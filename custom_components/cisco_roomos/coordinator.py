"""Push-based data update coordinator for Cisco RoomOS."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import RoomOSClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


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
        # Summary dict from api.booking_summary(), refreshed by the "next
        # meeting" sensor's poll; read by the "join next meeting" button.
        self.next_booking: dict[str, Any] | None = None

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
        return DeviceInfo(
            identifiers={(DOMAIN, self.unique_id)},
            manufacturer="Cisco",
            name=system_unit.get("Name") or self.entry.title,
            model=system_unit.get("ProductId"),
            sw_version=software.get("Version"),
            configuration_url=f"https://{self.entry.data['host']}",
        )
