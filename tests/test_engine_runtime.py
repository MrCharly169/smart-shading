from __future__ import annotations

import importlib.util
from copy import deepcopy
import sys
import types
from pathlib import Path
from datetime import datetime, timedelta, timezone
import unittest

ROOT = Path(__file__).parents[1]
COMP = ROOT / "custom_components" / "smart_shading"


def _install_ha_stubs() -> None:
    ha = types.ModuleType("homeassistant")
    const_mod = types.ModuleType("homeassistant.const")
    const_mod.STATE_ON = "on"
    const_mod.STATE_OFF = "off"
    core_mod = types.ModuleType("homeassistant.core")
    core_mod.HomeAssistant = object

    helpers = types.ModuleType("homeassistant.helpers")
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
            "homeassistant.const": const_mod,
            "homeassistant.core": core_mod,
            "homeassistant.helpers": helpers,
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
for name in ("const", "logic", "models", "storage"):
    _load(f"custom_components.smart_shading.{name}", COMP / f"{name}.py")
engine_mod = _load("custom_components.smart_shading.engine", COMP / "engine.py")
models_mod = sys.modules["custom_components.smart_shading.models"]


class FakeState:
    def __init__(self, state: str, **attrs):
        self.state = state
        self.attributes = attrs


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

    async def async_call(self, domain, service, data, blocking=False):
        self.calls.append((domain, service, dict(data), blocking))
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


class FakeEvent:
    def __init__(self, entity_id, old_state, new_state):
        self.data = {"entity_id": entity_id, "old_state": old_state, "new_state": new_state}


def base_config():
    return {
        "house_name": "Test",
        "sun_entity": "sun.sun",
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
        self.assertEqual(store.data["runtime_schema"], 2)
        self.assertEqual(store.data["room_runtime"]["room"]["suppressed_commands"], 0)
        self.assertEqual(store.data["room_runtime"]["room"]["sent_commands"], 5)
        self.assertTrue(store.data["cover_runtime"]["cover_one"]["active"])

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
        self.assertTrue(calls and calls[-1].startswith("cover_pause_ended:"))

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
            await callbacks[-1](None)
            self.assertEqual(self.hass.states.get("switch.cover_lock").state, "off")
            self.assertFalse(self.engine.cover_pauses["cover_one"].active)
            self.assertEqual(len(calls), 1)
            self.assertTrue(calls[0].startswith("cover_pause_ended:"))
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
        return engine, room

    async def test_heat_requires_room_sun_presence(self):
        engine, _ = await self._make_heat_engine()
        self.hass.states.values["sensor.lux"] = FakeState("1000", unit_of_measurement="lx")
        await engine.async_evaluate_all("test_heat_without_sun")
        self.assertFalse(engine.rooms["room"].heat_active)
        self.assertNotEqual(engine.rooms["room"].mode, "heat")

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
            "active_months": [1 if now.month != 1 else 2],
            "heat_outside_schedule": False,
        })
        self.hass.states.values["sensor.lux"] = FakeState("20000", unit_of_measurement="lx")
        await engine.async_evaluate_all("test_schedule_blocked")
        self.assertFalse(engine.rooms["room"].heat_active)

    async def test_evening_release_finishes_heat_for_the_day(self):
        engine, _ = await self._make_heat_engine()
        self.hass.states.values["sensor.lux"] = FakeState("20000", unit_of_measurement="lx")
        engine._evening_release_reached = lambda now: True
        await engine.async_evaluate_all("test_evening_release")
        self.assertFalse(engine.rooms["room"].heat_active)
        self.assertTrue(engine.rooms["room"].finished_today)
        self.assertEqual(engine.rooms["room"].mode, "finished")

        await engine.async_evaluate_all("test_no_second_cycle")
        self.assertFalse(engine.rooms["room"].heat_active)
        self.assertTrue(engine.rooms["room"].finished_today)

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
