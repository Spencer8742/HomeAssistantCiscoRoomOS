"""Sensors for Cisco RoomOS, plus the call/sharing entity services.

The call status sensor doubles as the service target for actions that need
free-form parameters (dial a number, send DTMF, pick a share connector) and
therefore don't map to a single button - see services.yaml.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    ATTR_CALL_ID,
    ATTR_CONNECTOR_ID,
    ATTR_DIGITS,
    ATTR_NUMBER,
    ATTR_PROTOCOL,
    DOMAIN,
    SERVICE_ANSWER,
    SERVICE_DIAL,
    SERVICE_HANG_UP,
    SERVICE_REJECT,
    SERVICE_SEND_DTMF,
    SERVICE_SHARE_LOCAL,
    SERVICE_SHARE_REMOTE,
    SERVICE_SHARE_STOP,
)
from .coordinator import RoomOSCoordinator
from .entity import RoomOSEntity

_LOGGER = logging.getLogger(__name__)

BOOKINGS_REFRESH_INTERVAL = timedelta(minutes=5)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Cisco RoomOS sensor entities and their entity services."""
    coordinator: RoomOSCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            CallStatusSensor(coordinator),
            StandbyStateSensor(coordinator),
            PeopleCountSensor(coordinator),
            AmbientNoiseSensor(coordinator),
            NextMeetingSensor(coordinator),
            UptimeSensor(coordinator),
            IpAddressSensor(coordinator),
            SoftwareVersionSensor(coordinator),
            ActiveAlertsSensor(coordinator),
        ]
    )

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_DIAL,
        {
            vol.Required(ATTR_NUMBER): cv.string,
            vol.Optional(ATTR_PROTOCOL): vol.In(["Sip", "H320", "H323", "Spark", "Auto"]),
        },
        "async_dial",
    )
    platform.async_register_entity_service(
        SERVICE_HANG_UP, {vol.Optional(ATTR_CALL_ID): cv.positive_int}, "async_hang_up"
    )
    platform.async_register_entity_service(
        SERVICE_ANSWER, {vol.Optional(ATTR_CALL_ID): cv.positive_int}, "async_answer"
    )
    platform.async_register_entity_service(
        SERVICE_REJECT, {vol.Optional(ATTR_CALL_ID): cv.positive_int}, "async_reject"
    )
    platform.async_register_entity_service(
        SERVICE_SEND_DTMF,
        {vol.Required(ATTR_DIGITS): cv.string, vol.Optional(ATTR_CALL_ID): cv.positive_int},
        "async_send_dtmf",
    )
    platform.async_register_entity_service(
        SERVICE_SHARE_LOCAL, {vol.Required(ATTR_CONNECTOR_ID): cv.positive_int}, "async_share_local"
    )
    platform.async_register_entity_service(
        SERVICE_SHARE_REMOTE, {vol.Required(ATTR_CONNECTOR_ID): cv.positive_int}, "async_share_remote"
    )
    platform.async_register_entity_service(SERVICE_SHARE_STOP, {}, "async_share_stop")


class CallStatusSensor(RoomOSEntity, SensorEntity):
    """Current call state (Idle, Ringing, Connected, ...) with call detail attributes."""

    _attr_icon = "mdi:phone"

    def __init__(self, coordinator: RoomOSCoordinator) -> None:
        super().__init__(coordinator, "call_status")

    @property
    def _calls(self) -> list[dict[str, Any]]:
        status = (self.coordinator.data or {}).get("Status", {})
        calls = status.get("Call", [])
        return [call for call in calls if isinstance(call, dict)] if isinstance(calls, list) else []

    @property
    def native_value(self) -> str:
        calls = self._calls
        if not calls:
            return "Idle"
        return calls[0].get("Status", "Idle")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        calls = self._calls
        if not calls:
            return {"active_calls": 0}
        first = calls[0]
        return {
            "active_calls": len(calls),
            "call_id": first.get("id"),
            "remote_number": first.get("RemoteNumber"),
            "display_name": first.get("DisplayName"),
            "direction": first.get("Direction"),
            "duration": first.get("Duration"),
        }

    async def async_dial(self, number: str, protocol: str | None = None) -> None:
        params: dict[str, Any] = {"Number": number}
        if protocol:
            params["Protocol"] = protocol
        await self.coordinator.client.async_command(["Dial"], params)

    async def async_hang_up(self, call_id: int | None = None) -> None:
        params = {"CallId": call_id} if call_id is not None else {}
        await self.coordinator.client.async_command(["Call", "Disconnect"], params)

    async def async_answer(self, call_id: int | None = None) -> None:
        params = {"CallId": call_id} if call_id is not None else {}
        await self.coordinator.client.async_command(["Call", "Accept"], params)

    async def async_reject(self, call_id: int | None = None) -> None:
        params = {"CallId": call_id} if call_id is not None else {}
        await self.coordinator.client.async_command(["Call", "Reject"], params)

    async def async_send_dtmf(self, digits: str, call_id: int | None = None) -> None:
        params: dict[str, Any] = {"DTMFString": digits}
        if call_id is not None:
            params["CallId"] = call_id
        await self.coordinator.client.async_command(["Call", "DTMFSend"], params)

    async def async_share_local(self, connector_id: int) -> None:
        await self.coordinator.client.async_command(
            ["Presentation", "Start"], {"ConnectorId": connector_id, "SendingMode": "LocalOnly"}
        )

    async def async_share_remote(self, connector_id: int) -> None:
        await self.coordinator.client.async_command(
            ["Presentation", "Start"], {"ConnectorId": connector_id, "SendingMode": "LocalRemote"}
        )

    async def async_share_stop(self) -> None:
        await self.coordinator.client.async_command(["Presentation", "Stop"])


