"""Base entity for Cisco RoomOS."""

from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import RoomOSCoordinator


class RoomOSEntity(CoordinatorEntity[RoomOSCoordinator]):
    """Common base for all Cisco RoomOS entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: RoomOSCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.unique_id}_{key}"
        self._attr_translation_key = key

    @property
    def device_info(self) -> DeviceInfo:
        return self.coordinator.device_info

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.client.available
