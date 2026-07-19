"""Minimal async client for the Cisco RoomOS xAPI over WebSocket (JSON-RPC 2.0).

Protocol reference: Cisco "xAPI over WebSocket for RoomOS or CE software"
(D15427.02). The device exposes wss://<host>/ws, authenticated with HTTP
Basic Auth on the upgrade request, and exchanges JSON-RPC 2.0 messages:
  - xCommand/<Path/With/Slashes> to run actions (Dial, Standby Activate, ...)
  - xGet {"Path": [...]} to read a single Status/Configuration value
  - xFeedback/Subscribe {"Query": [...], "NotifyCurrentValue": true} to
    receive the current value plus a stream of xFeedback/Event notifications
    whenever anything under Query changes.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import itertools
import json
import logging
import ssl
from collections.abc import Callable
from typing import Any

import websockets

_LOGGER = logging.getLogger(__name__)

RECONNECT_MIN_DELAY = 2
RECONNECT_MAX_DELAY = 60
REQUEST_TIMEOUT = 15


class RoomOSError(Exception):
    """Base error for RoomOS communication."""


class RoomOSAuthError(RoomOSError):
    """Raised when the device rejects the username/password."""


class RoomOSConnectionError(RoomOSError):
    """Raised when the websocket connection cannot be established or is lost."""


class RoomOSCommandError(RoomOSError):
    """Raised when the device returns a JSON-RPC error for a request."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"{message} (code {code})")
        self.code = code
        self.data = data


