"""Switch entity for Cisco RoomOS: microphone mute."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import RoomOSCoordinator
from .entity import RoomOSEntity

# Do Not Disturb requires a Timeout on some firmware versions; re-activated from
# HA whenever the switch is turned on, so a long ceiling (24h) just means "until
# turned off".
DO_NOT_DISTURB_TIMEOUT_MINUTES = 1440


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Cisco RoomOS switch entities."""
    coordinator: RoomOSCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            MicrophoneMuteSwitch(coordinator),
            DoNotDisturbSwitch(coordinator),
            SpeakerMuteSwitch(coordinator),
            SelfviewSwitch(coordinator),
        ]
    )


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


class DoNotDisturbSwitch(RoomOSEntity, SwitchEntity):
    """Suppresses incoming call notifications on the device."""

    _attr_icon = "mdi:do-not-disturb"

    def __init__(self, coordinator: RoomOSCoordinator) -> None:
        super().__init__(coordinator, "do_not_disturb")

    @property
    def is_on(self) -> bool | None:
        status = (self.coordinator.data or {}).get("Status", {})
        value = status.get("Conference", {}).get("DoNotDisturb")
        if value is None:
            return None
        return value == "Active"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_command(
            ["Conference", "DoNotDisturb", "Activate"],
            {"Timeout": DO_NOT_DISTURB_TIMEOUT_MINUTES},
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_command(["Conference", "DoNotDisturb", "Deactivate"])


class SpeakerMuteSwitch(RoomOSEntity, SwitchEntity):
    """Mutes/unmutes the device's speaker output (separate from the microphone mute)."""

    _attr_icon = "mdi:volume-mute"

    def __init__(self, coordinator: RoomOSCoordinator) -> None:
        super().__init__(coordinator, "speaker_mute")

    @property
    def is_on(self) -> bool | None:
        status = (self.coordinator.data or {}).get("Status", {})
        value = status.get("Audio", {}).get("VolumeMute")
        if value is None:
            return None
        return value == "On"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_command(["Audio", "Volume", "Mute"])

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_command(["Audio", "Volume", "Unmute"])


class SelfviewSwitch(RoomOSEntity, SwitchEntity):
    """Toggles the self-view video preview on the room's main display."""

    _attr_icon = "mdi:account-box-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: RoomOSCoordinator) -> None:
        super().__init__(coordinator, "selfview")

    @property
    def is_on(self) -> bool | None:
        status = (self.coordinator.data or {}).get("Status", {})
        value = status.get("Video", {}).get("Selfview", {}).get("Mode")
        if value is None:
            return None
        return value == "On"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_command(["Video", "Selfview", "Set"], {"Mode": "On"})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_command(["Video", "Selfview", "Set"], {"Mode": "Off"})
