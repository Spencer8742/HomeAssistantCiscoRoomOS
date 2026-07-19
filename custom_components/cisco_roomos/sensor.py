"""Sensors for Cisco RoomOS, plus the call/sharing entity services.

The call status sensor doubles as the service target for actions that need
free-form parameters (dial a number, send DTMF, pick a share connector) and
therefore don't map to a single button - see services.yaml.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_CALL_ID,
    ATTR_CONNECTOR_ID,
    ATTR_DIGITS,
    ATTR_NUMBER,
    ATTR_PROTOCOL,
    DOMAIN,
    SERVICE_ANSWER,
    SERVICE_DIAL,
    SERVICE_HANG_UP,
    SERVICE_REJECT,
    SERVICE_SEND_DTMF,
    SERVICE_SHARE_LOCAL,
    SERVICE_SHARE_REMOTE,
    SERVICE_SHARE_STOP,
)
from .coordinator import RoomOSCoordinator
from .entity import RoomOSEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Cisco RoomOS sensor entities and their entity services."""
    coordinator: RoomOSCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([CallStatusSensor(coordinator), StandbyStateSensor(coordinator)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_DIAL,
        {
            vol.Required(ATTR_NUMBER): cv.string,
            vol.Optional(ATTR_PROTOCOL): vol.In(["Sip", "H320", "H323", "Spark", "Auto"]),
        },
        "async_dial",
    )
    platform.async_register_entity_service(
        SERVICE_HANG_UP, {vol.Optional(ATTR_CALL_ID): cv.positive_int}, "async_hang_up"
    )
    platform.async_register_entity_service(
        SERVICE_ANSWER, {vol.Optional(ATTR_CALL_ID): cv.positive_int}, "async_answer"
    )
    platform.async_register_entity_service(
        SERVICE_REJECT, {vol.Optional(ATTR_CALL_ID): cv.positive_int}, "async_reject"
    )
    platform.async_register_entity_service(
        SERVICE_SEND_DTMF,
        {vol.Required(ATTR_DIGITS): cv.string, vol.Optional(ATTR_CALL_ID): cv.positive_int},
        "async_send_dtmf",
    )
    platform.async_register_entity_service(
        SERVICE_SHARE_LOCAL, {vol.Required(ATTR_CONNECTOR_ID): cv.positive_int}, "async_share_local"
    )
    platform.async_register_entity_service(
        SERVICE_SHARE_REMOTE, {vol.Required(ATTR_CONNECTOR_ID): cv.positive_int}, "async_share_remote"
    )
    platform.async_register_entity_service(SERVICE_SHARE_STOP, {}, "async_share_stop")


class CallStatusSensor(RoomOSEntity, SensorEntity):
    """Current call state (Idle, Ringing, Connected, ...) with call detail attributes."""

    _attr_icon = "mdi:phone"

    def __init__(self, coordinator: RoomOSCoordinator) -> None:
        super().__init__(coordinator, "call_status")

    @property
    def _calls(self) -> list[dict[str, Any]]:
        status = (self.coordinator.data or {}).get("Status", {})
        calls = status.get("Call", [])
        return [call for call in calls if isinstance(call, dict)] if isinstance(calls, list) else []

    @property
    def native_value(self) -> str:
        calls = self._calls
        if not calls:
            return "Idle"
        return calls[0].get("Status", "Idle")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        calls = self._calls
        if not calls:
            return {"active_calls": 0}
        first = calls[0]
        return {
            "active_calls": len(calls),
            "call_id": first.get("id"),
            "remote_number": first.get("RemoteNumber"),
            "display_name": first.get("DisplayName"),
            "direction": first.get("Direction"),
            "duration": first.get("Duration"),
        }

    async def async_dial(self, number: str, protocol: str | None = None) -> None:
        params: dict[str, Any] = {"Number": number}
        if protocol:
            params["Protocol"] = protocol
        await self.coordinator.client.async_command(["Dial"], params)

    async def async_hang_up(self, call_id: int | None = None) -> None:
        params = {"CallId": call_id} if call_id is not None else {}
        await self.coordinator.client.async_command(["Call", "Disconnect"], params)

    async def async_answer(self, call_id: int | None = None) -> None:
        params = {"CallId": call_id} if call_id is not None else {}
        await self.coordinator.client.async_command(["Call", "Accept"], params)

    async def async_reject(self, call_id: int | None = None) -> None:
        params = {"CallId": call_id} if call_id is not None else {}
        await self.coordinator.client.async_command(["Call", "Reject"], params)

    async def async_send_dtmf(self, digits: str, call_id: int | None = None) -> None:
        params: dict[str, Any] = {"DTMFString": digits}
        if call_id is not None:
            params["CallId"] = call_id
        await self.coordinator.client.async_command(["Call", "DTMFSend"], params)

    async def async_share_local(self, connector_id: int) -> None:
        await self.coordinator.client.async_command(
            ["Presentation", "Start"], {"ConnectorId": connector_id, "SendingMode": "LocalOnly"}
        )

    async def async_share_remote(self, connector_id: int) -> None:
        await self.coordinator.client.async_command(
            ["Presentation", "Start"], {"ConnectorId": connector_id, "SendingMode": "LocalRemote"}
        )

    async def async_share_stop(self) -> None:
        await self.coordinator.client.async_command(["Presentation", "Stop"])


class StandbyStateSensor(RoomOSEntity, SensorEntity):
    """Current power state: Off, Standby, EnteringStandby, or HalfWake."""

    _attr_icon = "mdi:power-standby"

    def __init__(self, coordinator: RoomOSCoordinator) -> None:
        super().__init__(coordinator, "standby_state")

    @property
    def native_value(self) -> str | None:
        status = (self.coordinator.data or {}).get("Status", {})
        return status.get("Standby", {}).get("State")
