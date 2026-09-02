"""The Uplift Desk integration."""

from __future__ import annotations

import logging

from uplift_ble.desk_enums import DeskUnit

from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_FALLBACK_UNIT, DOMAIN
from .coordinator import (
    UpliftDeskBluetoothCoordinator,
    Uplift_Desk_DeskConfigEntry,
)

_PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: Uplift_Desk_DeskConfigEntry
) -> bool:
    """Set up Uplift Desk from a config entry."""

    address = entry.data[CONF_ADDRESS]

    ble_device = async_ble_device_from_address(hass, address)
    if not ble_device:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="no_device_found",
            translation_placeholders={"address": address},
        )

    coordinator = UpliftDeskBluetoothCoordinator(hass, entry, ble_device)
    entry.runtime_data = coordinator

    await coordinator.async_connect()

    await coordinator.async_read_desk_units()
    await coordinator.async_read_desk_height()
    coordinator.async_set_updated_data(coordinator._desk)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    _LOGGER.debug(
        "Initializing Uplift Desk for desk %s: %s",
        entry.title,
        entry.data["address"],
    )

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    return True


async def async_reload_entry(
    hass: HomeAssistant, entry: Uplift_Desk_DeskConfigEntry
) -> None:
    """Reload the config entry after options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(
    hass: HomeAssistant, entry: Uplift_Desk_DeskConfigEntry
) -> bool:
    """Migrate existing entries to explicit fallback-unit options."""
    if entry.version == 1 and entry.minor_version < 2:
        options = dict(entry.options)
        options.setdefault(CONF_FALLBACK_UNIT, DeskUnit.CENTIMETERS.value)
        hass.config_entries.async_update_entry(
            entry, options=options, minor_version=2
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: Uplift_Desk_DeskConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: UpliftDeskBluetoothCoordinator | None = getattr(
        entry, "runtime_data", None
    )

    unload_ok = await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)

    if unload_ok and coordinator is not None:
        await coordinator.async_disconnect()

    return unload_ok
