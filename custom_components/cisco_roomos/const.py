"""Constants for the Cisco RoomOS integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "cisco_roomos"

DEFAULT_PORT = 443
DEFAULT_VERIFY_SSL = False

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

SERVICE_DIAL = "dial"
SERVICE_HANG_UP = "hang_up"
SERVICE_ANSWER = "answer"
SERVICE_REJECT = "reject"
SERVICE_SEND_DTMF = "send_dtmf"
SERVICE_SHARE_LOCAL = "share_local"
SERVICE_SHARE_REMOTE = "share_remote"
SERVICE_SHARE_STOP = "share_stop"

ATTR_NUMBER = "number"
ATTR_PROTOCOL = "protocol"
ATTR_CALL_ID = "call_id"
ATTR_DIGITS = "digits"
ATTR_CONNECTOR_ID = "connector_id"

ACTIVE_CALL_STATES = {"Dialling", "Ringing", "Connecting", "Connected", "OnHold", "Disconnecting"}
