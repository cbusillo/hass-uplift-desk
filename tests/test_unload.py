"""Regression tests for UPLIFT config-entry teardown."""

from __future__ import annotations

import asyncio
from enum import Enum
import sys
from types import ModuleType, SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch


def _install_module(name: str, *, package: bool = False, **attributes: object) -> None:
    module = ModuleType(name)
    if package:
        module.__path__ = []
    for attribute, value in attributes.items():
        setattr(module, attribute, value)
    sys.modules[name] = module


class _DataUpdateCoordinator:
    pass


class _FlowBase:
    def async_create_entry(self, *, title: str = "", data: dict[str, object]):
        return {"type": "create_entry", "title": title, "data": data}

    def async_show_form(self, *, step_id: str, data_schema=None, **kwargs: object):
        return {
            "type": "form",
            "step_id": step_id,
            "data_schema": data_schema,
            **kwargs,
        }


class _ConfigFlow(_FlowBase):
    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__()


class _DeskUnit(Enum):
    CENTIMETERS = "centimeters"
    INCHES = "inches"


class _Invalid(Exception):
    pass


class _Schema:
    def __init__(self, schema: object) -> None:
        self.schema = schema


_platform = SimpleNamespace(SENSOR="sensor", BUTTON="button")
_core_state = SimpleNamespace(running=object())
_desk_variant = SimpleNamespace(
    JIECANG_0x00FF=object(), JIECANG_0xFE60=object()
)
_desk_event_type = SimpleNamespace(HEIGHT=object())
_desk_unit = _DeskUnit

_install_module("uplift_ble", package=True)
_install_module("uplift_ble.desk_controller", DeskController=object)
_install_module("uplift_ble.desk_configs", DeskVariant=_desk_variant)
_install_module("uplift_ble.desk_validator", DeskValidator=object)
_install_module("uplift_ble.models", DiscoveredDesk=object)
_install_module(
    "uplift_ble.desk_enums",
    DeskEventType=_desk_event_type,
    DeskUnit=_desk_unit,
)
_install_module(
    "uplift_ble.ble_protos", BLEClientProtocol=object, BLEDeviceProtocol=object
)

_install_module("bleak", package=True, BleakClient=object)
_install_module("bleak.backends", package=True)
_install_module("bleak.backends.device", BLEDevice=object)
_install_module(
    "bleak_retry_connector",
    BleakClientWithServiceCache=object,
    establish_connection=AsyncMock(),
)

_install_module("homeassistant", package=True)
_install_module("homeassistant.components", package=True)
_install_module("homeassistant.helpers", package=True)
_install_module(
    "homeassistant.config_entries",
    ConfigEntry=object,
    ConfigFlow=_ConfigFlow,
    ConfigFlowResult=dict,
    OptionsFlow=_FlowBase,
)
_install_module("homeassistant.const", CONF_ADDRESS="address", Platform=_platform)
_install_module(
    "homeassistant.core",
    CoreState=_core_state,
    HomeAssistant=object,
    callback=lambda function: function,
)
_install_module("homeassistant.exceptions", ConfigEntryNotReady=Exception)
_install_module(
    "homeassistant.helpers.update_coordinator",
    CoordinatorEntity=object,
    DataUpdateCoordinator=_DataUpdateCoordinator,
    UpdateFailed=Exception,
)
_install_module(
    "homeassistant.helpers.dispatcher", async_dispatcher_send=MagicMock()
)
_install_module(
    "homeassistant.components.bluetooth",
    async_ble_device_from_address=MagicMock(),
    async_discovered_service_info=MagicMock(return_value=[]),
    BluetoothScanningMode=object,
    BluetoothServiceInfoBleak=object,
)
_install_module(
    "homeassistant.helpers.selector",
    SelectSelector=lambda config: config,
    SelectSelectorConfig=lambda **kwargs: kwargs,
    SelectSelectorMode=SimpleNamespace(DROPDOWN="dropdown"),
    selector=lambda config: config,
)
_install_module(
    "voluptuous",
    Invalid=_Invalid,
    Optional=lambda key, default=None: key,
    Required=lambda key, default=None: key,
    Schema=_Schema,
)

