"""Push-based data update coordinator for Cisco RoomOS."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from homeassistant.util import dt as dt_util

from .api import (
    RoomOSClient,
    RoomOSError,
    booking_sort_key,
    booking_summary,
    next_booking,
    next_joinable_booking,
    resolve_device_name,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Upper bound on the Bookings List window. The device only returns the bookings
# its calendar sync has populated, so a wide window pulls everything it can find
# (joinable or not) rather than only today's.
BOOKINGS_DAYS = 100
BOOKINGS_LIMIT = 100


class RoomOSCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Holds the live status tree, fed by the websocket feedback stream (no polling)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: RoomOSClient) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.entry = entry
        self.client = client
        self.unique_id: str = entry.unique_id or entry.entry_id
        self.data = client.status
        # Last presentation source picked via the select entity, used by the
        # "share locally" / "share to call" buttons.
        self.selected_presentation_source: int = 1
        # Every booking the device currently knows about (summary dicts from
        # api.booking_summary(), earliest first) and the next one, joinable or
        # not. Refreshed on a timer by the "next meeting" sensor and on demand by
        # the "refresh meetings" button, since bookings have no websocket feedback
        # events. next_booking is the earliest one still ahead of us; the "join
        # next meeting" button uses next_joinable_booking so a non-dialable
        # earliest entry (e.g. a plain calendar block) doesn't block joining a
        # later video meeting.
        #
        # Both are properties rather than fields refreshed alongside the list:
        # "next" is a question about the clock, and the list is only re-fetched
        # every few minutes.
        self.bookings: list[dict[str, Any]] = []

    @property
    def next_booking(self) -> dict[str, Any] | None:
        """The earliest booking that has not already finished."""
        return next_booking(self.bookings, dt_util.utcnow())

    @property
    def next_joinable_booking(self) -> dict[str, Any] | None:
        """The earliest booking still ahead of us that carries a dialable number.

        Evaluated fresh on every read rather than cached alongside `bookings`:
        the list is only refreshed every few minutes, and whether a booking has
        ended depends on the clock, not on when the device was last asked.
        """
        return next_joinable_booking(self.bookings, dt_util.utcnow())

    async def async_refresh_bookings(self) -> None:
        """Fetch every booking the device knows about and update listeners.

        Shared by the periodic poll and the manual refresh button. Failures are
        logged and left as-is (keeps the last known list) rather than raised.
        """
        try:
            raw = await self.client.async_list_bookings(days=BOOKINGS_DAYS, limit=BOOKINGS_LIMIT)
        except RoomOSError:
            _LOGGER.debug("Could not refresh Cisco RoomOS bookings", exc_info=True)
            return
        raw.sort(key=booking_sort_key)
        self.bookings = [booking_summary(booking) for booking in raw]
        self.async_update_listeners()

    def handle_client_update(self, status: dict[str, Any]) -> None:
        """Called from RoomOSClient whenever a feedback event changes the status tree."""
        self.async_set_updated_data(status)

    def handle_availability_change(self, available: bool) -> None:
        """Called from RoomOSClient when the websocket connects or drops."""
        self.async_update_listeners()

    def handle_client_event(self, event: dict[str, Any]) -> None:
        """Called from RoomOSClient for each xEvent notification (e.g. UI extension presses)."""
        self.hass.bus.async_fire(
            "cisco_roomos_event", {"device_id": self.unique_id, "event": event}
        )

    @property
    def device_info(self) -> DeviceInfo:
        status = (self.data or {}).get("Status", {})
        system_unit = status.get("SystemUnit", {})
        software = system_unit.get("Software", {})
        name = resolve_device_name(
            self.entry.data.get(CONF_NAME), system_unit.get("Name"), self.entry.title
        )
        return DeviceInfo(
            identifiers={(DOMAIN, self.unique_id)},
            manufacturer="Cisco",
            name=name,
            model=system_unit.get("ProductId"),
            sw_version=software.get("Version"),
            configuration_url=f"https://{self.entry.data['host']}",
        )
