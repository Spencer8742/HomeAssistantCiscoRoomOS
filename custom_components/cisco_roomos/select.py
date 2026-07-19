"""Select entity for Cisco RoomOS: which local video input to present/share."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import RoomOSCoordinator
from .entity import RoomOSEntity

_FALLBACK_OPTIONS = [str(i) for i in range(1, 9)]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Cisco RoomOS presentation source select entity."""
    coordinator: RoomOSCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PresentationSourceSelect(coordinator)])


class PresentationSourceSelect(RoomOSEntity, SelectEntity):
    """Picks which video input connector the share buttons act on.

    This only stores a selection; use the "Share locally" / "Share to call"
    buttons (or the share_local / share_remote services) to actually start
    sharing that source.
    """

    _attr_icon = "mdi:presentation"

    def __init__(self, coordinator: RoomOSCoordinator) -> None:
        super().__init__(coordinator, "presentation_source")

    @property
    def _connectors(self) -> dict[str, str]:
        status = (self.coordinator.data or {}).get("Status", {})
        connectors = status.get("Video", {}).get("Input", {}).get("Connector", [])
        if not isinstance(connectors, list):
            return {}
        labels: dict[str, str] = {}
        for connector in connectors:
            if not isinstance(connector, dict) or "id" not in connector:
                continue
            connector_id = str(connector["id"])
            name = connector.get("Name") or connector.get("Type") or f"Input {connector_id}"
            labels[connector_id] = f"{connector_id}: {name}"
        return labels

    @property
    def options(self) -> list[str]:
        connectors = self._connectors
        return list(connectors.values()) if connectors else _FALLBACK_OPTIONS

    @property
    def current_option(self) -> str | None:
        options = self.options
        selected = str(self.coordinator.selected_presentation_source)
        for option in options:
            if option == selected or option.startswith(f"{selected}:"):
                return option
        return options[0] if options else None

    async def async_select_option(self, option: str) -> None:
        try:
            connector_id = int(option.split(":")[0])
        except (ValueError, IndexError):
            return
        self.coordinator.selected_presentation_source = connector_id
        self.async_write_ha_state()