import custom_components.uplift_desk as integration_module
from custom_components.uplift_desk import (
    async_migrate_entry,
    async_reload_entry,
    async_unload_entry,
)
from custom_components.uplift_desk.config_flow import (
    UpliftDeskConfigFlow,
    UpliftDeskOptionsFlow,
)
from custom_components.uplift_desk.const import CONF_FALLBACK_UNIT, FALLBACK_UNIT_NONE
import custom_components.uplift_desk.coordinator as coordinator_module
from custom_components.uplift_desk.coordinator import (
    UpliftDeskBluetoothCoordinator,
    _parse_fallback_unit,
)


def _coordinator(controller: object | None = None) -> UpliftDeskBluetoothCoordinator:
    coordinator = UpliftDeskBluetoothCoordinator.__new__(
        UpliftDeskBluetoothCoordinator
    )
    coordinator._discovered_desk = SimpleNamespace(
        name="Test Desk", address="00:11:22:33:44:55"
    )
    coordinator._desk_ble_device = SimpleNamespace(
        name="Test Desk", address="00:11:22:33:44:55"
    )
    coordinator._desk = controller
    coordinator._desk_lock = asyncio.Lock()
    coordinator._disconnecting = False
    coordinator._validated_desk = None
    coordinator._desk_variant = None
    coordinator._fallback_unit = None
    coordinator._get_desk_controller = AsyncMock()
    return coordinator


def _controller(
    *, client: object | None, stop: AsyncMock | None = None
) -> SimpleNamespace:
    return SimpleNamespace(client=client, stop=stop or AsyncMock())


def _client(*, disconnect: AsyncMock | None = None) -> SimpleNamespace:
    return SimpleNamespace(is_connected=False, disconnect=disconnect or AsyncMock())


class UnloadEntryTests(IsolatedAsyncioTestCase):
    async def test_setup_registers_options_reload_listener(self) -> None:
        unsubscribe = object()
        coordinator = SimpleNamespace(
            desk_info="Test Desk",
            _desk=object(),
            async_connect=AsyncMock(),
            async_read_desk_units=AsyncMock(),
            async_read_desk_height=AsyncMock(),
            async_set_updated_data=MagicMock(),
        )
        add_update_listener = MagicMock(return_value=unsubscribe)
        async_on_unload = MagicMock()
        entry = SimpleNamespace(
            data={"address": "00:11:22:33:44:55"},
            title="Test Desk",
            add_update_listener=add_update_listener,
            async_on_unload=async_on_unload,
        )
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(
                async_forward_entry_setups=AsyncMock()
            )
        )

        with (
            patch.object(
                integration_module,
                "async_ble_device_from_address",
                MagicMock(return_value=object()),
            ),
            patch.object(
                integration_module,
                "UpliftDeskBluetoothCoordinator",
                MagicMock(return_value=coordinator),
            ),
        ):
            result = await integration_module.async_setup_entry(hass, entry)

        self.assertTrue(result)
        add_update_listener.assert_called_once_with(async_reload_entry)
        async_on_unload.assert_called_once_with(unsubscribe)

    async def test_migration_preserves_legacy_centimeters_behavior(self) -> None:
        update_entry = MagicMock()
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=update_entry)
        )
        entry = SimpleNamespace(
            version=1,
            minor_version=1,
            options={},
        )

        result = await async_migrate_entry(hass, entry)

        self.assertTrue(result)
        update_entry.assert_called_once_with(
            entry,
            options={CONF_FALLBACK_UNIT: _desk_unit.CENTIMETERS.value},
            minor_version=2,
        )

    async def test_migration_preserves_existing_fallback_option(self) -> None:
        update_entry = MagicMock()
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=update_entry)
        )
        entry = SimpleNamespace(
            version=1,
            minor_version=1,
            options={CONF_FALLBACK_UNIT: _desk_unit.INCHES.value},
        )

        await async_migrate_entry(hass, entry)

        update_entry.assert_called_once_with(
            entry,
            options={CONF_FALLBACK_UNIT: _desk_unit.INCHES.value},
            minor_version=2,
        )

    async def test_current_entry_does_not_migrate_again(self) -> None:
        update_entry = MagicMock()
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=update_entry)
        )
        entry = SimpleNamespace(version=1, minor_version=2, options={})

        result = await async_migrate_entry(hass, entry)

        self.assertTrue(result)
        update_entry.assert_not_called()

    async def test_reload_entry_reloads_config_entry(self) -> None:
        reload_entry = AsyncMock()
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_reload=reload_entry)
        )
        entry = SimpleNamespace(entry_id="test-entry")

        await async_reload_entry(hass, entry)

        reload_entry.assert_awaited_once_with("test-entry")

    async def test_unloads_platforms_before_disconnecting(self) -> None:
        events: list[str] = []

        async def unload_platforms(*args: object) -> bool:
            events.append("platforms")
            return True

        async def disconnect() -> None:
            events.append("disconnect")

        hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_unload_platforms=unload_platforms)
        )
        entry = SimpleNamespace(
            runtime_data=SimpleNamespace(async_disconnect=disconnect)
        )

        result = await async_unload_entry(hass, entry)

        self.assertTrue(result)
        self.assertEqual(events, ["platforms", "disconnect"])

    async def test_platform_failure_keeps_connection(self) -> None:
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(
                async_unload_platforms=AsyncMock(return_value=False)
            )
        )
        coordinator = SimpleNamespace(async_disconnect=AsyncMock())

        result = await async_unload_entry(
            hass, SimpleNamespace(runtime_data=coordinator)
        )

        self.assertFalse(result)
        coordinator.async_disconnect.assert_not_awaited()

    async def test_missing_runtime_data_does_not_fail_unload(self) -> None:
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(
                async_unload_platforms=AsyncMock(return_value=True)
            )
        )

        self.assertTrue(await async_unload_entry(hass, SimpleNamespace()))


