"""Switch entity for Cisco RoomOS: microphone mute."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import RoomOSCoordinator
from .entity import RoomOSEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Cisco RoomOS switch entities."""
    coordinator: RoomOSCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MicrophoneMuteSwitch(coordinator)])


class MicrophoneMuteSwitch(RoomOSEntity, SwitchEntity):
    """Mutes/unmutes the device's microphones."""

    _attr_icon = "mdi:microphone-off"

    def __init__(self, coordinator: RoomOSCoordinator) -> None:
        super().__init__(coordinator, "microphone_mute")

    @property
    def is_on(self) -> bool | None:
        status = (self.coordinator.data or {}).get("Status", {})
        mute = status.get("Audio", {}).get("Microphones", {}).get("Mute")
        if mute is None:
            return None
        return mute == "On"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_command(["Audio", "Microphones", "Mute"])

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_command(["Audio", "Microphones", "Unmute"])
