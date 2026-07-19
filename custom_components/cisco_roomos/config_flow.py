"""Config flow for the Cisco RoomOS integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .api import RoomOSAuthError, RoomOSClient, RoomOSConnectionError, RoomOSError, resolve_device_name
from .const import DEFAULT_PORT, DEFAULT_VERIFY_SSL, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_NAME, default=""): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
    }
)


async def _async_validate_and_identify(data: dict[str, Any]) -> tuple[str, str]:
    """Connect with the given data and return (unique_id, title). Raises RoomOSError on failure.

    A blank CONF_NAME means the user didn't set one: fall back to whatever the
    device itself reports, and failing that, the host/IP - which is exactly
    the "entities show up as the IP address" case the name field exists to avoid.
    """
    client = RoomOSClient(
        host=data[CONF_HOST],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        port=data[CONF_PORT],
        verify_ssl=data[CONF_VERIFY_SSL],
    )
    try:
        await client.async_connect()
        try:
            serial = await client.async_get(
                ["Status", "SystemUnit", "Hardware", "Module", "SerialNumber"]
            )
        except RoomOSError:
            serial = None
        try:
            device_name = await client.async_get(["Status", "SystemUnit", "Name"])
        except RoomOSError:
            device_name = None
    finally:
        await client.async_disconnect()

    unique_id = str(serial) if serial else data[CONF_HOST]
    title = resolve_device_name(
        data.get(CONF_NAME), str(device_name) if device_name else None, data[CONF_HOST]
    )
    return unique_id, title


class RoomOSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Cisco RoomOS."""

    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial connection setup step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                unique_id, title = await _async_validate_and_identify(user_input)
            except RoomOSAuthError:
                errors["base"] = "invalid_auth"
            except RoomOSConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating Cisco RoomOS connection")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured(updates=user_input)
                return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Handle re-authentication after the device rejects stored credentials."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask for updated credentials and re-validate them."""
        assert self._reauth_entry is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**self._reauth_entry.data, **user_input}
            try:
                await _async_validate_and_identify(data)
            except RoomOSAuthError:
                errors["base"] = "invalid_auth"
            except RoomOSConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating Cisco RoomOS connection")
                errors["base"] = "unknown"
            else:
                self.hass.config_entries.async_update_entry(self._reauth_entry, data=data)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=self._reauth_entry.data[CONF_USERNAME]): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            description_placeholders={"host": self._reauth_entry.data[CONF_HOST]},
            errors=errors,
        )
