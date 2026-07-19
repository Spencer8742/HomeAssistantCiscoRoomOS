"""Push-based data update coordinator for Cisco RoomOS."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import RoomOSClient, RoomOSError, booking_sort_key, booking_summary, resolve_device_name
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# How far ahead Bookings List looks; 1 = the rest of today.
BOOKINGS_DAYS = 1
BOOKINGS_LIMIT = 25


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
        # All of the day's bookings (summary dicts from api.booking_summary(),
        # earliest first) and the next one. Refreshed on a timer by the "next
        # meeting" sensor and on demand by the "refresh meetings" button, since
        # bookings have no websocket feedback events. next_booking is read by
        # the "join next meeting" button.
        self.bookings: list[dict[str, Any]] = []
        self.next_booking: dict[str, Any] | None = None

    async def async_refresh_bookings(self) -> None:
        """Fetch the day's bookings from the device and update listeners.

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
        self.next_booking = self.bookings[0] if self.bookings else None
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