def merge_status(target: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    """Recursively fold a Status/Configuration feedback fragment into target."""
    for key, value in update.items():
        if isinstance(value, dict):
            existing = target.get(key)
            target[key] = merge_status(existing if isinstance(existing, dict) else {}, value)
        elif isinstance(value, list):
            target[key] = _merge_status_list(target.get(key), value)
        else:
            target[key] = value
    return target


def _merge_status_list(existing: Any, update: list[Any]) -> list[Any]:
    """Merge a multi-instance status array, matching items by their 'id' field."""
    if not all(isinstance(item, dict) and "id" in item for item in update):
        # Not a keyed multi-instance list (e.g. plain scalars) - replace wholesale.
        return update
    by_id: dict[Any, dict[str, Any]] = {}
    if isinstance(existing, list):
        by_id = {item["id"]: item for item in existing if isinstance(item, dict) and "id" in item}
    for item in update:
        current = by_id.get(item["id"], {})
        by_id[item["id"]] = merge_status(dict(current), item)
    return sorted(by_id.values(), key=lambda item: item["id"])


def _booking_time(booking: dict[str, Any]) -> dict[str, Any]:
    time_info = booking.get("Time")
    if isinstance(time_info, list):
        time_info = time_info[0] if time_info else {}
    return time_info if isinstance(time_info, dict) else {}


def booking_sort_key(booking: dict[str, Any]) -> str:
    """Sortable key for a Bookings/List entry: its start time, earliest first."""
    return _booking_time(booking).get("StartTime") or ""


def booking_summary(booking: dict[str, Any]) -> dict[str, Any]:
    """Pull the fields the "next meeting" sensor needs out of a raw Booking entry.

    Field availability (organizer name, callback numbers, ...) depends on which
    calendar service (Webex, Exchange, Google) the device is paired with, so
    everything here is best-effort with a fallback to None.
    """
    time_info = _booking_time(booking)
    organizer = booking.get("Organizer")
    organizer_name = None
    if isinstance(organizer, dict):
        organizer_name = (
            " ".join(filter(None, [organizer.get("FirstName"), organizer.get("LastName")]))
            or organizer.get("Email")
        )
    return {
        "id": booking.get("Id"),
        "title": booking.get("Title") or "Meeting",
        "start_time": time_info.get("StartTime"),
        "end_time": time_info.get("EndTime"),
        "organizer": organizer_name,
    }


def resolve_device_name(custom_name: str | None, reported_name: str | None, fallback: str) -> str:
    """What to call the device: a user-chosen name always wins, even over what
    the device itself reports, since devices that never had SystemUnit.Name
    set otherwise report it blank or as their own host/IP. Falls through to
    the device-reported name, then to `fallback` (typically the host/IP).
    """
    for candidate in (custom_name, reported_name):
        if candidate and candidate.strip():
            return candidate.strip()
    return fallback


class RoomOSClient:
    """Persistent WebSocket connection to a Cisco RoomOS device's xAPI."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 443,
        verify_ssl: bool = False,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._verify_ssl = verify_ssl

        self.on_update: Callable[[dict[str, Any]], None] | None = None
        self.on_availability_change: Callable[[bool], None] | None = None
        # Called with the raw nested dict under "Event" for each xEvent notification
        # (e.g. UI extension button presses) - these are momentary, not stateful,
        # so they're dispatched rather than merged into `status`.
        self.on_event: Callable[[dict[str, Any]], None] | None = None

        self._ws: Any = None
        self._id_counter = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._status: dict[str, Any] = {}
        self._reader_task: asyncio.Task | None = None
        self._run_task: asyncio.Task | None = None
        self._closing = False
        self._available = False

    @property
    def status(self) -> dict[str, Any]:
        """The merged Status/Configuration tree built from feedback events."""
        return self._status

    @property
    def available(self) -> bool:
        return self._available

    @property
    def url(self) -> str:
        return f"wss://{self._host}:{self._port}/ws"

    async def async_connect(self) -> None:
        """Open the connection, subscribe to feedback, and start the reconnect loop."""
        self._closing = False
        await self._async_open_socket()
        self._reader_task = asyncio.create_task(self._async_reader())
        await self._async_subscribe_feedback()
        self._set_available(True)
        self._run_task = asyncio.create_task(self._async_run())

    async def async_disconnect(self) -> None:
        """Close the connection and stop reconnecting."""
        self._closing = True
        if self._run_task is not None:
            self._run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._run_task
        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
        self._fail_pending(RoomOSConnectionError("Client is shutting down"))

    async def async_command(self, path: list[str], params: dict[str, Any] | None = None) -> Any:
        """Run an xCommand, e.g. path=['Standby', 'Activate']."""
        return await self._async_request(f"xCommand/{'/'.join(path)}", params or {})

    async def async_get(self, path: list[str]) -> Any:
        """Read a single Status or Configuration value, e.g. ['Status','SystemUnit','Name']."""
        return await self._async_request("xGet", {"Path": path})

    async def async_list_bookings(self, days: int = 1, limit: int = 10) -> list[dict[str, Any]]:
        """Return the raw Booking entries from the device's calendar for the next `days`."""
        result = await self.async_command(["Bookings", "List"], {"Days": days, "Limit": limit})
        bookings = result.get("Booking", []) if isinstance(result, dict) else []
        return [booking for booking in bookings if isinstance(booking, dict)]

    async def _async_open_socket(self) -> None:
        ssl_context = ssl.create_default_context()
        if not self._verify_ssl:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        auth = base64.b64encode(f"{self._username}:{self._password}".encode()).decode()
        headers = {"Authorization": f"Basic {auth}"}
        try:
            self._ws = await websockets.connect(
                self.url,
                additional_headers=headers,
                ssl=ssl_context,
                open_timeout=REQUEST_TIMEOUT,
                max_size=2**22,
            )
        except Exception as err:  # noqa: BLE001 - websockets exception types vary by version
            response = getattr(err, "response", None)
            status_code = getattr(response, "status_code", None) or getattr(err, "status_code", None)
            if status_code in (401, 403):
                raise RoomOSAuthError("Invalid username or password") from err
            raise RoomOSConnectionError(str(err) or err.__class__.__name__) from err

    async def _async_subscribe_feedback(self) -> None:
        # Two separate subscriptions: the whole Status tree (stateful, seeded with
        # NotifyCurrentValue) and the whole Event tree (momentary notifications,
        # e.g. UI extension button presses, dispatched via on_event instead).
        await self._async_request(
            "xFeedback/Subscribe", {"Query": ["Status"], "NotifyCurrentValue": True}
        )
        await self._async_request(
            "xFeedback/Subscribe", {"Query": ["Event"], "NotifyCurrentValue": False}
        )

    async def _async_reader(self) -> None:
        try:
            async for raw in self._ws:
                self._handle_message(raw)
        except Exception:  # noqa: BLE001 - any read failure means the connection is gone
            pass
        finally:
            self._set_available(False)
            self._fail_pending(RoomOSConnectionError("Connection lost"))

    async def _async_run(self) -> None:
        """Supervise the connection, reconnecting with backoff whenever it drops."""
        delay = RECONNECT_MIN_DELAY
        while not self._closing:
            if self._reader_task is not None:
                with contextlib.suppress(asyncio.CancelledError):
                    await self._reader_task
            if self._closing:
                break
            _LOGGER.warning(
                "Lost connection to Cisco RoomOS device at %s, retrying in %ss", self._host, delay
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX_DELAY)
            try:
                await self._async_open_socket()
                self._reader_task = asyncio.create_task(self._async_reader())
                await self._async_subscribe_feedback()
            except RoomOSError as err:
                _LOGGER.debug("Reconnect attempt to %s failed: %s", self._host, err)
                continue
            self._set_available(True)
            delay = RECONNECT_MIN_DELAY

    def _fail_pending(self, err: Exception) -> None:
        pending, self._pending = self._pending, {}
        for fut in pending.values():
            if not fut.done():
                fut.set_exception(err)

    def _set_available(self, available: bool) -> None:
        if self._available != available:
            self._available = available
            if self.on_availability_change:
                self.on_availability_change(available)

    def _handle_message(self, raw: str | bytes) -> None:
        try:
            message = json.loads(raw)
        except ValueError:
            _LOGGER.debug("Ignoring non-JSON websocket message from %s", self._host)
            return

        if "id" in message and ("result" in message or "error" in message):
            fut = self._pending.pop(message["id"], None)
            if fut is None or fut.done():
                return
            if "error" in message:
                error = message["error"]
                fut.set_exception(
                    RoomOSCommandError(
                        error.get("code", -1), error.get("message", "Unknown error"), error.get("data")
                    )
                )
            else:
                fut.set_result(message.get("result"))
            return

        if message.get("method") == "xFeedback/Event":
            params = message.get("params") or {}
            changed = False
            for key in ("Status", "Configuration"):
                if key in params:
                    merge_status(self._status.setdefault(key, {}), params[key])
                    changed = True
            if changed and self.on_update:
                self.on_update(self._status)
            event = params.get("Event")
            if isinstance(event, dict) and self.on_event:
                self.on_event(event)

    async def _async_request(self, method: str, params: dict[str, Any]) -> Any:
        if self._ws is None:
            raise RoomOSConnectionError("Not connected")
        request_id = next(self._id_counter)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = fut
        message = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        try:
            await self._ws.send(json.dumps(message))
        except Exception as err:  # noqa: BLE001
            self._pending.pop(request_id, None)
            raise RoomOSConnectionError("Connection closed while sending request") from err
        try:
            return await asyncio.wait_for(fut, timeout=REQUEST_TIMEOUT)
        except asyncio.TimeoutError as err:
            self._pending.pop(request_id, None)
            raise RoomOSConnectionError(f"Timed out waiting for response to {method}") from err
