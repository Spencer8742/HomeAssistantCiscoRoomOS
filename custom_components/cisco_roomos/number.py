"""Number entity for Cisco RoomOS: master volume."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import RoomOSCoordinator
from .entity import RoomOSEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Cisco RoomOS number entities."""
    coordinator: RoomOSCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([VolumeNumber(coordinator)])


class VolumeNumber(RoomOSEntity, NumberEntity):
    """Master output volume, 0-100."""

    _attr_icon = "mdi:volume-high"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: RoomOSCoordinator) -> None:
        super().__init__(coordinator, "volume")

    @property
    def native_value(self) -> float | None:
        status = (self.coordinator.data or {}).get("Status", {})
        value = status.get("Audio", {}).get("Volume")
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.client.async_command(["Audio", "Volume", "Set"], {"Level": int(value)})