class CoordinatorDisconnectTests(IsolatedAsyncioTestCase):
    async def test_no_controller_never_connects(self) -> None:
        coordinator = _coordinator()

        await coordinator.async_disconnect()

        coordinator._get_desk_controller.assert_not_awaited()

    async def test_disconnected_client_is_stopped_and_disconnected(self) -> None:
        client = _client()
        controller = _controller(client=client)
        coordinator = _coordinator(controller)

        await coordinator.async_disconnect()

        controller.stop.assert_awaited_once()
        client.disconnect.assert_awaited_once()
        coordinator._get_desk_controller.assert_not_awaited()
        self.assertIsNone(coordinator._desk)
        self.assertIsNone(controller.client)

    async def test_controller_is_detached_before_teardown(self) -> None:
        coordinator = _coordinator()

        async def stop() -> None:
            self.assertIsNone(coordinator._desk)

        controller = _controller(client=None, stop=AsyncMock(side_effect=stop))
        coordinator._desk = controller

        await coordinator.async_disconnect()

        controller.stop.assert_awaited_once()

    async def test_stop_failure_does_not_prevent_disconnect(self) -> None:
        client = _client()
        controller = _controller(
            client=client, stop=AsyncMock(side_effect=RuntimeError("stop failed"))
        )
        coordinator = _coordinator(controller)

        await coordinator.async_disconnect()

        client.disconnect.assert_awaited_once()
        self.assertIsNone(controller.client)

    async def test_stop_cancellation_still_attempts_disconnect(self) -> None:
        client = _client()
        controller = _controller(
            client=client, stop=AsyncMock(side_effect=asyncio.CancelledError)
        )

        with self.assertRaises(asyncio.CancelledError):
            await _coordinator(controller).async_disconnect()

        client.disconnect.assert_awaited_once()
        self.assertIsNone(controller.client)

    async def test_disconnect_failure_does_not_block_unload(self) -> None:
        disconnect = AsyncMock(side_effect=RuntimeError("disconnect failed"))
        controller = _controller(client=_client(disconnect=disconnect))

        await _coordinator(controller).async_disconnect()

        disconnect.assert_awaited_once()
        self.assertIsNone(controller.client)

    async def test_disconnect_cancellation_propagates_after_cleanup(self) -> None:
        disconnect = AsyncMock(side_effect=asyncio.CancelledError)
        controller = _controller(client=_client(disconnect=disconnect))

        with self.assertRaises(asyncio.CancelledError):
            await _coordinator(controller).async_disconnect()

        disconnect.assert_awaited_once()
        self.assertIsNone(controller.client)

    async def test_disconnect_is_idempotent(self) -> None:
        client = _client()
        controller = _controller(client=client)
        coordinator = _coordinator(controller)

        await coordinator.async_disconnect()
        await coordinator.async_disconnect()

        controller.stop.assert_awaited_once()
        client.disconnect.assert_awaited_once()

    async def test_normal_connect_path_is_preserved(self) -> None:
        controller = _controller(client=_client())
        controller.start = AsyncMock()
        coordinator = _coordinator()
        coordinator._get_desk_controller = AsyncMock(return_value=controller)

        await coordinator.async_connect()

        coordinator._get_desk_controller.assert_awaited_once()
        controller.start.assert_not_awaited()