class StandbyStateSensor(RoomOSEntity, SensorEntity):
    """Current power state: Off, Standby, EnteringStandby, or HalfWake."""

    _attr_icon = "mdi:power-standby"

    def __init__(self, coordinator: RoomOSCoordinator) -> None:
        super().__init__(coordinator, "standby_state")

    @property
    def native_value(self) -> str | None:
        status = (self.coordinator.data or {}).get("Status", {})
        return status.get("Standby", {}).get("State")


class PeopleCountSensor(RoomOSEntity, SensorEntity):
    """Number of people detected in the room by RoomAnalytics (requires that feature enabled)."""

    _attr_icon = "mdi:account-group"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: RoomOSCoordinator) -> None:
        super().__init__(coordinator, "people_count")

    @property
    def native_value(self) -> int | None:
        status = (self.coordinator.data or {}).get("Status", {})
        value = status.get("RoomAnalytics", {}).get("PeopleCount", {}).get("Current")
        try:
            value = int(value)
        except (TypeError, ValueError):
            return None
        # -1 means the feature is disabled or not supported on this device.
        return value if value >= 0 else None


class AmbientNoiseSensor(RoomOSEntity, SensorEntity):
    """Estimated stationary background noise level in the room."""

    _attr_icon = "mdi:waveform"
    _attr_native_unit_of_measurement = "dBA"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: RoomOSCoordinator) -> None:
        super().__init__(coordinator, "ambient_noise")

    @property
    def native_value(self) -> int | None:
        status = (self.coordinator.data or {}).get("Status", {})
        value = status.get("RoomAnalytics", {}).get("AmbientNoise", {}).get("Level", {}).get("A")
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


class NextMeetingSensor(RoomOSEntity, SensorEntity):
    """The next calendar-booked meeting, polled periodically (bookings have no feedback events).

    Requires the device to be paired with a calendar service (Webex, Hybrid
    Calendar for Exchange/Google, ...); otherwise this always reads "No
    upcoming meetings".
    """

    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: RoomOSCoordinator) -> None:
        super().__init__(coordinator, "next_meeting")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._async_refresh_bookings, BOOKINGS_REFRESH_INTERVAL
            )
        )
        await self.coordinator.async_refresh_bookings()

    async def _async_refresh_bookings(self, _now: Any = None) -> None:
        await self.coordinator.async_refresh_bookings()

    @property
    def native_value(self) -> str:
        booking = self.coordinator.next_booking
        return booking["title"] if booking else "No upcoming meetings"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        bookings = self.coordinator.bookings
        booking = self.coordinator.next_booking
        # `meetings` lists every booking the device knows about (joinable or not)
        # so a card can show them all; the top-level keys mirror the next meeting
        # for simple templates.
        attrs: dict[str, Any] = {
            "meeting_count": len(bookings),
            "meetings": [
                {
                    "title": item["title"],
                    "start_time": item["start_time"],
                    "end_time": item["end_time"],
                    "organizer": item["organizer"],
                    "joinable": item["joinable"],
                }
                for item in bookings
            ],
        }
        if booking:
            attrs.update(
                {
                    "booking_id": booking["id"],
                    "start_time": booking["start_time"],
                    "end_time": booking["end_time"],
                    "organizer": booking["organizer"],
                }
            )
        return attrs


class UptimeSensor(RoomOSEntity, SensorEntity):
    """Seconds since the device last restarted."""

    _attr_icon = "mdi:clock-outline"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: RoomOSCoordinator) -> None:
        super().__init__(coordinator, "uptime")

    @property
    def native_value(self) -> int | None:
        status = (self.coordinator.data or {}).get("Status", {})
        value = status.get("SystemUnit", {}).get("Uptime")
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


class IpAddressSensor(RoomOSEntity, SensorEntity):
    """The device's primary IPv4 address."""

    _attr_icon = "mdi:ip-network"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: RoomOSCoordinator) -> None:
        super().__init__(coordinator, "ip_address")

    @property
    def native_value(self) -> str | None:
        status = (self.coordinator.data or {}).get("Status", {})
        interfaces = status.get("Network", [])
        if not isinstance(interfaces, list) or not interfaces:
            return None
        first = interfaces[0]
        return first.get("IPv4", {}).get("Address") if isinstance(first, dict) else None


class SoftwareVersionSensor(RoomOSEntity, SensorEntity):
    """The currently installed RoomOS software version."""

    _attr_icon = "mdi:chip"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: RoomOSCoordinator) -> None:
        super().__init__(coordinator, "software_version")

    @property
    def native_value(self) -> str | None:
        status = (self.coordinator.data or {}).get("Status", {})
        return status.get("SystemUnit", {}).get("Software", {}).get("Version")


class ActiveAlertsSensor(RoomOSEntity, SensorEntity):
    """Number of active diagnostics messages (errors/warnings) reported by the device."""

    _attr_icon = "mdi:alert-circle-outline"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: RoomOSCoordinator) -> None:
        super().__init__(coordinator, "active_alerts")

    @property
    def _messages(self) -> list[dict[str, Any]]:
        status = (self.coordinator.data or {}).get("Status", {})
        messages = status.get("Diagnostics", {}).get("Message", [])
        if not isinstance(messages, list):
            return []
        return [message for message in messages if isinstance(message, dict)]

    @property
    def native_value(self) -> int:
        return len(self._messages)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "messages": [
                {
                    "level": message.get("Level"),
                    "type": message.get("Type"),
                    "description": message.get("Description"),
                }
                for message in self._messages[:10]
            ]
        }
