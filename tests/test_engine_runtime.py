from __future__ import annotations

import importlib.util
from copy import deepcopy
from enum import IntFlag
import sys
import types
from pathlib import Path
from datetime import datetime, timedelta, timezone
import unittest

ROOT = Path(__file__).parents[1]
COMP = ROOT / "custom_components" / "smart_shading"


def _install_ha_stubs() -> None:
    ha = types.ModuleType("homeassistant")
    components_mod = types.ModuleType("homeassistant.components")
    cover_mod = types.ModuleType("homeassistant.components.cover")
    http_mod = types.ModuleType("homeassistant.components.http")

    class CoverEntityFeature(IntFlag):
        SET_POSITION = 4
        SET_TILT_POSITION = 128

    cover_mod.CoverEntityFeature = CoverEntityFeature

    class StaticPathConfig:
        def __init__(self, *args, **kwargs):
            pass

    http_mod.StaticPathConfig = StaticPathConfig
    config_entries_mod = types.ModuleType("homeassistant.config_entries")

    class ConfigEntry:
        @classmethod
        def __class_getitem__(cls, item):
            return cls

    config_entries_mod.ConfigEntry = ConfigEntry
    const_mod = types.ModuleType("homeassistant.const")
    const_mod.STATE_ON = "on"
    const_mod.STATE_OFF = "off"
    core_mod = types.ModuleType("homeassistant.core")
    core_mod.HomeAssistant = object
    exceptions_mod = types.ModuleType("homeassistant.exceptions")

    class ServiceValidationError(ValueError):
        pass

    exceptions_mod.ServiceValidationError = ServiceValidationError

    helpers = types.ModuleType("homeassistant.helpers")
    dr_mod = types.ModuleType("homeassistant.helpers.device_registry")
    dr_mod.async_get = lambda hass: types.SimpleNamespace()
    dr_mod.async_entries_for_config_entry = lambda registry, entry_id: []
    er_mod = types.ModuleType("homeassistant.helpers.entity_registry")
    er_mod.async_get = lambda hass: types.SimpleNamespace(async_get_entity_id=lambda *args: None)
    event_mod = types.ModuleType("homeassistant.helpers.event")
    event_mod.async_call_later = lambda hass, delay, callback: (lambda: None)
    event_mod.async_track_state_change_event = lambda hass, entities, callback: (lambda: None)
    event_mod.async_track_time_interval = lambda hass, callback, interval: (lambda: None)
    storage_mod = types.ModuleType("homeassistant.helpers.storage")

    class Store:
        def __init__(self, *args, **kwargs):
            self.value = None

        async def async_load(self):
            return self.value

        async def async_save(self, value):
            self.value = value

        @classmethod
        def __class_getitem__(cls, item):
            return cls

    storage_mod.Store = Store

    util_mod = types.ModuleType("homeassistant.util")
    dt_mod = types.ModuleType("homeassistant.util.dt")
    dt_mod.now = lambda: datetime.now(timezone.utc)
    dt_mod.parse_datetime = lambda value: datetime.fromisoformat(value) if value else None
    dt_mod.as_local = lambda value: value
    util_mod.dt = dt_mod

    sys.modules.update(
        {
            "homeassistant": ha,
            "homeassistant.components": components_mod,
            "homeassistant.components.cover": cover_mod,
            "homeassistant.components.http": http_mod,
            "homeassistant.config_entries": config_entries_mod,
            "homeassistant.const": const_mod,
            "homeassistant.core": core_mod,
            "homeassistant.exceptions": exceptions_mod,
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.device_registry": dr_mod,
            "homeassistant.helpers.entity_registry": er_mod,
            "homeassistant.helpers.event": event_mod,
            "homeassistant.helpers.storage": storage_mod,
            "homeassistant.util": util_mod,
            "homeassistant.util.dt": dt_mod,
        }
    )


def _load(fullname: str, path: Path):
    spec = importlib.util.spec_from_file_location(fullname, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[fullname] = module
    spec.loader.exec_module(module)
    return module


_install_ha_stubs()
custom_pkg = types.ModuleType("custom_components")
custom_pkg.__path__ = [str(ROOT / "custom_components")]
smart_pkg = types.ModuleType("custom_components.smart_shading")
smart_pkg.__path__ = [str(COMP)]
sys.modules["custom_components"] = custom_pkg
sys.modules["custom_components.smart_shading"] = smart_pkg
for name in ("const", "logic", "models", "storage", "decision", "execution"):
    _load(f"custom_components.smart_shading.{name}", COMP / f"{name}.py")
engine_mod = _load("custom_components.smart_shading.engine", COMP / "engine.py")
# Entry migration needs the integration's controller only for type wiring and
# setup hooks.  Keep this isolated from the engine-runtime regression fixture:
# the production controller is loaded by the dedicated manual-detection tests.
controller_stub = types.ModuleType("custom_components.smart_shading.controller")
controller_stub.SmartShadingEngine = engine_mod.SmartShadingEngine
sys.modules[controller_stub.__name__] = controller_stub
migration_mod = _load("custom_components.smart_shading", COMP / "__init__.py")
models_mod = sys.modules["custom_components.smart_shading.models"]


class FakeState:
    def __init__(
        self,
        state: str,
        *,
        last_updated: datetime | None = None,
        last_changed: datetime | None = None,
        **attrs,
    ):
        self.state = state
        self.attributes = attrs
        self.last_updated = last_updated
        self.last_changed = last_changed or last_updated


class FakeStates:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, entity_id):
        return self.values.get(entity_id)

    def is_state(self, entity_id, state):
        current = self.get(entity_id)
        return current is not None and current.state == state


class FakeServices:
    def __init__(self, states):
        self.calls = []
        self.states = states
        self.fail_notification_creates = 0

    async def async_call(self, domain, service, data, blocking=False):
        self.calls.append((domain, service, dict(data), blocking))
        if (
            domain == "persistent_notification"
            and service == "create"
            and self.fail_notification_creates > 0
        ):
            self.fail_notification_creates -= 1
            raise RuntimeError("simulated notification create failure")
        entity_id = data.get("entity_id")
        if domain in {"switch", "input_boolean"} and entity_id:
            if service == "turn_on":
                self.states.values[entity_id] = FakeState("on")
            elif service == "turn_off":
                self.states.values[entity_id] = FakeState("off")


class FakeHass:
    def __init__(self, values):
        self.states = FakeStates(values)
        self.services = FakeServices(self.states)
        self.config = types.SimpleNamespace(language="de", path=lambda value: f"/tmp/{value}")
        self.http = types.SimpleNamespace()

    async def async_add_executor_job(self, callback, *args):
        return callback(*args)


class FakeEntry:
    def __init__(self, data):
        self.entry_id = "entry"
        self.data = data
        self.options = {}
        self.title = "Test"


class FakeMigrationEntry:
    """Small ConfigEntry stand-in that exposes the schema-15 snapshots."""

    def __init__(self, data, options, *, version=15):
        self.data = data
        self.options = options
        self.version = version


class FakeMigrationConfigEntries:
    """Record Home Assistant's atomic migration update for assertions."""

    def __init__(self):
        self.updates = []

    def async_update_entry(self, entry, **values):
        self.updates.append(dict(values))
        for key, value in values.items():
            setattr(entry, key, value)


class FakeMigrationHass:
    def __init__(self):
        self.config_entries = FakeMigrationConfigEntries()


class FakeEvent:
    def __init__(self, entity_id, old_state, new_state):
        self.data = {"entity_id": entity_id, "old_state": old_state, "new_state": new_state}


class FakeEntityRegistry:
    def __init__(self, entries=None):
        self.entries = entries or {}

    def async_get_entity_id(self, platform, domain, unique_id):
        return self.entries.get((platform, domain, unique_id))