class CoordinatorReconnectTests(IsolatedAsyncioTestCase):
    def _reconnect_coordinator(
        self, *, controller: object | None = None, validated_desk: object | None = None
    ) -> UpliftDeskBluetoothCoordinator:
        coordinator = _coordinator(controller)
        del coordinator._get_desk_controller
        coordinator._validated_desk = validated_desk
        return coordinator

    async def test_initial_connect_validates_and_starts_notifications(self) -> None:
        validation_client = object()
        new_client = SimpleNamespace(is_connected=True, disconnect=AsyncMock())
        new_controller = _controller(client=new_client)
        new_controller.start = AsyncMock()
        new_controller.on = MagicMock()
        desk_variant = object()
        validated_desk = SimpleNamespace(
            desk_config=SimpleNamespace(desk_variant=desk_variant),
            create_controller=MagicMock(return_value=new_controller),
        )
        validator = SimpleNamespace(
            validate_device=AsyncMock(return_value=validated_desk)
        )
        coordinator = self._reconnect_coordinator()

        with (
            patch.object(
                coordinator_module,
                "DeskValidator",
                MagicMock(return_value=validator),
            ),
            patch.object(
                coordinator_module,
                "establish_connection",
                AsyncMock(side_effect=[validation_client, new_client]),
            ) as establish,
        ):
            result = await coordinator._get_desk_controller()

        self.assertIs(result, new_controller)
        new_controller.start.assert_awaited_once()
        self.assertIs(coordinator._validated_desk, validated_desk)
        self.assertIs(coordinator._desk_variant, desk_variant)
        validator.validate_device.assert_awaited_once()
        self.assertEqual(establish.await_count, 2)
        validated_desk.create_controller.assert_called_once_with(
            new_client, fallback_unit=None
        )

    async def test_controller_receives_configured_fallback_unit(self) -> None:
        new_client = SimpleNamespace(is_connected=True, disconnect=AsyncMock())
        new_controller = _controller(client=new_client)
        new_controller.start = AsyncMock()
        new_controller.on = MagicMock()
        validated_desk = SimpleNamespace(
            desk_config=SimpleNamespace(desk_variant=object()),
            create_controller=MagicMock(return_value=new_controller),
        )
        coordinator = self._reconnect_coordinator(validated_desk=validated_desk)
        coordinator._fallback_unit = _desk_unit.INCHES

        with patch.object(
            coordinator_module,
            "establish_connection",
            AsyncMock(return_value=new_client),
        ):
            await coordinator._get_desk_controller()

        validated_desk.create_controller.assert_called_once_with(
            new_client, fallback_unit=_desk_unit.INCHES
        )

    async def test_reconnect_disposes_stale_controller_and_starts_notifications(
        self,
    ) -> None:
        stale_client = _client()
        stale_controller = _controller(client=stale_client)
        new_client = SimpleNamespace(is_connected=True, disconnect=AsyncMock())
        new_controller = _controller(client=new_client)
        new_controller.start = AsyncMock()
        new_controller.on = MagicMock()
        validated_desk = SimpleNamespace(
            desk_config=SimpleNamespace(desk_variant=object()),
            create_controller=MagicMock(return_value=new_controller),
        )
        coordinator = self._reconnect_coordinator(
            controller=stale_controller, validated_desk=validated_desk
        )

        with patch.object(
            coordinator_module,
            "establish_connection",
            AsyncMock(return_value=new_client),
        ) as establish:
            result = await coordinator._get_desk_controller()

        self.assertIs(result, new_controller)
        self.assertIs(coordinator._desk, new_controller)
        stale_controller.stop.assert_awaited_once()
        stale_client.disconnect.assert_awaited_once()
        new_controller.on.assert_called_once()
        new_controller.start.assert_awaited_once()
        establish.assert_awaited_once()

    async def test_concurrent_reconnect_calls_share_one_controller(self) -> None:
        connection_started = asyncio.Event()
        release_connection = asyncio.Event()
        new_client = SimpleNamespace(is_connected=True, disconnect=AsyncMock())
        new_controller = _controller(client=new_client)
        new_controller.start = AsyncMock()
        new_controller.on = MagicMock()
        validated_desk = SimpleNamespace(
            desk_config=SimpleNamespace(desk_variant=object()),
            create_controller=MagicMock(return_value=new_controller),
        )
        coordinator = self._reconnect_coordinator(validated_desk=validated_desk)

        async def establish(*args: object, **kwargs: object) -> object:
            connection_started.set()
            await release_connection.wait()
            return new_client

        with patch.object(
            coordinator_module,
            "establish_connection",
            AsyncMock(side_effect=establish),
        ) as establish_mock:
            first = asyncio.create_task(coordinator._get_desk_controller())
            await connection_started.wait()
            second = asyncio.create_task(coordinator._get_desk_controller())
            release_connection.set()
            first_result, second_result = await asyncio.gather(first, second)

        self.assertIs(first_result, new_controller)
        self.assertIs(second_result, new_controller)
        establish_mock.assert_awaited_once()
        validated_desk.create_controller.assert_called_once()
        new_controller.start.assert_awaited_once()

    async def test_failed_notification_start_cleans_up_new_controller(self) -> None:
        new_client = SimpleNamespace(is_connected=True, disconnect=AsyncMock())
        new_controller = _controller(client=new_client)
        new_controller.start = AsyncMock(side_effect=RuntimeError("start failed"))
        new_controller.on = MagicMock()
        validated_desk = SimpleNamespace(
            desk_config=SimpleNamespace(desk_variant=object()),
            create_controller=MagicMock(return_value=new_controller),
        )
        coordinator = self._reconnect_coordinator(validated_desk=validated_desk)

        with patch.object(
            coordinator_module,
            "establish_connection",
            AsyncMock(return_value=new_client),
        ):
            with self.assertRaisesRegex(RuntimeError, "start failed"):
                await coordinator._get_desk_controller()

        self.assertIsNone(coordinator._desk)
        new_controller.stop.assert_awaited_once()
        new_client.disconnect.assert_awaited_once()
        self.assertIsNone(new_controller.client)

    async def test_unload_suppresses_in_flight_reconnect(self) -> None:
        connection_started = asyncio.Event()
        release_connection = asyncio.Event()
        new_client = SimpleNamespace(is_connected=True, disconnect=AsyncMock())
        new_controller = _controller(client=new_client)
        new_controller.start = AsyncMock()
        new_controller.on = MagicMock()
        validated_desk = SimpleNamespace(
            desk_config=SimpleNamespace(desk_variant=object()),
            create_controller=MagicMock(return_value=new_controller),
        )
        coordinator = self._reconnect_coordinator(validated_desk=validated_desk)

        async def establish(*args: object, **kwargs: object) -> object:
            connection_started.set()
            await release_connection.wait()
            return new_client

        with patch.object(
            coordinator_module,
            "establish_connection",
            AsyncMock(side_effect=establish),
        ):
            reconnect = asyncio.create_task(coordinator._get_desk_controller())
            await connection_started.wait()
            unload = asyncio.create_task(coordinator.async_disconnect())
            await asyncio.sleep(0)
            self.assertTrue(coordinator._disconnecting)
            release_connection.set()
            with self.assertRaisesRegex(RuntimeError, "disconnecting"):
                await reconnect
            await unload

        self.assertIsNone(coordinator._desk)
        new_controller.start.assert_not_awaited()
        new_controller.stop.assert_awaited_once()
        new_client.disconnect.assert_awaited_once()

    async def test_unload_state_rejects_new_reconnect(self) -> None:
        coordinator = self._reconnect_coordinator()
        coordinator._disconnecting = True

        with patch.object(
            coordinator_module, "establish_connection", AsyncMock()
        ) as establish:
            with self.assertRaisesRegex(RuntimeError, "disconnecting"):
                await coordinator._get_desk_controller()

        establish.assert_not_awaited()


