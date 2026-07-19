"""Binary sensors for Cisco RoomOS: call and content-sharing activity."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ACTIVE_CALL_STATES, DOMAIN
from .coordinator import RoomOSCoordinator
from .entity import RoomOSEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Cisco RoomOS binary sensor entities."""
    coordinator: RoomOSCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            InCallBinarySensor(coordinator),
            SharingContentBinarySensor(coordinator),
            OccupancyBinarySensor(coordinator),
        ]
    )


class InCallBinarySensor(RoomOSEntity, BinarySensorEntity):
    """On while at least one call is active."""

    _attr_icon = "mdi:phone-in-talk"

    def __init__(self, coordinator: RoomOSCoordinator) -> None:
        super().__init__(coordinator, "in_call")

    @property
    def is_on(self) -> bool:
        status = (self.coordinator.data or {}).get("Status", {})
        calls = status.get("Call", [])
        if not isinstance(calls, list):
            return False
        return any(isinstance(call, dict) and call.get("Status") in ACTIVE_CALL_STATES for call in calls)


class SharingContentBinarySensor(RoomOSEntity, BinarySensorEntity):
    """On while a presentation (local or remote) is being shared."""

    _attr_icon = "mdi:monitor-share"

    def __init__(self, coordinator: RoomOSCoordinator) -> None:
        super().__init__(coordinator, "sharing_content")

    @property
    def is_on(self) -> bool:
        status = (self.coordinator.data or {}).get("Status", {})
        mode = status.get("Conference", {}).get("Presentation", {}).get("Mode")
        return mode not in (None, "Off")


class OccupancyBinarySensor(RoomOSEntity, BinarySensorEntity):
    """On while RoomAnalytics detects someone in the room.

    Requires RoomAnalytics people presence detection to be enabled on the
    device (Configuration.RoomAnalytics.PeoplePresenceDetector); unavailable
    on devices without that feature.
    """

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def __init__(self, coordinator: RoomOSCoordinator) -> None:
        super().__init__(coordinator, "occupancy")

    @property
    def is_on(self) -> bool | None:
        status = (self.coordinator.data or {}).get("Status", {})
        presence = status.get("RoomAnalytics", {}).get("PeoplePresence")
        if presence is None:
            return None
        return presence == "Yes"