def base_config():
    return {
        "house_name": "Test",
        "sun_entity": "sun.sun",
        "advanced_mode": True,
        "external_movement_detection": True,
        "evaluation_interval": 1200,
        "diagnostic_level": "full",
        "rooms": [
            {
                "id": "room",
                "name": "Room",
                "enabled": True,
                "default_pause_mode": "next_sunrise",
                "pause_sun_offset_minutes": 0,
                "safety_blockers": [],
                "sectors": [
                    {
                        "id": "south",
                        "name": "South",
                        "short": "S",
                        "sun_preset": "medium",
                        "lux_sensor": "sensor.lux",
                        "azimuth_start": 120,
                        "azimuth_end": 240,
                        "elevation_min": 10,
                        "layers": [
                            {
                                "id": "layer",
                                "name": "Blinds",
                                "profile": "venetian",
                                "covers": [
                                    {
                                        "id": "cover_one",
                                        "entity": "cover.one",
                                        "name": "Cover one",
                                        "short": "C1",
                                        "lock": "switch.cover_lock",
                                        "window": "",
                                        "window_safe_state": "on",
                                        "window_policy": "block_closing",
                                        "window_returns_to_automation": True,
                                        "max_open_position": 100,
                                        "invert_position": False,
                                        "invert_tilt": False,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }


class EntryMigrationRuntimeTests(unittest.IsolatedAsyncioTestCase):
    """Exercise the real entry migration with the lightweight HA fixture."""

    @staticmethod
    def _schema_15_payload(*, advanced: bool) -> dict:
        mode = "advanced" if advanced else "easy"
        return {
            "house_name": "v4.6.2 fixture",
            "sun_entity": "sun.sun",
            "advanced_mode": advanced,
            "evaluation_interval": 1200,
            "rooms": [
                {
                    "id": f"{mode}-room",
                    "name": f"{mode.title()} room",
                    "sectors": [
                        {
                            "id": f"{mode}-sector",
                            "name": f"{mode.title()} sector",
                            "sun_source": "geometry",
                            "layers": [
                                {
                                    "id": f"{mode}-layer",
                                    "name": f"{mode.title()} layer",
                                    "profile": "venetian",
                                    "covers": [
                                        {
                                            "id": f"{mode}-cover",
                                            "entity": f"cover.{mode}",
                                            "name": f"{mode.title()} cover",
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }

    def _assert_hierarchy(self, config: dict, *, mode: str) -> None:
        room = config["rooms"][0]
        sector = room["sectors"][0]
        layer = sector["layers"][0]
        cover = layer["covers"][0]
        self.assertEqual(room["id"], f"{mode}-room")
        self.assertEqual(sector["id"], f"{mode}-sector")
        self.assertEqual(layer["id"], f"{mode}-layer")
        self.assertEqual(cover["id"], f"{mode}-cover")
        self.assertEqual(cover["entity"], f"cover.{mode}")

    async def test_schema_16_re_normalizes_v4_6_2_advanced_and_easy_entries(self):
        """Schema 15 stable snapshots gain or lose the Issue #79 surface."""
        advanced_data = self._schema_15_payload(advanced=True)
        advanced_room_seed = advanced_data["rooms"][0]
        advanced_room_seed.update(
            {
                "stagger_scope": "crafted-invalid-scope",
                "safety_bypasses_stagger": "not-a-boolean",
            }
        )
        advanced_layer_seed = advanced_room_seed["sectors"][0]["layers"][0]
        advanced_layer_seed["opening_order"] = "crafted-invalid-order"
        advanced_layer_seed["covers"][0]["allow_automatic_reverse"] = "yes"
        advanced_options = deepcopy(advanced_data)
        advanced_options["migration_option_marker"] = "advanced-options"
        advanced_options["rooms"][0]["name"] = "Advanced option room"
        advanced_entry = FakeMigrationEntry(advanced_data, advanced_options)
        advanced_hass = FakeMigrationHass()

        self.assertTrue(
            await migration_mod.async_migrate_entry(advanced_hass, advanced_entry)
        )
        self.assertEqual(advanced_entry.version, 16)
        self.assertEqual(len(advanced_hass.config_entries.updates), 1)
        self._assert_hierarchy(advanced_entry.data, mode="advanced")
        self._assert_hierarchy(advanced_entry.options, mode="advanced")
        self.assertEqual(
            advanced_entry.options["migration_option_marker"], "advanced-options"
        )
        self.assertEqual(
            advanced_entry.options["rooms"][0]["name"], "Advanced option room"
        )
        self.assertNotIn("advanced_mode", advanced_entry.options)
        advanced_room = advanced_entry.data["rooms"][0]
        for key, expected in migration_mod.ADVANCED_EXECUTION_ROOM_DEFAULTS.items():
            with self.subTest(mode="advanced", field=key):
                self.assertEqual(advanced_room[key], expected)
        advanced_layer = advanced_room["sectors"][0]["layers"][0]
        self.assertEqual(
            advanced_layer["movement_seconds"], advanced_room["movement_seconds"]
        )
        self.assertEqual(
            advanced_layer["settling_seconds"], advanced_room["settling_seconds"]
        )
        self.assertEqual(
            advanced_layer["opening_order"],
            migration_mod.DEFAULT_OPENING_ORDER,
        )
        advanced_cover = advanced_layer["covers"][0]
        self.assertEqual(advanced_cover["feedback_quality"], "trusted")
        self.assertFalse(advanced_cover["verify_target"])
        self.assertFalse(advanced_cover["allow_automatic_reverse"])

        easy_data = self._schema_15_payload(advanced=False)
        easy_room = easy_data["rooms"][0]
        easy_room.update(
            {
                "command_stagger_seconds": 17,
                "stagger_scope": "house",
                "safety_bypasses_stagger": False,
                "target_verification_enabled": True,
                "verification_retries": 9,
                "movement_seconds": 41,
                "settling_seconds": 12,
                "source_stale_seconds": 1800,
            }
        )
        easy_sector = easy_room["sectors"][0]
        easy_sector["protected_zones"] = [
            {
                "id": "beta-zone",
                "name": "Crafted Advanced value",
                "group_ids": ["easy-layer"],
            }
        ]
        easy_layer = easy_sector["layers"][0]
        easy_layer.update(
            {
                "movement_seconds": 41,
                "settling_seconds": 12,
                "opening_order": "tilt_then_height",
            }
        )
        easy_layer["covers"][0].update(
            {
                "feedback_quality": "none",
                "verify_target": True,
                "allow_automatic_reverse": True,
            }
        )
        easy_options = deepcopy(easy_data)
        # A stale full options snapshot must not be able to turn an Easy entry
        # into Advanced mode during migration.
        easy_options["advanced_mode"] = True
        easy_options["migration_option_marker"] = "easy-options"
        easy_options["rooms"][0]["name"] = "Easy option room"
        easy_entry = FakeMigrationEntry(easy_data, easy_options)
        easy_hass = FakeMigrationHass()

        self.assertTrue(
            await migration_mod.async_migrate_entry(easy_hass, easy_entry)
        )
        self.assertEqual(easy_entry.version, 16)
        self.assertEqual(len(easy_hass.config_entries.updates), 1)
        self._assert_hierarchy(easy_entry.data, mode="easy")
        self._assert_hierarchy(easy_entry.options, mode="easy")
        self.assertEqual(
            easy_entry.options["migration_option_marker"], "easy-options"
        )
        self.assertEqual(easy_entry.options["rooms"][0]["name"], "Easy option room")
        self.assertNotIn("advanced_mode", easy_entry.options)
        for snapshot_name, snapshot in (
            ("data", easy_entry.data),
            ("options", easy_entry.options),
        ):
            room = snapshot["rooms"][0]
            sector = room["sectors"][0]
            layer = sector["layers"][0]
            cover = layer["covers"][0]
            for key in migration_mod.ADVANCED_EXECUTION_ROOM_DEFAULTS:
                with self.subTest(
                    mode="easy", snapshot=snapshot_name, field=key
                ):
                    self.assertNotIn(key, room)
            self.assertNotIn("protected_zones", sector)
            self.assertNotIn("movement_seconds", layer)
            self.assertNotIn("settling_seconds", layer)
            self.assertNotIn("opening_order", layer)
            self.assertNotIn("feedback_quality", cover)
            self.assertNotIn("verify_target", cover)
            self.assertNotIn("allow_automatic_reverse", cover)

    async def test_preview_service_routes_only_to_a_loaded_matching_room(self):
        """The Card-facing preview service is narrow, async, and non-actuating."""
        received: list[tuple[str, object]] = []

        class PreviewEngine:
            rooms = {"room": object()}

            async def async_preview_room_day(self, room_id, *, date=None):
                received.append((room_id, date))

        engine = PreviewEngine()
        hass = types.SimpleNamespace(
            data={migration_mod._ENGINE_REGISTRY: {"entry": engine}}
        )
        call = types.SimpleNamespace(
            data={"entry_id": "entry", "room_id": "room", "date": "2031-06-21"}
        )
        await migration_mod._async_preview_day_service(hass, call)
        self.assertEqual(received, [("room", "2031-06-21")])
        with self.assertRaises(migration_mod.ServiceValidationError):
            await migration_mod._async_preview_day_service(
                hass,
                types.SimpleNamespace(
                    data={"entry_id": "entry", "room_id": "missing"}
                ),
            )


class EngineRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        values = {
            "sun.sun": FakeState(
                "above_horizon",
                azimuth=180,
                elevation=35,
                next_rising=tomorrow.isoformat(),
                next_setting=tomorrow.isoformat(),
            ),
            "sensor.lux": FakeState("26398.72", unit_of_measurement="lx"),
            "cover.one": FakeState("open", current_position=100, current_tilt_position=100),
            "switch.cover_lock": FakeState("off"),
        }
        self.hass = FakeHass(values)
        self.engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(base_config()))
        await self.engine.async_initialize()

    async def _sync_card_notifications(self, registry):
        original_async_get = engine_mod.er.async_get
        engine_mod.er.async_get = lambda hass: registry
        try:
            return await self.engine.async_sync_card_notifications()
        finally:
            engine_mod.er.async_get = original_async_get

    def _notification_calls(self, service):
        return [
            call
            for call in self.hass.services.calls
            if call[0:2] == ("persistent_notification", service)
        ]

    async def test_optional_maximum_opening_corrects_only_real_violations(self):
        layer = self.engine.config["rooms"][0]["sectors"][0]["layers"][0]
        cover = layer["covers"][0]
        layer["position_tolerance"] = 5
        cover["enforce_max_open_position"] = True
        cover["max_open_position"] = 90
        violating = FakeState(
            "open", current_position=96, supported_features=4
        )

        self.assertTrue(
            await self.engine._async_enforce_cover_maximum(
                "cover.one", violating
            )
        )
        correction_calls = [
            call
            for call in self.hass.services.calls
            if call[0:2] == ("cover", "set_cover_position")
        ]
        self.assertEqual(len(correction_calls), 1)
        self.assertEqual(correction_calls[0][2]["position"], 90)

        # The 90-second internal cooldown acknowledges the still-violating
        # feedback without sending the identical command again.
        self.assertTrue(
            await self.engine._async_enforce_cover_maximum(
                "cover.one", violating
            )
        )
        self.assertEqual(
            len(
                [
                    call
                    for call in self.hass.services.calls
                    if call[0:2] == ("cover", "set_cover_position")
                ]
            ),
            1,
        )
        self.assertFalse(
            await self.engine._async_enforce_cover_maximum(
                "cover.one",
                FakeState("open", current_position=95, supported_features=4),
            )
        )

    async def test_safety_has_priority_over_optional_maximum_opening(self):
        room = self.engine.config["rooms"][0]
        cover = room["sectors"][0]["layers"][0]["covers"][0]
        cover["enforce_max_open_position"] = True
        cover["max_open_position"] = 90
        room["safety_blockers"] = ["binary_sensor.wind"]
        self.hass.states.values["binary_sensor.wind"] = FakeState("on")

        self.assertFalse(
            await self.engine._async_enforce_cover_maximum(
                "cover.one",
                FakeState("open", current_position=100, supported_features=4),
            )
        )
        self.assertFalse(
            any(
                call[0:2] == ("cover", "set_cover_position")
                for call in self.hass.services.calls
            )
        )

    async def test_card_notification_is_created_once_for_a_new_room(self):
        registry = FakeEntityRegistry({
            ("sensor", "smart_shading", "entry_room_status"): "sensor.room_status"
        })

        self.assertTrue(await self._sync_card_notifications(registry))

        creates = self._notification_calls("create")
        self.assertEqual(len(creates), 1)
        self.assertEqual(
            creates[0][2]["notification_id"], "smart_shading_card_entry_room"
        )
        self.assertIn("entity: sensor.room_status", creates[0][2]["message"])
        self.assertEqual(
            self.engine.store.card_notification_ids(),
            ["smart_shading_card_entry_room"],
        )

        # Reloading or editing a room with the same stable room id must not
        # recreate the onboarding notification.
        self.engine.entry.data["rooms"][0]["name"] = "Renamed room"
        self.engine.reload_config()
        self.assertTrue(await self._sync_card_notifications(registry))
        self.assertEqual(len(self._notification_calls("create")), 1)

    async def test_card_notification_adds_only_the_second_new_room(self):
        registry = FakeEntityRegistry({
            ("sensor", "smart_shading", "entry_room_status"): "sensor.room_status",
            ("sensor", "smart_shading", "entry_room_two_status"): "sensor.room_two_status",
        })
        self.assertTrue(await self._sync_card_notifications(registry))
        self.hass.services.calls.clear()

        second_room = deepcopy(self.engine.entry.data["rooms"][0])
        second_room.update({"id": "room_two", "name": "Room two"})
        self.engine.entry.data["rooms"].append(second_room)
        self.engine.reload_config()

        self.assertTrue(await self._sync_card_notifications(registry))

        creates = self._notification_calls("create")
        self.assertEqual(len(creates), 1)
        self.assertEqual(
            creates[0][2]["notification_id"], "smart_shading_card_entry_room_two"
        )
        self.assertEqual(
            self.engine.store.card_notification_ids(),
            [
                "smart_shading_card_entry_room",
                "smart_shading_card_entry_room_two",
            ],
        )

    async def test_card_notification_missing_entity_remains_retryable(self):
        registry = FakeEntityRegistry()

        self.assertFalse(await self._sync_card_notifications(registry))
        self.assertEqual(self._notification_calls("create"), [])
        self.assertEqual(self.engine.store.card_notification_ids(), [])

        registry.entries[
            ("sensor", "smart_shading", "entry_room_status")
        ] = "sensor.room_status"
        self.assertTrue(await self._sync_card_notifications(registry))
        self.assertEqual(len(self._notification_calls("create")), 1)
        self.assertEqual(
            self.engine.store.card_notification_ids(),
            ["smart_shading_card_entry_room"],
        )

    async def test_card_notification_create_failure_remains_retryable(self):
        registry = FakeEntityRegistry({
            ("sensor", "smart_shading", "entry_room_status"): "sensor.room_status"
        })
        self.hass.services.fail_notification_creates = 1

        with self.assertLogs(engine_mod._LOGGER, level="ERROR"):
            self.assertFalse(await self._sync_card_notifications(registry))
        self.assertEqual(self.engine.store.card_notification_ids(), [])

        self.assertTrue(await self._sync_card_notifications(registry))
        self.assertEqual(len(self._notification_calls("create")), 2)
        self.assertEqual(
            self.engine.store.card_notification_ids(),
            ["smart_shading_card_entry_room"],
        )

    async def test_card_notification_for_deleted_room_is_dismissed(self):
        registry = FakeEntityRegistry({
            ("sensor", "smart_shading", "entry_room_status"): "sensor.room_status"
        })
        self.assertTrue(await self._sync_card_notifications(registry))
        self.hass.services.calls.clear()

        self.engine.entry.data["rooms"] = []
        self.engine.reload_config()

        self.assertTrue(await self._sync_card_notifications(registry))
        dismisses = self._notification_calls("dismiss")
        self.assertEqual(len(dismisses), 1)
        self.assertEqual(
            dismisses[0][2],
            {"notification_id": "smart_shading_card_entry_room"},
        )
        self.assertEqual(self.engine.store.card_notification_ids(), [])

    async def test_easy_mode_uses_only_sun_geometry_and_manual_override(self):
        config = base_config()
        config["advanced_mode"] = False
        room = config["rooms"][0]
        room["sectors"][0]["lux_sensor"] = ""
        room.update({
            "indoor_temperature": "sensor.indoor",
            "safety_blockers": ["binary_sensor.wind"],
            "night_enabled": True,
            "night_source": "entity",
            "night_entity": "schedule.night",
            "active_months": [],
            "external_movement_detection": True,
        })
        self.hass.states.values.update({
            "sensor.indoor": FakeState("40"),
            "binary_sensor.wind": FakeState("on"),
            "schedule.night": FakeState("on"),
            "sensor.lux": FakeState("0", unit_of_measurement="lx"),
        })
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()
        engine.rooms["room"].pause_mode = "manual"

        await engine.async_evaluate_all("easy_contract")

        self.assertEqual(engine.rooms["room"].mode, "solar")
        self.assertEqual(engine.rooms["room"].pause_mode, "auto")
        self.assertFalse(engine.rooms["room"].night_active)
        self.assertFalse(engine.rooms["room"].heat_active)
        self.assertEqual(engine.referenced_entities(), {"sun.sun"})

        await engine.async_set_room_enabled("room", False)
        self.assertEqual(engine.rooms["room"].mode, "disabled")

    async def test_runtime_cannot_change_the_setup_variant_from_options(self):
        for configured, crafted in ((False, True), (True, False)):
            with self.subTest(configured=configured, crafted=crafted):
                config = base_config()
                config["advanced_mode"] = configured
                entry = FakeEntry(config)
                entry.options = {
                    "advanced_mode": crafted,
                    "evaluation_interval": 600,
                }

                engine = engine_mod.SmartShadingEngine(self.hass, entry)

                self.assertIs(engine.advanced_mode, configured)
                self.assertEqual(engine.config["evaluation_interval"], 600)

    async def test_advanced_sector_metadata_tracks_real_sun_not_room_wide_modes(self):
        config = base_config()
        room = config["rooms"][0]
        sector = room["sectors"][0]
        sector["lux_sensor"] = ""
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()
        noon = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
        await engine._evaluate_room(room, noon)

        runtime = engine.sun_runtime["south"]
        self.assertTrue(runtime.geometry_active)
        self.assertTrue(runtime.effective_active)
        self.assertTrue(runtime.shading_active)
        self.assertEqual(runtime.confirmation_source, "geometry")
        self.assertIsNone(runtime.confirmation_state)

        room["safety_blockers"] = ["binary_sensor.wind"]
        self.hass.states.values["binary_sensor.wind"] = FakeState("on")
        await engine._evaluate_room(room, noon)

        self.assertEqual(engine.rooms["room"].mode, "safety")
        self.assertEqual(runtime.status, "safety")
        self.assertFalse(runtime.effective_active)

    async def test_advanced_lux_source_is_exposed_to_the_card(self):
        config = base_config()
        sector = config["rooms"][0]["sectors"][0]
        sector.update({
            "sun_preset": "custom",
            "sun_on_lux": 10000,
            "sun_off_lux": 5000,
            "sun_on_delay": 0,
            "sun_off_delay": 0,
        })
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()
        noon = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
        await engine._update_sun_presence(sector, noon)
        await engine._evaluate_room(config["rooms"][0], noon)

        runtime = engine.sun_runtime["south"]
        self.assertEqual(runtime.confirmation_source, "lux")
        self.assertEqual(runtime.confirmation_entity, "sensor.lux")
        self.assertTrue(runtime.confirmation_state)
        self.assertTrue(runtime.effective_active)

    async def test_advanced_external_confirmation_controls_the_sector(self):
        config = base_config()
        sector = config["rooms"][0]["sectors"][0]
        sector.update({
            "sun_source": "external",
            "sun_presence_entity": "binary_sensor.facade_sun",
            "lux_sensor": "",
        })
        self.hass.states.values["binary_sensor.facade_sun"] = FakeState("off")
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()

        await engine.async_evaluate_all("advanced_external_off")
        runtime = engine.sun_runtime["south"]
        self.assertEqual(runtime.confirmation_source, "binary")
        self.assertEqual(
            runtime.confirmation_entity, "binary_sensor.facade_sun"
        )
        self.assertFalse(runtime.confirmation_state)
        self.assertFalse(runtime.effective_active)
        self.assertEqual(engine.rooms["room"].mode, "open")
        self.assertIn(
            "binary_sensor.facade_sun", engine.referenced_entities()
        )

        self.hass.states.values["binary_sensor.facade_sun"] = FakeState("on")
        await engine.async_evaluate_all("advanced_external_on")
        self.assertTrue(runtime.confirmation_state)
        self.assertTrue(runtime.effective_active)
        self.assertEqual(engine.rooms["room"].mode, "solar")

    async def test_advanced_external_never_falls_back_when_unavailable(self):
        config = base_config()
        sector = config["rooms"][0]["sectors"][0]
        sector.update({
            "sun_source": "external",
            "sun_presence_entity": "binary_sensor.facade_sun",
            "sun_preset": "custom",
            "sun_on_lux": 10000,
            "sun_off_lux": 5000,
            "sun_on_delay": 0,
            "sun_off_delay": 0,
        })
        self.hass.states.values["binary_sensor.facade_sun"] = FakeState(
            "unavailable"
        )
        self.hass.states.values["sensor.lux"] = FakeState("50000")
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()

        self.hass.services.calls.clear()
        await engine.async_evaluate_all("advanced_external_unavailable")
        runtime = engine.sun_runtime["south"]
        self.assertEqual(runtime.confirmation_source, "binary")
        self.assertEqual(runtime.confirmation_entity, "binary_sensor.facade_sun")
        self.assertIsNone(runtime.confirmation_state)
        self.assertFalse(runtime.effective_active)
        self.assertEqual(runtime.status, "source_unavailable")
        self.assertEqual(engine.rooms["room"].mode, "idle")
        self.assertFalse(
            any(call[0] == "cover" for call in self.hass.services.calls)
        )

    async def test_easy_selected_external_confirmation_ignores_lux(self):
        config = base_config()
        config["advanced_mode"] = False
        sector = config["rooms"][0]["sectors"][0]
        sector.update({
            "sun_source": "external",
            "sun_presence_entity": "binary_sensor.facade_sun",
            "sun_preset": "custom",
            "sun_on_lux": 10000,
            "sun_off_lux": 5000,
            "sun_on_delay": 0,
            "sun_off_delay": 0,
        })
        self.hass.states.values["binary_sensor.facade_sun"] = FakeState("off")
        self.hass.states.values["sensor.lux"] = FakeState("50000")
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()

        await engine.async_evaluate_all("easy_binary_off")
        runtime = engine.sun_runtime["south"]
        self.assertTrue(runtime.is_on)
        self.assertEqual(runtime.confirmation_source, "binary")
        self.assertFalse(runtime.confirmation_state)
        self.assertFalse(runtime.effective_active)
        self.assertEqual(engine.rooms["room"].mode, "open")

        self.hass.states.values["binary_sensor.facade_sun"] = FakeState("on")
        await engine.async_evaluate_all("easy_binary_on")
        self.assertTrue(runtime.confirmation_state)
        self.assertTrue(runtime.effective_active)
        self.assertEqual(engine.rooms["room"].mode, "solar")

    async def test_easy_unavailable_external_never_falls_back_to_lux(self):
        config = base_config()
        config["advanced_mode"] = False
        sector = config["rooms"][0]["sectors"][0]
        sector.update({
            "sun_source": "external",
            "sun_presence_entity": "binary_sensor.facade_sun",
            "sun_preset": "custom",
            "sun_on_lux": 10000,
            "sun_off_lux": 5000,
            "sun_on_delay": 0,
            "sun_off_delay": 0,
        })
        self.hass.states.values["binary_sensor.facade_sun"] = FakeState(
            "unavailable"
        )
        self.hass.states.values["sensor.lux"] = FakeState("50000")
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()

        self.hass.services.calls.clear()
        await engine.async_evaluate_all("easy_external_unavailable")
        runtime = engine.sun_runtime["south"]
        self.assertEqual(runtime.confirmation_source, "binary")
        self.assertIsNone(runtime.confirmation_state)
        self.assertFalse(runtime.effective_active)
        self.assertEqual(runtime.status, "source_unavailable")
        self.assertEqual(engine.rooms["room"].mode, "idle")
        self.assertFalse(
            any(call[0] == "cover" for call in self.hass.services.calls)
        )

    async def test_easy_geometry_source_ignores_house_weather(self):
        config = base_config()
        config.update({"advanced_mode": False, "weather_entity": "weather.home"})
        config["rooms"][0]["sectors"][0].update({
            "sun_source": "geometry",
            "lux_sensor": "",
        })
        self.hass.states.values["weather.home"] = FakeState("rainy")
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()

        await engine.async_evaluate_all("easy_geometry_ignores_weather")
        runtime = engine.sun_runtime["south"]
        self.assertEqual(runtime.confirmation_source, "geometry")
        self.assertIsNone(runtime.confirmation_state)
        self.assertEqual(engine.rooms["room"].mode, "solar")

    async def test_easy_outdoor_temperature_condition_uses_only_selected_sensor(self):
        config = base_config()
        config.update({"advanced_mode": False, "weather_entity": "weather.home"})
        room = config["rooms"][0]
        room.update({
            "outdoor_temperature": "sensor.outdoor",
            "outdoor_minimum": 18.0,
        })
        room["sectors"][0]["lux_sensor"] = ""
        self.hass.states.values["sensor.outdoor"] = FakeState("12")
        self.hass.states.values["weather.home"] = FakeState(
            "partlycloudy", temperature=24
        )
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()

        await engine.async_evaluate_all("easy_temperature_low")
        runtime = engine.rooms["room"]
        self.assertEqual(runtime.mode, "open")
        self.assertFalse(runtime.outdoor_temperature_passed)
        self.assertEqual(runtime.outdoor_temperature_source, "sensor.outdoor")

        self.hass.states.values["sensor.outdoor"] = FakeState("22")
        await engine.async_evaluate_all("easy_temperature_high")
        self.assertEqual(runtime.mode, "solar")
        self.assertTrue(runtime.outdoor_temperature_passed)

        self.hass.states.values["sensor.outdoor"] = FakeState("unavailable")
        self.hass.states.values["weather.home"] = FakeState(
            "partlycloudy", temperature=10
        )
        await engine.async_evaluate_all("easy_temperature_unavailable")
        self.assertEqual(runtime.mode, "open")
        self.assertEqual(runtime.outdoor_temperature_source, "sensor.outdoor")
        self.assertIsNone(runtime.outdoor_temperature_value)
        self.assertFalse(runtime.outdoor_temperature_passed)

    async def test_easy_outdoor_temperature_condition_normalizes_fahrenheit(self):
        config = base_config()
        config["advanced_mode"] = False
        room = config["rooms"][0]
        room.update({
            "outdoor_temperature": "sensor.outdoor",
            "outdoor_minimum": 18.0,
        })
        room["sectors"][0]["lux_sensor"] = ""
        self.hass.states.values["sensor.outdoor"] = FakeState(
            "64", unit_of_measurement="°F"
        )
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()

        await engine.async_evaluate_all("easy_temperature_fahrenheit")

        runtime = engine.rooms["room"]
        self.assertEqual(runtime.mode, "open")
        self.assertAlmostEqual(runtime.outdoor_temperature_value, 17.7778, places=3)
        self.assertFalse(runtime.outdoor_temperature_passed)

    async def test_advanced_temperature_sources_normalize_fahrenheit_and_kelvin(self):
        cases = (
            ("°F", "80", "82", "68"),
            ("K", "300", "301", "293.15"),
        )
        for unit, below_heat, above_heat, outdoor_value in cases:
            with self.subTest(unit=unit):
                config = base_config()
                room = config["rooms"][0]
                room.update(
                    {
                        "indoor_temperature": "sensor.indoor",
                        "outdoor_temperature": "sensor.outdoor",
                        "outdoor_minimum": 18.0,
                        "normal_shading_temperature": 23.5,
                        "heat_temperature": 27.0,
                        "heat_requires_sun": False,
                    }
                )
                self.hass.states.values["sensor.indoor"] = FakeState(
                    below_heat, unit_of_measurement=unit
                )
                self.hass.states.values["sensor.outdoor"] = FakeState(
                    outdoor_value, unit_of_measurement=unit
                )
                engine = engine_mod.SmartShadingEngine(
                    self.hass, FakeEntry(config)
                )
                await engine.async_initialize()
                engine._evening_release_reached = lambda _room, _now: False

                await engine.async_evaluate_all(f"advanced_{unit}_below_heat")
                self.assertNotEqual(engine.rooms["room"].mode, "heat")

                self.hass.states.values["sensor.indoor"] = FakeState(
                    above_heat, unit_of_measurement=unit
                )
                await engine.async_evaluate_all(f"advanced_{unit}_above_heat")
                self.assertEqual(engine.rooms["room"].mode, "heat")

    async def test_decision_snapshot_temperatures_are_celsius_with_source_units(self):
        """Pure/virtual decisions must share live temperature semantics."""
        for unit, indoor_raw, outdoor_raw, expected_indoor, expected_outdoor in (
            ("°F", "80", "68", 26.6667, 20.0),
            ("K", "300", "293.15", 26.85, 20.0),
        ):
            with self.subTest(unit=unit):
                config = base_config()
                room = config["rooms"][0]
                room.update(
                    {
                        "indoor_temperature": "sensor.indoor",
                        "outdoor_temperature": "sensor.outdoor",
                    }
                )
                self.hass.states.values["sensor.indoor"] = FakeState(
                    indoor_raw, unit_of_measurement=unit
                )
                self.hass.states.values["sensor.outdoor"] = FakeState(
                    outdoor_raw, unit_of_measurement=unit
                )
                engine = engine_mod.SmartShadingEngine(
                    self.hass, FakeEntry(config)
                )
                await engine.async_initialize()

                snapshot = engine._advanced_input_snapshot(
                    engine.room_config("room"), datetime.now(timezone.utc)
                )
                indoor = snapshot.get("indoor_temperature")
                outdoor = snapshot.get("outdoor_temperature")
                self.assertAlmostEqual(indoor.value, expected_indoor, places=3)
                self.assertAlmostEqual(outdoor.value, expected_outdoor, places=3)
                self.assertEqual(indoor.raw_value, indoor_raw)
                self.assertEqual(outdoor.raw_value, outdoor_raw)
                self.assertEqual(indoor.unit, "°C")
                self.assertEqual(outdoor.unit, "°C")
                self.assertEqual(indoor.details["source_unit"], unit)
                self.assertEqual(outdoor.details["normalized_unit"], "°C")

    async def test_easy_without_outdoor_sensor_ignores_weather_temperature(self):
        config = base_config()
        config.update({"advanced_mode": False, "weather_entity": "weather.home"})
        room = config["rooms"][0]
        room.update({
            "outdoor_temperature": "",
            "outdoor_minimum": 18.0,
        })
        room["sectors"][0]["lux_sensor"] = ""
        self.hass.states.values["weather.home"] = FakeState(
            "unavailable", temperature=30, temperature_unit="°C"
        )
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()

        await engine.async_evaluate_all("easy_temperature_stale_weather")

        runtime = engine.rooms["room"]
        self.assertEqual(runtime.mode, "solar")
        self.assertIsNone(runtime.outdoor_temperature_source)
        self.assertIsNone(runtime.outdoor_temperature_value)
        self.assertIsNone(runtime.outdoor_temperature_passed)

    async def test_easy_shared_source_updates_every_sector(self):
        config = base_config()
        config["advanced_mode"] = False
        room = config["rooms"][0]
        south = room["sectors"][0]
        south.update({
            "sun_presence_entity": "binary_sensor.facade_sun",
            "lux_sensor": "",
        })
        east = deepcopy(south)
        east.update({"id": "east", "name": "East", "short": "E", "layers": []})
        room["sectors"].append(east)
        self.hass.states.values["binary_sensor.facade_sun"] = FakeState("on")
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()

        self.assertEqual(
            len(engine._find_sectors_by_source("binary_sensor.facade_sun")), 2
        )
        await engine.async_evaluate_all("easy_shared_on")
        self.assertTrue(engine.sun_runtime["south"].confirmation_state)
        self.assertTrue(engine.sun_runtime["east"].confirmation_state)

        old_state = self.hass.states.values["binary_sensor.facade_sun"]
        new_state = FakeState("off")
        self.hass.states.values["binary_sensor.facade_sun"] = new_state
        await engine._async_state_changed(
            FakeEvent("binary_sensor.facade_sun", old_state, new_state)
        )
        self.assertFalse(engine.sun_runtime["south"].confirmation_state)
        self.assertFalse(engine.sun_runtime["east"].confirmation_state)

    async def test_easy_lux_delay_timer_re_evaluates_after_transition(self):
        config = base_config()
        config["advanced_mode"] = False
        sector = config["rooms"][0]["sectors"][0]
        sector.update({
            "sun_preset": "custom",
            "sun_on_lux": 10000,
            "sun_off_lux": 5000,
            "sun_on_delay": 1,
            "sun_off_delay": 1,
        })
        self.hass.states.values["sensor.lux"] = FakeState("50000")
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()
        callbacks = []
        original_call_later = engine_mod.async_call_later
        original_now = engine_mod.dt_util.now
        start = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)
        engine_mod.async_call_later = (
            lambda hass, seconds, callback: (
                callbacks.append(callback) or (lambda: None)
            )
        )
        engine_mod.dt_util.now = lambda: start
        try:
            await engine._update_sun_presence(sector, start)
            self.assertTrue(callbacks)
            evaluations = []

            async def fake_evaluate(trigger):
                evaluations.append(trigger)

            engine.async_evaluate_all = fake_evaluate
            engine_mod.dt_util.now = lambda: start + timedelta(minutes=1, seconds=1)
            # The external-movement path now performs an immediate normal
            # re-evaluation as well, which may schedule later lifecycle
            # timers.  The first callback is the local-pause expiry we are
            # exercising here.
            await callbacks[0](None)
            self.assertTrue(engine.sun_runtime["south"].is_on)
            self.assertEqual(evaluations, ["sun_presence_timer:south"])
        finally:
            engine_mod.async_call_later = original_call_later
            engine_mod.dt_util.now = original_now

    async def test_easy_cover_feedback_never_starts_per_cover_pause(self):
        config = base_config()
        config["advanced_mode"] = False
        config["rooms"][0]["sectors"][0]["lux_sensor"] = ""
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()
        old = FakeState("open", current_position=100)
        new = FakeState("closing", current_position=70)

        await engine._async_state_changed(FakeEvent("cover.one", old, new))

        self.assertFalse(engine.cover_pauses["cover_one"].active)
        self.assertFalse(
            any(call[0:2] == ("switch", "turn_on") for call in self.hass.services.calls)
        )



    async def test_runtime_store_migration_resets_only_legacy_blocked_counter(self):
        store = self.engine.store
        store._store.value = {
            "runtime_schema": 1,
            "room_runtime": {
                "room": {
                    "suppressed_commands": 330,
                    "sent_commands": 5,
                    "pause_mode": "next_sunrise",
                }
            },
            "cover_runtime": {"cover_one": {"active": True}},
        }
        await store.async_load()
        self.assertEqual(store.data["runtime_schema"], 5)
        self.assertEqual(store.data["room_runtime"]["room"]["suppressed_commands"], 0)
        self.assertEqual(store.data["room_runtime"]["room"]["sent_commands"], 5)
        self.assertTrue(store.data["cover_runtime"]["cover_one"]["active"])

    async def test_runtime_store_migrates_persisted_slat_overrides_once(self):
        store = self.engine.store
        store._store.value = {
            "runtime_schema": 2,
            "overrides": {
                "layer": {
                    "layer": {
                        "tilt_value_1": 10,
                        "heat_tilt": 0,
                        "open_position": 100,
                    }
                }
            },
        }
        await store.async_load()
        layer = store.data["overrides"]["layer"]["layer"]
        self.assertEqual(store.data["runtime_schema"], 5)
        self.assertEqual(layer["tilt_value_1"], 90.0)
        self.assertEqual(layer["heat_tilt"], 100.0)
        self.assertEqual(layer["open_position"], 100)

        await store.async_load()
        layer = store.data["overrides"]["layer"]["layer"]
        self.assertEqual(layer["tilt_value_1"], 90.0)
        self.assertEqual(layer["heat_tilt"], 100.0)

    async def test_runtime_store_migrates_pause_duration_into_one_override(self):
        store = self.engine.store
        store._store.value = {
            "runtime_schema": 3,
            "overrides": {},
            "room_runtime": {
                "room": {
                    "pause_hours": 4.5,
                    "pause_mode": "auto",
                }
            },
        }

        await store.async_load()

        self.assertEqual(store.data["runtime_schema"], 5)
        self.assertEqual(
            store.data["overrides"]["room"]["room"][
                "pause_duration_hours"
            ],
            4.5,
        )
        self.assertNotIn(
            "pause_hours", store.data["room_runtime"]["room"]
        )

    async def test_configured_pause_duration_wins_over_stale_runtime_copy(self):
        config = base_config()
        config["rooms"][0]["pause_duration_hours"] = 4.0
        engine = engine_mod.SmartShadingEngine(
            self.hass, FakeEntry(config)
        )
        engine.store._store.value = {
            "runtime_schema": 4,
            "room_runtime": {
                "room": {
                    "pause_hours": 2.0,
                    "pause_mode": "auto",
                }
            },
        }

        await engine.async_initialize()
        await engine.async_set_pause_mode("room", "timed")

        runtime = engine.rooms["room"]
        self.assertEqual(runtime.pause_hours, 4.0)
        self.assertIsNotNone(runtime.pause_until)
        remaining = runtime.pause_until - datetime.now(timezone.utc)
        self.assertGreater(remaining, timedelta(hours=3, minutes=59))
        self.assertLessEqual(remaining, timedelta(hours=4))
        self.assertNotIn(
            "pause_hours", engine.store.room_runtime("room")
        )

    async def test_runtime_store_migrates_schema_four_ledger_queue_and_heat_phase(self):
        store = self.engine.store
        store._store.value = {
            "runtime_schema": 4,
            "command_ledger": {"cover_one": {"schema": 1, "marker": "keep"}},
            "queued_commands": {"first": {"cover_id": "cover_one", "axis": "tilt"}},
            "decision_traces": {"room": {"marker": "keep"}},
            "room_runtime": {"room": {"heat_active": True}},
        }

        await store.async_load()

        self.assertEqual(store.data["runtime_schema"], 5)
        self.assertEqual(
            store.data["command_ledger"]["cover_one"]["marker"], "keep"
        )
        self.assertEqual(
            store.queued_commands(),
            [{"cover_id": "cover_one", "axis": "tilt"}],
        )
        self.assertEqual(store.data["decision_traces"]["room"]["marker"], "keep")
        self.assertEqual(store.data["room_runtime"]["room"]["heat_phase"], "active")

    async def test_runtime_store_can_clear_folded_configuration_overrides(self):
        store = self.engine.store
        store.data["overrides"] = {
            "room": {"room": {"heat_temperature": 30.0}}
        }

        await store.async_clear_overrides()

        self.assertEqual(store.data["overrides"], {})
        self.assertEqual(store._store.value["overrides"], {})

    async def test_venetian_modes_use_knx_slat_semantics(self):
        layer = self.engine.layer_config("layer")
        self.assertEqual(self.engine._targets(layer, "open", 35), (100.0, 0.0))
        self.assertEqual(self.engine._targets(layer, "solar", 35), (0.0, 65.0))
        self.assertEqual(self.engine._targets(layer, "heat", 35), (0.0, 100.0))
        self.assertEqual(self.engine._targets(layer, "safety", 35), (100.0, 0.0))

    async def test_curtain_heat_position_is_always_effective(self):
        layer = self.engine.layer_config("layer")
        layer.update(
            {
                "profile": "curtain",
                "solar_position": 42.0,
                "heat_position": 12.0,
            }
        )
        self.assertEqual(self.engine._targets(layer, "heat", 35), (12.0, None))

    async def test_every_position_profile_uses_its_own_mode_defaults(self):
        layer = self.engine.layer_config("layer")
        expected = {
            "roller_shutter": {
                "open": 100.0, "comfort": 65.0, "solar": 25.0,
                "heat": 0.0, "night": 0.0, "safety": 100.0,
            },
            "exterior_screen": {
                "open": 100.0, "comfort": 60.0, "solar": 15.0,
                "heat": 0.0, "night": 0.0, "safety": 100.0,
            },
            "curtain": {
                "open": 100.0, "comfort": 60.0, "solar": 30.0,
                "heat": 30.0, "night": 0.0, "safety": 100.0,
            },
            "awning": {
                "open": 0.0, "comfort": 60.0, "solar": 100.0,
                "heat": 100.0, "night": 0.0, "safety": 0.0,
            },
            "binary_cover": {
                "open": 100.0, "comfort": 0.0, "solar": 0.0,
                "heat": 0.0, "night": 0.0, "safety": 100.0,
            },
        }
        for profile, modes in expected.items():
            with self.subTest(profile=profile):
                covers = layer.get("covers", [])
                layer.clear()
                layer.update(deepcopy(engine_mod.PROFILE_DEFAULTS[profile]))
                layer.update({"id": "layer", "profile": profile, "covers": covers})
                for mode, position in modes.items():
                    self.assertEqual(
                        self.engine._targets(layer, mode, 35),
                        (position, None),
                    )

    async def test_vertical_blind_uses_position_and_slat_profile(self):
        layer = self.engine.layer_config("layer")
        covers = layer.get("covers", [])
        layer.clear()
        layer.update(deepcopy(engine_mod.PROFILE_DEFAULTS["vertical_blind"]))
        layer.update({"id": "layer", "profile": "vertical_blind", "covers": covers})

        self.assertEqual(self.engine._targets(layer, "open", 35), (100.0, 0.0))
        self.assertEqual(self.engine._targets(layer, "comfort", 35), (0.0, 35.0))
        self.assertEqual(self.engine._targets(layer, "heat", 35), (0.0, 100.0))
        self.assertEqual(self.engine._targets(layer, "safety", 35), (100.0, 0.0))

    async def test_per_cover_slat_inversion_changes_only_command_value(self):
        layer = self.engine.layer_config("layer")
        second = deepcopy(layer["covers"][0])
        second.update({
            "id": "cover_two",
            "entity": "cover.two",
            "name": "Cover two",
            "short": "C2",
            "lock": "",
            "invert_tilt": True,
        })
        layer["covers"].append(second)
        self.hass.states.values["cover.one"] = FakeState(
            "closed", current_position=0, current_tilt_position=50
        )
        self.hass.states.values["cover.two"] = FakeState(
            "closed", current_position=0, current_tilt_position=50
        )
        self.hass.services.calls.clear()

        await self.engine._apply_sector_mode(
            self.engine.room_config("room"),
            self.engine.sector_config("south"),
            self.engine.rooms["room"],
            "heat",
            35,
            "test",
        )

        tilt_calls = {
            call[2]["entity_id"]: call[2]["tilt_position"]
            for call in self.hass.services.calls
            if call[0:2] == ("cover", "set_cover_tilt_position")
        }
        self.assertEqual(tilt_calls, {"cover.one": 100, "cover.two": 0})
        targets = {target["entity_id"]: target for target in self.engine.rooms["room"].targets}
        self.assertEqual(targets["cover.one"]["tilt"], 100.0)
        self.assertEqual(targets["cover.one"]["command_tilt"], 100.0)
        self.assertEqual(targets["cover.one"]["tilt_mapping"], "knx_default")
        self.assertEqual(targets["cover.two"]["tilt"], 100.0)
        self.assertEqual(targets["cover.two"]["command_tilt"], 0.0)
        self.assertEqual(targets["cover.two"]["tilt_mapping"], "inverted")

    async def test_real_ha_lux_state_turns_balanced_sector_on_after_three_minutes(self):
        start = datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)
        sector = self.engine.sector_config("south")
        await self.engine._update_sun_presence(sector, start)
        runtime = self.engine.sun_runtime["south"]
        self.assertFalse(runtime.is_on)
        self.assertTrue(runtime.pending_target)
        self.assertEqual(runtime.current_lux, 26398.72)
        await self.engine._update_sun_presence(sector, start + timedelta(minutes=3))
        self.assertTrue(runtime.is_on)
        self.assertIsNone(runtime.pending_target)

    async def test_preset_values_override_stale_beta_thresholds(self):
        sector = self.engine.sector_config("south")
        sector.update({"sun_on_lux": 65000, "sun_off_lux": 50000, "sun_on_delay": 30})
        settings = self.engine._sun_settings("south")
        self.assertEqual(settings["sun_on_lux"], 18000)
        self.assertEqual(settings["sun_off_lux"], 9000)
        self.assertEqual(settings["sun_on_delay"], 3)

    async def test_custom_profile_uses_custom_thresholds(self):
        sector = self.engine.sector_config("south")
        sector.update({
            "sun_preset": "custom",
            "sun_on_lux": 21000,
            "sun_off_lux": 12000,
            "sun_on_delay": 4,
            "sun_off_delay": 14,
        })
        settings = self.engine._sun_settings("south")
        self.assertEqual(settings, {
            "sun_on_lux": 21000.0,
            "sun_off_lux": 12000.0,
            "sun_on_delay": 4.0,
            "sun_off_delay": 14.0,
        })


    async def test_full_evaluation_uses_real_lux_and_shades_inside_sector(self):
        self.engine.sun_runtime["south"].is_on = True
        self.hass.services.calls.clear()
        await self.engine.async_evaluate_all("test_full_evaluation")
        self.assertEqual(self.engine.rooms["room"].mode, "solar")
        cover_calls = [call for call in self.hass.services.calls if call[0] == "cover"]
        self.assertTrue(any(call[1] == "set_cover_position" and call[2].get("position") == 0 for call in cover_calls))

    async def test_advanced_evaluation_persists_a_complete_live_decision_trace(self):
        self.engine.sun_runtime["south"].is_on = True
        self.engine.sun_runtime["south"].current_lux = 26398.72
        await self.engine._evaluate_room(
            self.engine.room_config("room"),
            datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc),
        )

        trace = self.engine.rooms["room"].decision_trace
        self.assertEqual(trace["mode"], self.engine.rooms["room"].mode)
        self.assertEqual(trace["winner"]["mode"], self.engine.rooms["room"].mode)
        self.assertTrue(trace["entries"])
        self.assertIn("sun_azimuth", trace["input_snapshot"]["inputs"])
        self.assertTrue(trace["target_decisions"])

    async def test_protected_zone_changes_only_the_scoped_solar_layer_target(self):
        room = self.engine.room_config("room")
        sector = self.engine.sector_config("south")
        sector["protected_zones"] = [
            {
                "id": "desk",
                "name": "Desk",
                "group_ids": ["layer"],
                "enabled": True,
                "distance_m": 1.5,
                "lower_height_m": 0.2,
                "upper_height_m": 0.8,
                "target_position": 15,
                "target_tilt": 95,
            }
        ]
        self.engine.sun_runtime["south"].is_on = True
        self.engine.sun_runtime["south"].current_lux = 26398.72
        await self.engine._evaluate_room(
            room, datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
        )

        target = self.engine.rooms["room"].targets[0]
        # Venetian Solar already uses the maximally protective height. The
        # zone still narrows the slat target and remains fully traceable.
        self.assertEqual(target["position"], 0.0)
        self.assertEqual(target["tilt"], 95.0)
        zone = self.engine.rooms["room"].decision_trace["target_decisions"][0]["decision"]["trace"]["protected_zones"][0]
        self.assertEqual(zone["zone_id"], "desk")
        self.assertEqual(zone["status"], "hit")

    async def test_quality_hold_prevents_new_solar_cover_service(self):
        room = self.engine.room_config("room")
        room["source_stale_seconds"] = 1
        self.hass.states.values["sensor.lux"] = FakeState(
            "26398.72",
            unit_of_measurement="lx",
            last_updated=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        self.engine.sun_runtime["south"].is_on = True
        self.engine.sun_runtime["south"].current_lux = 26398.72
        self.hass.services.calls.clear()

        await self.engine._evaluate_room(room, datetime.now(timezone.utc))

        self.assertEqual(self.engine.rooms["room"].mode, "idle")
        self.assertFalse(any(call[0] == "cover" for call in self.hass.services.calls))
        trace = self.engine.rooms["room"].decision_trace["target_decisions"][0]
        self.assertTrue(trace["held"])
        self.assertEqual(trace["decision"]["mode"], "idle")

    async def test_safety_trace_keeps_real_solar_candidate_as_rejected(self):
        """Safety wins actions without hiding simultaneous Solar conditions."""
        room = self.engine.room_config("room")
        room["safety_blockers"] = ["binary_sensor.wind"]
        self.engine.sector_config("south")["sun_source"] = "geometry"
        self.hass.states.values["binary_sensor.wind"] = FakeState("on")

        await self.engine._evaluate_room(room, datetime.now(timezone.utc))

        trace = self.engine.rooms["room"].decision_trace
        self.assertEqual(trace["winner"]["rule"], "safety")
        solar = next(
            candidate for candidate in trace["rejected"] if candidate["rule"] == "solar"
        )
        self.assertTrue(solar["matched"])
        self.assertEqual(solar["reason_code"], "solar_conditions_met")
        facts = trace["decision"]["trace"]["context_details"]["decision_facts"]
        self.assertTrue(facts["safety_active"])
        self.assertTrue(facts["solar_active"])

    async def test_simulation_and_preview_never_call_cover_services(self):
        self.engine.sun_runtime["south"].is_on = True
        self.engine.sun_runtime["south"].current_lux = 26398.72
        self.hass.services.calls.clear()

        simulation = await self.engine.async_simulate_room(
            "room", {"sun_elevation": "unavailable"}
        )
        now = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
        preview = await self.engine.async_preview_room_day(
            "room",
            [
                {"at": now, "mode": "open", "label": "open"},
                {
                    "at": now + timedelta(hours=1),
                    "mode": "solar",
                    "label": "solar",
                },
            ],
        )

        self.assertTrue(simulation["available"])
        self.assertTrue(self.engine.rooms["room"].simulation_active)
        self.assertTrue(preview["available"])
        self.assertTrue(preview["day_preview"]["samples"])
        self.assertFalse(any(call[0] == "cover" for call in self.hass.services.calls))

    async def test_virtual_inputs_recompute_simulation_and_preview_facts(self):
        """Virtual sun/Lux values must not reuse the live sector mode."""
        self.engine.sun_runtime["south"].is_on = False
        self.engine.sun_runtime["south"].current_lux = 0.0
        at = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)

        dark = await self.engine.async_simulate_room(
            "room",
            {"at": at, "sun_state": "below_horizon"},
        )
        bright = await self.engine.async_simulate_room(
            "room",
            {"at": at, "lux": 30000},
        )
        self.assertEqual(dark["result"]["mode"], "open")
        self.assertEqual(bright["result"]["mode"], "solar")

        preview = await self.engine.async_preview_room_day(
            "room",
            [
                {
                    "at": at,
                    "label": "dark",
                    "overrides": {"sun_state": "below_horizon"},
                },
                {
                    "at": at + timedelta(hours=1),
                    "label": "bright",
                    "overrides": {"lux": 30000},
                },
            ],
        )
        modes = {
            sample["label"]: sample["result"]["mode"]
            for sample in preview["preview"]["samples"]
        }
        self.assertEqual(modes, {"dark": "open", "bright": "solar"})

    async def test_simulation_projects_virtual_per_cover_constraints(self):
        """A virtual unsafe window/lock/pause blocks only the simulated cover."""
        cover = self.engine.config["rooms"][0]["sectors"][0]["layers"][0][
            "covers"
        ][0]
        cover.update(
            {
                "window": "binary_sensor.window",
                "window_safe_state": "on",
                "window_policy": "block_all",
            }
        )
        self.hass.states.values["binary_sensor.window"] = FakeState("on")
        at = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
        self.hass.services.calls.clear()

        unsafe_window = await self.engine.async_simulate_room(
            "room",
            {
                "at": at,
                "lux": 30000,
                "cover:cover_one:window_state": "off",
            },
        )
        window_target = unsafe_window["results"][0]["cover_targets"][0]
        self.assertEqual(window_target["command_result"], "blocked")
        self.assertIn("unsafe_window", window_target["constraints"])
        self.assertEqual(window_target["command_position"], 0.0)

        locked = await self.engine.async_simulate_room(
            "room",
            {"at": at, "lux": 30000, "cover:cover_one:lock_active": True},
        )
        lock_target = locked["results"][0]["cover_targets"][0]
        self.assertEqual(lock_target["command_result"], "blocked")
        self.assertIn("automation_lock", lock_target["constraints"])

        paused = await self.engine.async_simulate_room(
            "room",
            {"at": at, "lux": 30000, "cover:cover_one:pause_active": True},
        )
        pause_target = paused["results"][0]["cover_targets"][0]
        self.assertEqual(pause_target["command_result"], "blocked")
        self.assertIn("cover_paused_until_morning", pause_target["constraints"])

        # Binary covers have no numeric position attribute in many HA
        # integrations.  The projection must mirror the real adapter and use
        # open/closed state so an already-open virtual target is not reported
        # as an unnecessary simulated command.
        layer = self.engine.config["rooms"][0]["sectors"][0]["layers"][0]
        layer["profile"] = "binary_cover"
        cover.pop("window", None)
        cover.pop("window_policy", None)
        self.hass.states.values[cover["entity"]] = FakeState("open")
        binary_open = await self.engine.async_simulate_room(
            "room", {"at": at, "sun_state": "below_horizon"}
        )
        binary_target = binary_open["results"][0]["cover_targets"][0]
        self.assertEqual(binary_target["current_position"], 100.0)
        self.assertEqual(binary_target["command_result"], "suppressed")
        self.assertEqual(binary_target["reason_code"], "target_within_tolerance")
        self.assertFalse(any(call[0] == "cover" for call in self.hass.services.calls))

    async def test_selected_day_preview_uses_virtual_solar_geometry_and_boundaries(self):
        """A chosen date must not replay the current ``sun.sun`` coordinates."""
        previous_modules = {
            name: sys.modules.get(name) for name in ("astral", "astral.sun")
        }
        astral_mod = types.ModuleType("astral")
        sun_mod = types.ModuleType("astral.sun")

        class Observer:
            def __init__(self, *, latitude, longitude):
                self.latitude = latitude
                self.longitude = longitude

        def azimuth(_observer, at):
            return ((at.hour + at.minute / 60) * 15.0) % 360.0

        def elevation(_observer, at):
            hour = at.hour + at.minute / 60
            return 60.0 - abs(hour - 12.0) * 10.0

        def solar_events(_observer, *, date, tzinfo=None):
            return {
                "sunrise": datetime(
                    date.year, date.month, date.day, 6, 0, tzinfo=tzinfo
                ),
                "sunset": datetime(
                    date.year, date.month, date.day, 18, 0, tzinfo=tzinfo
                ),
            }

        astral_mod.Observer = Observer
        sun_mod.azimuth = azimuth
        sun_mod.elevation = elevation
        sun_mod.sun = solar_events
        sys.modules["astral"] = astral_mod
        sys.modules["astral.sun"] = sun_mod

        def restore_astral_modules():
            for name, module in previous_modules.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

        self.addCleanup(restore_astral_modules)
        self.hass.config.latitude = 49.61
        self.hass.config.longitude = 6.13
        room = self.engine.room_config("room")
        room.update({"night_enabled": True, "night_source": "sun"})
        self.engine.sector_config("south")["sun_source"] = "geometry"
        self.hass.services.calls.clear()

        preview = await self.engine.async_preview_room_day(
            "room", {"date": "2031-06-21"}
        )

        data = preview["preview"]
        samples = data["samples"]
        self.assertEqual(preview["date"], "2031-06-21")
        self.assertEqual(data["assumptions"]["solar_source"], "astral")
        self.assertGreater(len(samples), 280)
        self.assertTrue(
            all(
                "scope" in sample and "sun" in sample and "reason_code" in sample
                for sample in samples
            )
        )
        self.assertTrue(any(sample["sun"]["elevation"] < 0 for sample in samples))
        self.assertTrue(any(sample["sun"]["elevation"] >= 60 for sample in samples))
        self.assertTrue(data["sector_periods"])
        period = data["sector_periods"][0]
        self.assertTrue(period["started_at"].startswith("2031-06-21T08:"))
        self.assertTrue(period["ended_at"].startswith("2031-06-21T16:"))
        solar_targets = {
            sample["result"]["target"]["tilt"]
            for sample in samples
            if sample["result"]["mode"] == "solar"
            and sample["result"].get("target")
        }
        self.assertGreaterEqual(len(solar_targets), 3)
        self.assertTrue(
            any(
                transition["scope"]["sector_id"] == "south"
                for transition in data["transitions"]
            )
        )
        self.assertFalse(any(call[0] == "cover" for call in self.hass.services.calls))

        # Legacy preview callers can still pass a mode field, but it no longer
        # fakes candidates ahead of the production resolver.
        noon = await self.engine.async_preview_room_day(
            "room",
            [
                {
                    "at": datetime(2031, 6, 21, 12, 0, tzinfo=timezone.utc),
                    "mode": "open",
                }
            ],
        )
        self.assertEqual(noon["preview"]["samples"][0]["result"]["mode"], "solar")
        self.assertTrue(noon["ignored_mode_hints"])

    async def test_geometry_boundary_timer_schedules_sector_entry_exactly(self):
        """Facade entry is an exact event, not a watchdog-only evaluation."""
        room = self.engine.room_config("room")
        now = datetime(2031, 6, 21, 8, 0, tzinfo=timezone.utc)
        scheduled = []
        queued = []
        original_geometry = self.engine._virtual_solar_geometry
        original_call_later = engine_mod.async_call_later
        original_now = engine_mod.dt_util.now
        original_queue = self.engine._queue_evaluation

        def geometry(at, *, trajectory=None):
            elapsed_minutes = (at - now).total_seconds() / 60.0
            return (
                {
                    "sun_state": "above_horizon",
                    "sun_azimuth": 100.0 + elapsed_minutes,
                    "sun_elevation": 35.0,
                },
                "astral",
            )

        def call_later(_hass, seconds, callback):
            scheduled.append((seconds, callback))
            return lambda: None

        async def queue(trigger, *, immediate=False):
            queued.append((trigger, immediate))

        self.engine._virtual_solar_geometry = geometry
        self.engine._queue_evaluation = queue
        engine_mod.async_call_later = call_later
        engine_mod.dt_util.now = lambda: now

        def restore_timer_dependencies():
            self.engine._virtual_solar_geometry = original_geometry
            self.engine._queue_evaluation = original_queue
            engine_mod.async_call_later = original_call_later
            engine_mod.dt_util.now = original_now

        self.addCleanup(restore_timer_dependencies)
        self.engine._schedule_geometry_boundary_timer(room, now)

        self.assertEqual(len(scheduled), 1)
        seconds, callback = scheduled[0]
        self.assertAlmostEqual(seconds, 20 * 60 + 0.1, delta=1.1)
        await callback(None)
        self.assertEqual(queued, [("geometry_boundary:room", True)])

    async def test_disabled_sector_never_plans_open_fallback(self):
        sector = self.engine.sector_config("south")
        sector["enabled"] = False
        self.hass.services.calls.clear()

        await self.engine.async_evaluate_all("disabled_sector")

        self.assertEqual(self.engine.sun_runtime["south"].mode, "disabled")
        self.assertFalse(any(call[0] == "cover" for call in self.hass.services.calls))

    async def test_verification_outcome_persists_trace_without_a_due_retry(self):
        room = self.engine.room_config("room")
        room.update(
            {
                "target_verification_enabled": True,
                "verification_retries": 0,
                "movement_seconds": 0,
                "settling_seconds": 0,
            }
        )
        self.engine.sun_runtime["south"].is_on = True
        self.engine.sun_runtime["south"].current_lux = 26398.72
        start = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
        original_now = engine_mod.dt_util.now
        notifications: list[bool] = []
        remove = self.engine.async_add_listener(lambda: notifications.append(True))
        engine_mod.dt_util.now = lambda: start
        try:
            await self.engine.async_evaluate_all("verification_setup")
            entry = self.engine.command_planner.ledger_entry("cover_one")
            self.assertIsNotNone(entry)
            assert entry is not None
            self.assertEqual(entry.result.value, "sent")
            engine_mod.dt_util.now = lambda: start + timedelta(minutes=2)
            before_notifications = len(notifications)
            await self.engine._verify_due_command_lifecycles()
        finally:
            engine_mod.dt_util.now = original_now
            remove()

        target = self.engine.rooms["room"].targets[0]
        self.assertEqual(target["command_result"], "target_not_reached")
        self.assertEqual(
            self.engine.rooms["room"].decision_trace["command_results"][0]["status"],
            "target_not_reached",
        )
        nested = self.engine.rooms["room"].decision_trace["target_decisions"][0]["covers"][0]["command"]
        self.assertEqual(nested["trace"]["command_result"]["status"], "target_not_reached")
        self.assertEqual(
            self.engine.store.data["decision_traces"]["room"]["command_results"][0]["status"],
            "target_not_reached",
        )
        self.assertGreater(len(notifications), before_notifications)

    async def test_trusted_feedback_persists_target_reached_trace(self):
        room = self.engine.room_config("room")
        room.update(
            {
                "target_verification_enabled": True,
                "movement_seconds": 0,
                "settling_seconds": 0,
            }
        )
        self.engine.sun_runtime["south"].is_on = True
        self.engine.sun_runtime["south"].current_lux = 26398.72
        start = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
        original_now = engine_mod.dt_util.now
        engine_mod.dt_util.now = lambda: start
        try:
            await self.engine.async_evaluate_all("feedback_setup")
            await self.engine._record_command_feedback(
                "cover.one",
                FakeState("closed", current_position=0, current_tilt_position=65),
            )
        finally:
            engine_mod.dt_util.now = original_now

        target = self.engine.rooms["room"].targets[0]
        self.assertEqual(target["command_result"], "target_reached")
        nested = self.engine.rooms["room"].decision_trace["target_decisions"][0]["covers"][0]["command"]
        self.assertEqual(nested["trace"]["command_result"]["status"], "target_reached")

    async def test_sun_presence_on_still_respects_sector_geometry(self):
        self.engine.sun_runtime["south"].is_on = True
        self.hass.states.values["sun.sun"] = FakeState(
            "above_horizon",
            azimuth=244.43,
            elevation=46.94,
            next_rising=(datetime.now(timezone.utc) + timedelta(hours=12)).isoformat(),
            next_setting=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        )
        await self.engine.async_evaluate_all("test_geometry")
        self.assertEqual(self.engine.rooms["room"].mode, "open")
        self.assertEqual(self.engine.sun_runtime["south"].status, "outside_sun_sector")
        self.assertTrue(self.engine.sun_runtime["south"].is_on)

    async def test_safety_overrides_local_cover_pause_and_lock(self):
        config = base_config()
        config["rooms"][0]["safety_blockers"] = ["binary_sensor.wind"]
        config["rooms"][0]["sectors"][0]["layers"][0]["covers"][0][
            "max_open_position"
        ] = 70
        self.hass.states.values["binary_sensor.wind"] = FakeState("on")
        self.hass.states.values["cover.one"] = FakeState("closed", current_position=0, current_tilt_position=0)
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()
        await engine._activate_cover_pause(config["rooms"][0], config["rooms"][0]["sectors"][0]["layers"][0]["covers"][0], "manual")
        self.hass.services.calls.clear()
        await engine.async_evaluate_all("test_safety")
        self.assertEqual(engine.rooms["room"].mode, "safety")
        self.assertTrue(any(call[0:2] == ("cover", "set_cover_position") and call[2].get("position") == 100 for call in self.hass.services.calls))

    async def test_unsafe_window_blocks_normal_closing(self):
        config = base_config()
        cover = config["rooms"][0]["sectors"][0]["layers"][0]["covers"][0]
        cover["window"] = "binary_sensor.window"
        cover["window_safe_state"] = "on"
        cover["window_policy"] = "block_closing"
        self.hass.states.values["binary_sensor.window"] = FakeState("off")
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()
        engine.sun_runtime["south"].is_on = True
        self.hass.services.calls.clear()
        await engine.async_evaluate_all("test_window")
        self.assertFalse(any(call[0] == "cover" for call in self.hass.services.calls))
        target = engine.rooms["room"].targets[0]
        self.assertIn("unsafe_window_closing_blocked", target["suppressed"])

    async def test_unsafe_window_uses_inverted_command_space_to_block_closing(self):
        config = base_config()
        room = config["rooms"][0]
        sector = room["sectors"][0]
        layer = sector["layers"][0]
        cover = layer["covers"][0]
        cover.update({
            "window": "binary_sensor.window",
            "window_safe_state": "on",
            "window_policy": "block_closing",
            "invert_position": True,
        })
        self.hass.states.values["binary_sensor.window"] = FakeState("off")
        self.hass.states.values["cover.one"] = FakeState(
            "open", current_position=50, current_tilt_position=50
        )
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()
        self.hass.services.calls.clear()
        engine.rooms["room"].targets.clear()

        # Logical 80% is sent as 20% by this inverted cover and is therefore
        # a real closing movement from the current 50% feedback.
        await engine._apply_cover(
            room, sector, layer, cover, engine.rooms["room"],
            "open", 80.0, None, "inverted closing",
        )

        self.assertFalse(any(call[0] == "cover" for call in self.hass.services.calls))
        self.assertIn(
            "unsafe_window_closing_blocked",
            engine.rooms["room"].targets[-1]["suppressed"],
        )

    async def test_unsafe_window_allows_inverted_command_space_opening(self):
        config = base_config()
        room = config["rooms"][0]
        sector = room["sectors"][0]
        layer = sector["layers"][0]
        cover = layer["covers"][0]
        cover.update({
            "window": "binary_sensor.window",
            "window_safe_state": "on",
            "window_policy": "block_closing",
            "invert_position": True,
        })
        self.hass.states.values["binary_sensor.window"] = FakeState("off")
        self.hass.states.values["cover.one"] = FakeState(
            "open", current_position=50, current_tilt_position=50
        )
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()
        self.hass.services.calls.clear()
        engine.rooms["room"].targets.clear()

        # Logical 20% is sent as 80% and safely opens in command space.
        await engine._apply_cover(
            room, sector, layer, cover, engine.rooms["room"],
            "open", 20.0, None, "inverted opening",
        )

        self.assertTrue(any(
            call[0:2] == ("cover", "set_cover_position")
            and call[2].get("position") == 80
            for call in self.hass.services.calls
        ))

    async def test_external_cover_change_starts_local_pause_and_lock(self):
        old = FakeState("open", current_position=100, current_tilt_position=100)
        new = FakeState("closing", current_position=70, current_tilt_position=100)
        await self.engine._async_state_changed(FakeEvent("cover.one", old, new))
        pause = self.engine.cover_pauses["cover_one"]
        self.assertTrue(pause.active)
        self.assertEqual(self.hass.states.get("switch.cover_lock").state, "on")
        self.assertTrue(any(call[0:2] == ("switch", "turn_on") for call in self.hass.services.calls))

    async def test_own_cover_feedback_does_not_start_pause(self):
        now = datetime.now(timezone.utc)
        self.engine.command_memory["cover.one"] = models_mod.CommandMemory(
            position=100,
            position_at=now,
            tilt=100,
            tilt_at=now,
            last_activity_at=now,
        )
        old = FakeState("opening", current_position=0, current_tilt_position=100)
        new = FakeState("opening", current_position=40, current_tilt_position=100)
        await self.engine._async_state_changed(FakeEvent("cover.one", old, new))
        self.assertFalse(self.engine.cover_pauses.get("cover_one", models_mod.CoverPauseRuntime("", "", "")).active)
        self.assertEqual(self.hass.states.get("switch.cover_lock").state, "off")

    async def test_external_lock_on_starts_pause_and_off_releases_with_evaluation(self):
        await self.engine._async_state_changed(
            FakeEvent("switch.cover_lock", FakeState("off"), FakeState("on"))
        )
        self.assertTrue(self.engine.cover_pauses["cover_one"].active)
        calls = []

        async def fake_evaluate(trigger):
            calls.append(trigger)

        self.engine.async_evaluate_all = fake_evaluate
        await self.engine._async_state_changed(
            FakeEvent("switch.cover_lock", FakeState("on"), FakeState("off"))
        )
        self.assertFalse(self.engine.cover_pauses["cover_one"].active)
        self.assertEqual(
            calls[-1], "manual_group_released:switch.cover_lock"
        )

    async def test_master_on_does_not_evaluate_and_master_off_does(self):
        calls = []

        async def fake_evaluate(trigger):
            calls.append(trigger)

        self.engine.async_evaluate_all = fake_evaluate
        await self.engine.async_set_room_enabled("room", False)
        self.assertFalse(self.engine.rooms["room"].enabled)
        self.assertEqual(self.engine.rooms["room"].mode, "disabled")
        self.assertEqual(calls, [])
        await self.engine.async_set_room_enabled("room", True)
        self.assertEqual(calls, ["manual_master_released"])

    async def test_startup_sync_creates_pause_for_existing_lock(self):
        self.hass.states.values["switch.cover_lock"] = FakeState("on")
        await self.engine._async_sync_configured_locks()
        self.assertTrue(self.engine.cover_pauses["cover_one"].active)

    async def test_next_rising_same_day_is_not_shifted_by_one_day(self):
        now = datetime.now(timezone.utc).replace(hour=4, minute=0, second=0, microsecond=0)
        rising = now.replace(hour=6)
        self.hass.states.values["sun.sun"] = FakeState(
            "below_horizon",
            azimuth=0,
            elevation=-10,
            next_rising=rising.isoformat(),
            next_setting=(rising + timedelta(hours=12)).isoformat(),
        )
        result = self.engine._pause_until_from_sun("room", "next_sunrise", now)
        self.assertEqual(result, rising)

    async def test_unavailable_lock_does_not_clear_persisted_pause(self):
        pause = models_mod.CoverPauseRuntime(
            "cover_one", "cover.one", "room", active=True,
            until=datetime.now(timezone.utc) + timedelta(hours=5), reason="manual_lock_entity"
        )
        self.engine.cover_pauses["cover_one"] = pause
        self.hass.states.values["switch.cover_lock"] = FakeState("unavailable")
        await self.engine._async_sync_configured_locks()
        self.assertTrue(self.engine.cover_pauses["cover_one"].active)

    async def test_diagnostic_export_contains_live_lux_and_runtime(self):
        url = await self.engine.async_export_diagnostics("room")
        self.assertTrue(url.startswith("/local/smart_shading_logs/"))
        path = Path("/tmp/www/smart_shading_logs") / url.rsplit("/", 1)[-1]
        self.assertTrue(path.exists())
        content = path.read_text(encoding="utf-8")
        self.assertIn('"26398.72"', content)
        self.assertIn('"evaluation_interval_seconds": 1200', content)
        self.assertIn('"sun_presence"', content)



    async def test_user_unlock_immediately_after_owned_lock_is_not_ignored(self):
        old = FakeState("open", current_position=100, current_tilt_position=100)
        new = FakeState("closing", current_position=70, current_tilt_position=100)
        await self.engine._async_state_changed(FakeEvent("cover.one", old, new))
        self.assertTrue(self.engine.cover_pauses["cover_one"].active)
        calls = []
        async def fake_evaluate(trigger):
            calls.append(trigger)
        self.engine.async_evaluate_all = fake_evaluate
        await self.engine._async_state_changed(
            FakeEvent("switch.cover_lock", FakeState("on"), FakeState("off"))
        )
        self.assertFalse(self.engine.cover_pauses["cover_one"].active)
        self.assertEqual(len(calls), 1)

    async def test_input_boolean_lock_is_supported(self):
        config = base_config()
        config["rooms"][0]["sectors"][0]["layers"][0]["covers"][0]["lock"] = "input_boolean.cover_lock"
        self.hass.states.values.pop("switch.cover_lock", None)
        self.hass.states.values["input_boolean.cover_lock"] = FakeState("off")
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()
        old = FakeState("open", current_position=100, current_tilt_position=100)
        new = FakeState("closing", current_position=70, current_tilt_position=100)
        await engine._async_state_changed(FakeEvent("cover.one", old, new))
        self.assertEqual(self.hass.states.get("input_boolean.cover_lock").state, "on")
        self.assertTrue(any(call[0:2] == ("input_boolean", "turn_on") for call in self.hass.services.calls))

    async def test_cover_pause_expiry_unlocks_and_evaluates(self):
        callbacks = []
        original = engine_mod.async_call_later
        engine_mod.async_call_later = lambda hass, seconds, callback: (callbacks.append(callback) or (lambda: None))
        try:
            old = FakeState("open", current_position=100, current_tilt_position=100)
            new = FakeState("closing", current_position=70, current_tilt_position=100)
            await self.engine._async_state_changed(FakeEvent("cover.one", old, new))
            self.assertTrue(callbacks)
            calls = []
            async def fake_evaluate(trigger):
                calls.append(trigger)
            self.engine.async_evaluate_all = fake_evaluate
            # The external-movement path performs an immediate normal
            # evaluation too, which may append a Lux/schedule timer.  The
            # first scheduled callback remains the local-pause expiry under
            # test here.
            await callbacks[0](None)
            self.assertEqual(self.hass.states.get("switch.cover_lock").state, "off")
            self.assertFalse(self.engine.cover_pauses["cover_one"].active)
            self.assertEqual(len(calls), 1)
            self.assertEqual(
                calls[0], "manual_group_released:switch.cover_lock"
            )
        finally:
            engine_mod.async_call_later = original

    async def test_repeated_external_movement_does_not_extend_pause(self):
        old = FakeState("open", current_position=100, current_tilt_position=100)
        new = FakeState("closing", current_position=70, current_tilt_position=100)
        await self.engine._async_state_changed(FakeEvent("cover.one", old, new))
        first_until = self.engine.cover_pauses["cover_one"].until
        second = FakeState("closing", current_position=40, current_tilt_position=100)
        await self.engine._async_state_changed(FakeEvent("cover.one", new, second))
        self.assertEqual(self.engine.cover_pauses["cover_one"].until, first_until)


    async def test_manual_cover_move_during_safety_re_evaluates_immediately(self):
        config = base_config()
        config["rooms"][0]["safety_blockers"] = ["binary_sensor.wind"]
        self.hass.states.values["binary_sensor.wind"] = FakeState("on")
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()
        calls = []
        async def fake_evaluate(trigger):
            calls.append(trigger)
        engine.async_evaluate_all = fake_evaluate
        old = FakeState("open", current_position=100, current_tilt_position=100)
        new = FakeState("closing", current_position=70, current_tilt_position=100)
        await engine._async_state_changed(FakeEvent("cover.one", old, new))
        self.assertTrue(engine.cover_pauses["cover_one"].active)
        self.assertEqual(calls, ["safety_manual_cover:cover.one"])

    async def test_manual_cover_move_re_evaluates_normal_trace_immediately(self):
        calls = []

        async def fake_evaluate(trigger):
            calls.append(trigger)

        self.engine.async_evaluate_all = fake_evaluate
        old = FakeState("open", current_position=100, current_tilt_position=100)
        new = FakeState("closing", current_position=70, current_tilt_position=100)
        await self.engine._async_state_changed(FakeEvent("cover.one", old, new))

        self.assertTrue(self.engine.cover_pauses["cover_one"].active)
        self.assertEqual(calls, ["external_manual_cover:cover.one"])

    async def test_normal_temperature_change_is_deferred_but_window_is_immediate(self):
        config = base_config()
        config["rooms"][0]["indoor_temperature"] = "sensor.room_temp"
        config["rooms"][0]["sectors"][0]["layers"][0]["covers"][0]["window"] = "binary_sensor.window"
        self.hass.states.values["sensor.room_temp"] = FakeState("25.1")
        self.hass.states.values["binary_sensor.window"] = FakeState("on")
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()
        calls = []
        async def fake_evaluate(trigger):
            calls.append(trigger)
        engine.async_evaluate_all = fake_evaluate
        await engine._async_state_changed(FakeEvent("sensor.room_temp", FakeState("25.0"), FakeState("25.1")))
        self.assertEqual(calls, [])
        await engine._async_state_changed(FakeEvent("binary_sensor.window", FakeState("off"), FakeState("on")))
        self.assertEqual(calls, ["critical_state:binary_sensor.window"])

    async def test_room_pause_timer_releases_and_evaluates_exactly_once(self):
        callbacks = []
        pause_changes = []

        async def record_pause_change(room_id, paused):
            pause_changes.append((room_id, paused))

        self.engine._async_room_pause_state_changed = record_pause_change
        original = engine_mod.async_call_later
        engine_mod.async_call_later = lambda hass, seconds, callback: (callbacks.append(callback) or (lambda: None))
        try:
            await self.engine.async_set_pause_mode("room", "next_sunrise")
            self.assertEqual(self.engine.rooms["room"].mode, "paused")
            self.assertTrue(callbacks)
            calls = []

            async def fake_evaluate(trigger):
                calls.append(trigger)

            self.engine.async_evaluate_all = fake_evaluate
            await callbacks[-1](None)
            self.assertEqual(self.engine.rooms["room"].pause_mode, "auto")
            self.assertEqual(len(calls), 1)
            self.assertTrue(calls[0].startswith("room_pause_ended:"))
            self.assertEqual(
                pause_changes,
                [("room", True), ("room", False)],
            )
        finally:
            engine_mod.async_call_later = original


    async def _make_heat_engine(self, *, two_sectors=False, requires_sun=True):
        config = base_config()
        room = config["rooms"][0]
        room.update({
            "indoor_temperature": "sensor.indoor",
            "heat_temperature": 27.0,
            "heat_release_temperature": 26.0,
            "heat_requires_sun": requires_sun,
        })
        south = room["sectors"][0]
        south.update({
            "sun_preset": "custom",
            "sun_on_lux": 10000,
            "sun_off_lux": 5000,
            "sun_on_delay": 0,
            "sun_off_delay": 0,
        })
        if two_sectors:
            east = deepcopy(south)
            east.update({
                "id": "east",
                "name": "East",
                "short": "E",
                "lux_sensor": "sensor.lux_east",
                "layers": [],
            })
            room["sectors"].append(east)
            self.hass.states.values["sensor.lux_east"] = FakeState("1000", unit_of_measurement="lx")
        self.hass.states.values["sensor.indoor"] = FakeState("28", unit_of_measurement="°C")
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()
        # Heat behavior tests must not depend on the UTC time at which CI runs.
        # The dedicated evening-release test overrides this with ``True``.
        engine._evening_release_reached = lambda _room, _now: False
        return engine, engine.room_config("room")

    async def test_heat_requires_room_sun_presence(self):
        engine, _ = await self._make_heat_engine()
        self.hass.states.values["sensor.lux"] = FakeState("1000", unit_of_measurement="lx")
        await engine.async_evaluate_all("test_heat_without_sun")
        self.assertFalse(engine.rooms["room"].heat_active)
        self.assertNotEqual(engine.rooms["room"].mode, "heat")

    async def test_external_confirmation_can_start_heat_protection(self):
        engine, room = await self._make_heat_engine()
        sector = room["sectors"][0]
        sector.update({
            "sun_source": "external",
            "sun_presence_entity": "binary_sensor.facade_sun",
            "lux_sensor": "",
        })
        self.hass.states.values["binary_sensor.facade_sun"] = FakeState("on")

        await engine.async_evaluate_all("test_external_sun_for_heat")

        self.assertTrue(engine.rooms["room"].heat_active)
        self.assertEqual(engine.rooms["room"].mode, "heat")

    async def test_one_active_sector_enables_heat_for_whole_room(self):
        engine, _ = await self._make_heat_engine(two_sectors=True)
        self.hass.states.values["sensor.lux"] = FakeState("1000", unit_of_measurement="lx")
        self.hass.states.values["sensor.lux_east"] = FakeState("20000", unit_of_measurement="lx")
        await engine.async_evaluate_all("test_one_sector_with_sun")
        self.assertTrue(engine.rooms["room"].heat_active)
        self.assertEqual(engine.rooms["room"].mode, "heat")

    async def test_heat_stays_latched_when_last_active_sector_turns_off(self):
        engine, _ = await self._make_heat_engine(two_sectors=True)
        self.hass.states.values["sensor.lux"] = FakeState("1000", unit_of_measurement="lx")
        self.hass.states.values["sensor.lux_east"] = FakeState("20000", unit_of_measurement="lx")
        await engine.async_evaluate_all("test_heat_start")
        self.assertTrue(engine.rooms["room"].heat_active)

        self.hass.states.values["sensor.lux_east"] = FakeState("1000", unit_of_measurement="lx")
        await engine.async_evaluate_all("test_last_sector_off")
        self.assertTrue(engine.rooms["room"].heat_active)
        self.assertEqual(engine.rooms["room"].mode, "heat")

    async def test_heat_stays_active_while_another_sector_has_sun(self):
        engine, _ = await self._make_heat_engine(two_sectors=True)
        self.hass.states.values["sensor.lux"] = FakeState("20000", unit_of_measurement="lx")
        self.hass.states.values["sensor.lux_east"] = FakeState("20000", unit_of_measurement="lx")
        await engine.async_evaluate_all("test_both_sectors_on")
        self.assertTrue(engine.rooms["room"].heat_active)

        self.hass.states.values["sensor.lux"] = FakeState("1000", unit_of_measurement="lx")
        await engine.async_evaluate_all("test_one_sector_off")
        self.assertTrue(engine.rooms["room"].heat_active)
        self.assertEqual(engine.rooms["room"].mode, "heat")

    async def test_disabled_sector_does_not_enable_heat(self):
        engine, room = await self._make_heat_engine(two_sectors=True)
        room["sectors"][1]["enabled"] = False
        self.hass.states.values["sensor.lux"] = FakeState("1000", unit_of_measurement="lx")
        self.hass.states.values["sensor.lux_east"] = FakeState("20000", unit_of_measurement="lx")
        await engine.async_evaluate_all("test_disabled_sector")
        self.assertFalse(engine.rooms["room"].heat_active)

    async def test_heat_without_sun_requirement_keeps_temperature_only_behavior(self):
        engine, _ = await self._make_heat_engine(requires_sun=False)
        self.hass.states.values["sensor.lux"] = FakeState("1000", unit_of_measurement="lx")
        await engine.async_evaluate_all("test_temperature_only_heat")
        self.assertTrue(engine.rooms["room"].heat_active)
        self.assertEqual(engine.rooms["room"].mode, "heat")

    async def test_unavailable_lux_cannot_start_heat_but_does_not_release_latched_heat(self):
        engine, _ = await self._make_heat_engine()
        self.hass.states.values["sensor.lux"] = FakeState("unavailable")
        await engine.async_evaluate_all("test_unavailable_before_start")
        self.assertFalse(engine.rooms["room"].heat_active)

        self.hass.states.values["sensor.lux"] = FakeState("20000", unit_of_measurement="lx")
        await engine.async_evaluate_all("test_valid_sun")
        self.assertTrue(engine.rooms["room"].heat_active)

        self.hass.states.values["sensor.lux"] = FakeState("unavailable")
        await engine.async_evaluate_all("test_unavailable_after_start")
        self.assertTrue(engine.rooms["room"].heat_active)

    async def test_heat_stays_latched_when_indoor_temperature_falls(self):
        engine, _ = await self._make_heat_engine()
        self.hass.states.values["sensor.lux"] = FakeState("20000", unit_of_measurement="lx")
        await engine.async_evaluate_all("test_heat_start")
        self.assertTrue(engine.rooms["room"].heat_active)

        self.hass.states.values["sensor.indoor"] = FakeState("20", unit_of_measurement="°C")
        await engine.async_evaluate_all("test_temperature_fell")
        self.assertTrue(engine.rooms["room"].heat_active)
        self.assertEqual(engine.rooms["room"].mode, "heat")

    async def test_outdoor_minimum_is_required_to_start_heat(self):
        engine, room = await self._make_heat_engine()
        room.update({
            "outdoor_temperature": "sensor.outdoor",
            "outdoor_minimum": 18.0,
        })
        self.hass.states.values["sensor.lux"] = FakeState("20000", unit_of_measurement="lx")
        self.hass.states.values["sensor.outdoor"] = FakeState("12", unit_of_measurement="°C")
        await engine.async_evaluate_all("test_outdoor_too_cold")
        self.assertFalse(engine.rooms["room"].heat_active)

        self.hass.states.values["sensor.outdoor"] = FakeState("22", unit_of_measurement="°C")
        await engine.async_evaluate_all("test_outdoor_warm")
        self.assertTrue(engine.rooms["room"].heat_active)

    async def test_schedule_is_required_when_heat_outside_schedule_is_disabled(self):
        engine, room = await self._make_heat_engine()
        now = datetime.now(timezone.utc)
        room.update({
            "schedule_enabled": True,
            "active_months": [1 if now.month != 1 else 2],
            "heat_outside_schedule": False,
        })
        self.hass.states.values["sensor.lux"] = FakeState("20000", unit_of_measurement="lx")
        await engine.async_evaluate_all("test_schedule_blocked")
        self.assertFalse(engine.rooms["room"].heat_active)

    async def test_evening_release_finishes_heat_for_the_day(self):
        engine, _ = await self._make_heat_engine()
        self.hass.states.values["sensor.lux"] = FakeState("20000", unit_of_measurement="lx")
        engine._evening_release_reached = lambda _room, _now: True
        await engine.async_evaluate_all("test_evening_release")
        self.assertFalse(engine.rooms["room"].heat_active)
        self.assertTrue(engine.rooms["room"].finished_today)
        self.assertEqual(engine.rooms["room"].mode, "open")

        await engine.async_evaluate_all("test_no_second_cycle")
        self.assertFalse(engine.rooms["room"].heat_active)
        self.assertTrue(engine.rooms["room"].finished_today)

    async def test_advanced_night_entity_moves_directly_to_knx_night_target(self):
        config = base_config()
        config["advanced_mode"] = True
        room = config["rooms"][0]
        room.update({
            "night_enabled": True,
            "night_source": "entity",
            "night_entity": "schedule.night",
        })
        self.hass.states.values["schedule.night"] = FakeState("on")
        self.hass.states.values["cover.one"] = FakeState(
            "open", current_position=100, current_tilt_position=0
        )
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()

        await engine.async_evaluate_all("night_started")

        self.assertEqual(engine.rooms["room"].mode, "night")
        commands = [call for call in self.hass.services.calls if call[0] == "cover"]
        self.assertTrue(any(call[2].get("position") == 0 for call in commands))
        # Venetian profiles deliberately sequence height before slat tilt. The
        # second step is persisted for the configured settling boundary rather
        # than being dispatched in the same service turn.
        self.assertTrue(
            any(
                step.axis == "tilt" and step.target == 100
                for step in engine.command_planner.pending_steps
            )
        )

    async def test_basic_mode_ignores_stored_night_configuration(self):
        config = base_config()
        config["advanced_mode"] = False
        room = config["rooms"][0]
        room.update({
            "night_enabled": True,
            "night_source": "entity",
            "night_entity": "schedule.night",
        })
        self.hass.states.values["schedule.night"] = FakeState("on")
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()

        await engine.async_evaluate_all("basic_mode")

        self.assertNotEqual(engine.rooms["room"].mode, "night")
        self.assertFalse(engine.rooms["room"].night_active)

    async def test_unavailable_night_source_holds_cover_position(self):
        config = base_config()
        config["advanced_mode"] = True
        room = config["rooms"][0]
        room.update({
            "night_enabled": True,
            "night_source": "entity",
            "night_entity": "schedule.night",
        })
        self.hass.states.values["schedule.night"] = FakeState("unavailable")
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()

        await engine.async_evaluate_all("night_unavailable")

        self.assertTrue(engine.rooms["room"].night_blocked)
        self.assertEqual(engine.rooms["room"].mode, "idle")
        self.assertFalse(any(call[0] == "cover" for call in self.hass.services.calls))

    async def test_night_end_hands_directly_to_solar_without_open_target(self):
        config = base_config()
        config["advanced_mode"] = True
        room = config["rooms"][0]
        room.update({
            "night_enabled": True,
            "night_source": "entity",
            "night_entity": "schedule.night",
        })
        room["sectors"][0]["lux_sensor"] = ""
        self.hass.states.values["schedule.night"] = FakeState("on")
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()
        await engine.async_evaluate_all("night_active")
        self.hass.services.calls.clear()
        self.hass.states.values["cover.one"] = FakeState(
            "closed", current_position=0, current_tilt_position=100
        )
        self.hass.states.values["schedule.night"] = FakeState("off")

        await engine.async_evaluate_all("night_ended")

        self.assertEqual(engine.rooms["room"].mode, "solar")
        position_targets = [
            call[2].get("position")
            for call in self.hass.services.calls
            if call[0] == "cover" and "position" in call[2]
        ]
        self.assertNotIn(100, position_targets)

    async def test_morning_transition_opens_after_conditions_miss_window(self):
        config = base_config()
        config["advanced_mode"] = True
        room = config["rooms"][0]
        room.update({
            "night_enabled": True,
            "night_source": "entity",
            "night_entity": "schedule.night",
            "night_morning_transition_minutes": 10,
            "indoor_temperature": "sensor.indoor",
        })
        self.hass.states.values["sensor.indoor"] = FakeState(
            "20", unit_of_measurement="°C"
        )
        self.hass.states.values["schedule.night"] = FakeState("on")
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()
        await engine.async_evaluate_all("night_active")
        self.hass.states.values["schedule.night"] = FakeState("off")
        morning = datetime.now(timezone.utc)

        await engine._evaluate_room(room, morning)

        runtime = engine.rooms["room"]
        self.assertEqual(runtime.mode, "idle")
        self.assertTrue(runtime.night_morning_handover_pending)

        await engine._evaluate_room(room, morning + timedelta(minutes=11))

        self.assertEqual(runtime.mode, "open")
        self.assertFalse(runtime.night_morning_handover_pending)
        self.assertIsNone(runtime.night_morning_hold_until)

    async def test_next_night_end_pause_releases_but_manual_pause_does_not(self):
        config = base_config()
        config["advanced_mode"] = True
        room = config["rooms"][0]
        room.update({
            "night_enabled": True,
            "night_source": "entity",
            "night_entity": "schedule.night",
        })
        self.hass.states.values["schedule.night"] = FakeState("off")
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()
        await engine.async_evaluate_all("day")
        await engine.async_set_pause_mode("room", "next_night_end")
        self.assertTrue(engine.rooms["room"].pause_waiting_for_night)

        self.hass.states.values["schedule.night"] = FakeState("on")
        await engine.async_evaluate_all("night_started")
        self.assertFalse(engine.rooms["room"].pause_waiting_for_night)
        self.hass.states.values["schedule.night"] = FakeState("off")
        await engine.async_evaluate_all("night_ended")
        self.assertEqual(engine.rooms["room"].pause_mode, "auto")

        await engine.async_set_pause_mode("room", "manual")
        self.hass.states.values["schedule.night"] = FakeState("on")
        await engine.async_evaluate_all("second_night")
        self.hass.states.values["schedule.night"] = FakeState("off")
        await engine.async_evaluate_all("second_morning")
        self.assertEqual(engine.rooms["room"].pause_mode, "manual")

    async def test_unavailable_night_pause_falls_back_to_next_morning(self):
        config = base_config()
        room = config["rooms"][0]
        room.update({
            "night_enabled": True,
            "night_source": "entity",
            "night_entity": "schedule.night",
        })
        self.hass.states.values["schedule.night"] = FakeState("unavailable")
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()

        await engine.async_set_pause_mode("room", "next_night_end")

        runtime = engine.rooms["room"]
        self.assertEqual(runtime.pause_mode, "next_sunrise")
        self.assertIsNotNone(runtime.pause_until)
        self.assertFalse(runtime.pause_waiting_for_night)

    async def test_disabled_night_pause_falls_back_to_next_morning(self):
        config = base_config()
        config["rooms"][0]["night_enabled"] = False
        engine = engine_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()

        await engine.async_set_pause_mode("room", "next_night_end")

        runtime = engine.rooms["room"]
        self.assertEqual(runtime.pause_mode, "next_sunrise")
        self.assertIsNotNone(runtime.pause_until)
        self.assertFalse(runtime.pause_waiting_for_night)

    async def test_reload_rehomes_orphaned_night_end_room_and_cover_pauses(self):
        for night_values, source_state in (
            ({"night_enabled": False}, None),
            (
                {
                    "night_enabled": True,
                    "night_source": "entity",
                    "night_entity": "schedule.night",
                },
                "unavailable",
            ),
        ):
            with self.subTest(night_values=night_values):
                config = base_config()
                config["rooms"][0].update(night_values)
                if source_state is not None:
                    self.hass.states.values["schedule.night"] = FakeState(
                        source_state
                    )
                else:
                    self.hass.states.values.pop("schedule.night", None)
                engine = engine_mod.SmartShadingEngine(
                    self.hass, FakeEntry(config)
                )
                engine.store._store.value = {
                    "runtime_schema": 3,
                    "room_runtime": {
                        "room": {
                            "pause_mode": "next_night_end",
                            "pause_until": None,
                            "pause_waiting_for_night": True,
                        }
                    },
                    "cover_runtime": {
                        "cover_one": {
                            "active": True,
                            "until": None,
                            "reason": "external_or_physical_control",
                            "pause_mode": "next_night_end",
                            "waiting_for_night": True,
                        }
                    },
                }

                await engine.async_initialize()

                room_pause = engine.rooms["room"]
                cover_pause = engine.cover_pauses["cover_one"]
                self.assertEqual(room_pause.pause_mode, "next_sunrise")
                self.assertEqual(cover_pause.pause_mode, "next_sunrise")
                self.assertIsNotNone(room_pause.pause_until)
                self.assertEqual(cover_pause.until, room_pause.pause_until)
                self.assertFalse(room_pause.pause_waiting_for_night)
                self.assertFalse(cover_pause.waiting_for_night)
                self.assertIn("room", engine._room_pause_timer_unsubs)
                self.assertIn("cover_one", engine._cover_pause_timer_unsubs)

                saved_room = engine.store.room_runtime("room")
                saved_cover = engine.store.cover_runtime("cover_one")
                self.assertEqual(saved_room["pause_mode"], "next_sunrise")
                self.assertEqual(saved_cover["pause_mode"], "next_sunrise")
                self.assertIsNotNone(saved_room["pause_until"])
                self.assertEqual(saved_cover["until"], saved_room["pause_until"])
                self.assertFalse(saved_room["pause_waiting_for_night"])
                self.assertFalse(saved_cover["waiting_for_night"])

    async def test_room_sun_transition_triggers_immediate_heat_evaluation(self):
        engine, _ = await self._make_heat_engine()
        self.hass.states.values["sensor.lux"] = FakeState("1000", unit_of_measurement="lx")
        await engine._update_sun_presence(engine.sector_config("south"), datetime.now(timezone.utc))
        calls = []

        async def fake_evaluate(trigger):
            calls.append(trigger)

        engine.async_evaluate_all = fake_evaluate
        old_state = self.hass.states.values["sensor.lux"]
        new_state = FakeState("20000", unit_of_measurement="lx")
        self.hass.states.values["sensor.lux"] = new_state
        await engine._async_state_changed(FakeEvent("sensor.lux", old_state, new_state))
        self.assertEqual(calls, ["heat_sun_presence:room:south"])



if __name__ == "__main__":
    unittest.main()