class CoordinatorFallbackUnitTests(IsolatedAsyncioTestCase):
    def test_parse_fallback_unit(self) -> None:
        self.assertIsNone(_parse_fallback_unit(None))
        self.assertIsNone(_parse_fallback_unit(FALLBACK_UNIT_NONE))
        self.assertIsNone(_parse_fallback_unit("invalid"))
        self.assertIs(
            _parse_fallback_unit(_desk_unit.CENTIMETERS.value),
            _desk_unit.CENTIMETERS,
        )
        self.assertIs(
            _parse_fallback_unit(_desk_unit.INCHES.value), _desk_unit.INCHES
        )

    async def test_missing_reported_unit_uses_configured_fallback(self) -> None:
        controller = SimpleNamespace(unit=None, request_units=AsyncMock())
        coordinator = _coordinator()
        coordinator._fallback_unit = _desk_unit.INCHES
        coordinator._get_desk_controller = AsyncMock(return_value=controller)

        result = await coordinator.async_read_desk_units()

        self.assertIs(result, _desk_unit.INCHES)
        self.assertFalse(hasattr(controller, "_unit"))

    async def test_missing_reported_unit_without_fallback_stays_unknown(self) -> None:
        controller = SimpleNamespace(unit=None, request_units=AsyncMock())
        coordinator = _coordinator()
        coordinator._get_desk_controller = AsyncMock(return_value=controller)

        result = await coordinator.async_read_desk_units()

        self.assertIsNone(result)
        self.assertFalse(hasattr(controller, "_unit"))


