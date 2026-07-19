"""The Cisco RoomOS integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .api import RoomOSAuthError, RoomOSClient, RoomOSConnectionError
from .const import DEFAULT_PORT, DEFAULT_VERIFY_SSL, DOMAIN, PLATFORMS
from .coordinator import RoomOSCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Cisco RoomOS from a config entry."""
    data = entry.data

    client = RoomOSClient(
        host=data[CONF_HOST],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        port=data.get(CONF_PORT, DEFAULT_PORT),
        verify_ssl=data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
    )

    coordinator = RoomOSCoordinator(hass, entry, client)
    client.on_update = coordinator.handle_client_update
    client.on_availability_change = coordinator.handle_availability_change
    client.on_event = coordinator.handle_client_event

    try:
        await client.async_connect()
    except RoomOSAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except RoomOSConnectionError as err:
        raise ConfigEntryNotReady(f"Unable to connect to {data[CONF_HOST]}: {err}") from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: RoomOSCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.client.async_disconnect()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options/data change (e.g. after reauth)."""
    await hass.config_entries.async_reload(entry.entry_id)
