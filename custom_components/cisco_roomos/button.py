"""Button entities for Cisco RoomOS: power and call/sharing controls."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import RoomOSCoordinator
from .entity import RoomOSEntity

DESCRIPTIONS: tuple[ButtonEntityDescription, ...] = (
    ButtonEntityDescription(key="wake_up", icon="mdi:power-on"),
    ButtonEntityDescription(key="standby", icon="mdi:power-sleep"),
    ButtonEntityDescription(key="answer_call", icon="mdi:phone-in-talk"),
    ButtonEntityDescription(key="reject_call", icon="mdi:phone-cancel"),
    ButtonEntityDescription(key="hang_up", icon="mdi:phone-hangup"),
    ButtonEntityDescription(key="share_local", icon="mdi:monitor-share"),
    ButtonEntityDescription(key="share_to_call", icon="mdi:monitor-share"),
    ButtonEntityDescription(key="stop_sharing", icon="mdi:monitor-off"),
    ButtonEntityDescription(key="join_next_meeting", icon="mdi:calendar-check"),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Cisco RoomOS button entities."""
    coordinator: RoomOSCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(RoomOSButton(coordinator, description) for description in DESCRIPTIONS)


class RoomOSButton(RoomOSEntity, ButtonEntity):
    """A momentary action button that maps to a single xCommand."""

    def __init__(self, coordinator: RoomOSCoordinator, description: ButtonEntityDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        client = self.coordinator.client
        key = self.entity_description.key
        source = self.coordinator.selected_presentation_source

        if key == "wake_up":
            await client.async_command(["Standby", "Deactivate"])
        elif key == "standby":
            await client.async_command(["Standby", "Activate"])
        elif key == "answer_call":
            await client.async_command(["Call", "Accept"])
        elif key == "reject_call":
            await client.async_command(["Call", "Reject"])
        elif key == "hang_up":
            await client.async_command(["Call", "Disconnect"])
        elif key == "share_local":
            await client.async_command(
                ["Presentation", "Start"],
                {"ConnectorId": source, "SendingMode": "LocalOnly"},
            )
        elif key == "share_to_call":
            await client.async_command(
                ["Presentation", "Start"],
                {"ConnectorId": source, "SendingMode": "LocalRemote"},
            )
        elif key == "stop_sharing":
            await client.async_command(["Presentation", "Stop"])
        elif key == "join_next_meeting":
            booking = self.coordinator.next_booking
            if not booking or not booking.get("number"):
                raise HomeAssistantError("No upcoming meeting to join")
            params = {"Number": booking["number"]}
            if booking.get("protocol"):
                params["Protocol"] = booking["protocol"]
            if booking.get("id"):
                params["BookingId"] = booking["id"]
            await client.async_command(["Dial"], params)
