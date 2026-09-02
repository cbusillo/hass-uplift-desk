"""The Uplift Desk integration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from uplift_ble.ble_protos import BLEClientProtocol, BLEDeviceProtocol
from uplift_ble.desk_configs import DeskVariant
from uplift_ble.desk_controller import DeskController
from uplift_ble.desk_enums import (
    DeskEventType,
    DeskUnit,
)
from uplift_ble.desk_validator import DeskValidator
from uplift_ble.models import DiscoveredDesk as ValidatedDesk

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    BLEAK_TIMEOUT_SECONDS,
    CONF_FALLBACK_UNIT,
    FALLBACK_UNIT_NONE,
)
from .models import DiscoveredDesk

type Uplift_Desk_DeskConfigEntry = ConfigEntry[UpliftDeskBluetoothCoordinator]

_LOGGER: logging.Logger = logging.getLogger(__name__)

_EXTENDED_PRESET_VARIANTS = {
    DeskVariant.JIECANG_0x00FF,
    DeskVariant.JIECANG_0xFE60,
}


def _parse_fallback_unit(value: str | None) -> DeskUnit | None:
    """Parse a configured fallback unit."""
    if not value or value == FALLBACK_UNIT_NONE:
        return None
    try:
        return DeskUnit(value)
    except ValueError:
        _LOGGER.warning("Ignoring invalid fallback unit: %s", value)
        return None


def _generate_existing_client_factory(
    bleak_client: BleakClient,
) -> Callable[..., BLEClientProtocol]:
    def _existing_client_factory(
        device: BLEDeviceProtocol, timeout: float
    ) -> BLEClientProtocol:
        return bleak_client

    return _existing_client_factory


class UpliftDeskBluetoothCoordinator(DataUpdateCoordinator):
    """Define the Update Coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: Uplift_Desk_DeskConfigEntry,
        desk_ble_device: BLEDevice,
    ) -> None:
        """Initialize the Data Coordinator."""
        super().__init__(hass, _LOGGER, name="Uplift Desk", config_entry=config_entry)
        _LOGGER.debug(
            "Initializing coordinator for desk %s:%s with config entry %s",
            config_entry.title,
            desk_ble_device.address,
            config_entry,
        )

        self._discovered_desk = DiscoveredDesk(
            name=config_entry.title, address=desk_ble_device.address
        )
        self._desk_ble_device = desk_ble_device
        self._desk = None
        self._desk_lock = asyncio.Lock()
        self._disconnecting = False
        self._validated_desk: ValidatedDesk | None = None
        self._desk_variant: DeskVariant | None = None
        self._fallback_unit = _parse_fallback_unit(
            config_entry.options.get(CONF_FALLBACK_UNIT)
        )

    async def _async_dispose_controller(self, controller: DeskController) -> None:
        client = getattr(controller, "client", None)
        try:
            await controller.stop()
        except Exception:
            _LOGGER.debug(
                "Error stopping desk controller for %s",
                self.desk_info,
                exc_info=True,
            )
        finally:
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    _LOGGER.debug(
                        "Error disconnecting BLE client for %s",
                        self.desk_info,
                        exc_info=True,
                    )
                finally:
                    if getattr(controller, "client", None) is client:
                        controller.client = None

    async def _get_desk_controller(self) -> DeskController:
        _LOGGER.debug("Getting desk controller for %s", self.desk_info)
        if self._disconnecting:
            raise RuntimeError("Desk coordinator is disconnecting")
        if self.is_connected:
            return self._desk

        async with self._desk_lock:
            if self._disconnecting:
                raise RuntimeError("Desk coordinator is disconnecting")
            if self.is_connected:
                return self._desk

            stale_controller = self._desk
            self._desk = None
            if stale_controller is not None:
                await self._async_dispose_controller(stale_controller)

            validated_desk = self._validated_desk
            if validated_desk is None:
                bleak_client = await establish_connection(
                    BleakClientWithServiceCache,
                    self._desk_ble_device,
                    self._desk_ble_device.name or self.desk_name or "Unknown",
                    max_attempts=3,
                )

                bleak_client_factory: Callable[..., BLEClientProtocol] = (
                    _generate_existing_client_factory(bleak_client)
                )

                validated_desk = await DeskValidator(
                    bleak_client_factory
                ).validate_device(
                    self._discovered_desk, timeout=BLEAK_TIMEOUT_SECONDS
                )
                if validated_desk is None:
                    raise UpdateFailed(f"Could not validate desk {self.desk_info}")
                self._validated_desk = validated_desk
                self._desk_variant = validated_desk.desk_config.desk_variant

            if self._disconnecting:
                raise RuntimeError("Desk coordinator is disconnecting")

            bleak_client = await establish_connection(
                BleakClientWithServiceCache,
                self._desk_ble_device,
                self._desk_ble_device.name or self.desk_name or "Unknown",
                max_attempts=3,
            )
            controller = validated_desk.create_controller(
                bleak_client, fallback_unit=self._fallback_unit
            )
            controller.on(DeskEventType.HEIGHT, self._async_height_notify_callback)
            if self._disconnecting:
                await self._async_dispose_controller(controller)
                raise RuntimeError("Desk coordinator is disconnecting")
            try:
                await controller.start()
                if self._disconnecting:
                    raise RuntimeError("Desk coordinator is disconnecting")
            except BaseException:
                await self._async_dispose_controller(controller)
                raise

            self._desk = controller
            return controller

    @property
    def desk_name(self):
        return self._discovered_desk.name

    @property
    def desk_address(self):
        return self._discovered_desk.address

    @property
    def desk_info(self):
        return f"{self.desk_name} - {self.desk_address}"

    @property
    def is_connected(self):
        return self._desk is not None and self._desk.client is not None and self._desk.client.is_connected

    @property
    def supports_extended_presets(self):
        return self._desk_variant in _EXTENDED_PRESET_VARIANTS

    async def async_connect(self):
        await self._get_desk_controller()

    async def async_disconnect(self) -> None:
        """Disconnect an existing controller without establishing a new one."""
        self._disconnecting = True
        async with self._desk_lock:
            controller = self._desk
            self._desk = None
            if controller is not None:
                await self._async_dispose_controller(controller)

    async def async_read_desk_height(self):
        controller = await self._get_desk_controller()
        await controller.request_height_limits()
        self.height_mm = controller.height_mm
        return self.height_mm

    async def async_read_desk_units(self):
        controller = await self._get_desk_controller()
        await controller.request_units()
        retrieved_unit = controller.unit
        if retrieved_unit is None:
            retrieved_unit = self._fallback_unit
            if retrieved_unit is None:
                _LOGGER.warning(
                    "Desk %s did not report units and has no fallback configured",
                    self.desk_info,
                )
            else:
                _LOGGER.warning(
                    "Desk %s did not report units, using configured %s fallback",
                    self.desk_info,
                    retrieved_unit.value,
                )
        self.keypad_display_units = retrieved_unit
        return self.keypad_display_units

    async def async_preset_1(self):
        await self.async_wake()
        await (await self._get_desk_controller()).move_to_height_preset_1()

    async def async_preset_2(self):
        await self.async_wake()
        await (await self._get_desk_controller()).move_to_height_preset_2()

    async def async_preset_3(self):
        await self.async_wake()
        await (await self._get_desk_controller()).move_to_height_preset_3()

    async def async_preset_4(self):
        await self.async_wake()
        await (await self._get_desk_controller()).move_to_height_preset_4()

    async def async_wake(self):
        await (await self._get_desk_controller()).wake()

    def _async_height_notify_callback(self, height_mm: int):
        self.height_mm: int =  height_mm
        _LOGGER.debug("Height notify callback received height: %d mm", self.height_mm)
        self.async_set_updated_data(self._desk)