class OptionsFlowTests(IsolatedAsyncioTestCase):
    def test_config_flow_registers_options_flow(self) -> None:
        entry = SimpleNamespace(options={})

        flow = UpliftDeskConfigFlow.async_get_options_flow(entry)

        self.assertIsInstance(flow, UpliftDeskOptionsFlow)
        self.assertIs(flow._config_entry, entry)

    async def test_options_flow_shows_current_fallback(self) -> None:
        flow = UpliftDeskOptionsFlow(
            SimpleNamespace(options={CONF_FALLBACK_UNIT: _desk_unit.INCHES.value})
        )

        result = await flow.async_step_init()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "init")

    async def test_options_flow_saves_fallback(self) -> None:
        flow = UpliftDeskOptionsFlow(SimpleNamespace(options={}))

        result = await flow.async_step_init(
            {CONF_FALLBACK_UNIT: _desk_unit.CENTIMETERS.value}
        )

        self.assertEqual(
            result,
            {
                "type": "create_entry",
                "title": "",
                "data": {CONF_FALLBACK_UNIT: _desk_unit.CENTIMETERS.value},
            },
        )

    async def test_options_flow_saves_explicit_no_fallback(self) -> None:
        flow = UpliftDeskOptionsFlow(SimpleNamespace(options={}))

        result = await flow.async_step_init(
            {CONF_FALLBACK_UNIT: FALLBACK_UNIT_NONE}
        )

        self.assertEqual(
            result["data"], {CONF_FALLBACK_UNIT: FALLBACK_UNIT_NONE}
        )
