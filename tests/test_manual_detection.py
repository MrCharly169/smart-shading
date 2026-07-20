from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest

from test_engine_runtime import (
    COMP,
    FakeEntry,
    FakeEvent,
    FakeHass,
    FakeState,
    _load,
    base_config,
)

# engine.py is already loaded by test_engine_runtime. Load the two production
# modules that wrap the baseline engine for the real integration runtime.
manual_mod = _load(
    "custom_components.smart_shading.manual_detection",
    COMP / "manual_detection.py",
)
controller_mod = _load(
    "custom_components.smart_shading.controller",
    COMP / "controller.py",
)
models_mod = sys.modules["custom_components.smart_shading.models"]


class ManualDetectionRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        self.values = {
            "sun.sun": FakeState(
                "above_horizon",
                azimuth=180,
                elevation=35,
                next_rising=tomorrow.isoformat(),
                next_setting=tomorrow.isoformat(),
            ),
            "sensor.lux": FakeState("26398.72", unit_of_measurement="lx"),
            "cover.one": FakeState(
                "open", current_position=100, current_tilt_position=100
            ),
            "switch.cover_lock": FakeState("off"),
        }
        self.hass = FakeHass(self.values)
        self.engine = controller_mod.SmartShadingEngine(
            self.hass, FakeEntry(base_config())
        )
        await self.engine.async_initialize()

    def _configure_window_return(self, *, enabled: bool = True):
        cover = self.engine.config["rooms"][0]["sectors"][0]["layers"][0][
            "covers"
        ][0]
        cover["window"] = "binary_sensor.window"
        cover["window_safe_state"] = "on"
        cover["window_policy"] = "block_closing"
        cover["window_returns_to_automation"] = enabled
        self.hass.states.values["binary_sensor.window"] = FakeState("on")
        self.engine._rebuild_runtime()
        return cover

    async def _window_transition(self, old_value: str, new_value: str) -> None:
        old_state = FakeState(old_value)
        new_state = FakeState(new_value)
        self.hass.states.values["binary_sensor.window"] = new_state
        await self.engine._async_state_changed(
            FakeEvent("binary_sensor.window", old_state, new_state)
        )

    async def test_external_cover_movement_pauses_by_default(self):
        first = FakeState("open", current_position=100, current_tilt_position=100)
        second = FakeState("closing", current_position=70, current_tilt_position=100)
        third = FakeState("closing", current_position=40, current_tilt_position=100)
        settled = FakeState("open", current_position=40, current_tilt_position=100)
        await self.engine._async_state_changed(FakeEvent("cover.one", first, second))
        await self.engine._async_state_changed(FakeEvent("cover.one", second, third))
        self.assertFalse(self.engine.cover_pauses["cover_one"].active)
        await self.engine._async_state_changed(FakeEvent("cover.one", third, settled))
        self.assertTrue(self.engine.cover_pauses["cover_one"].active)
        self.assertEqual(self.hass.states.get("switch.cover_lock").state, "on")

    async def test_external_lock_remains_immediate_and_authoritative(self):
        await self.engine._async_state_changed(
            FakeEvent("switch.cover_lock", FakeState("off"), FakeState("on"))
        )
        self.assertTrue(self.engine.cover_pauses["cover_one"].active)
        self.assertEqual(
            self.engine.cover_pauses["cover_one"].reason,
            "manual_lock_entity",
        )
        calls = []

        async def fake_evaluate(trigger):
            calls.append(trigger)

        self.engine.async_evaluate_all = fake_evaluate
        await self.engine._async_state_changed(
            FakeEvent("switch.cover_lock", FakeState("on"), FakeState("off"))
        )
        self.assertFalse(self.engine.cover_pauses["cover_one"].active)
        self.assertEqual(len(calls), 1)

    async def test_single_update_is_only_possible_external_by_default(self):
        first = FakeState("open", current_position=100, current_tilt_position=100)
        second = FakeState("closing", current_position=70, current_tilt_position=100)
        await self.engine._async_state_changed(FakeEvent("cover.one", first, second))
        self.assertFalse(self.engine.cover_pauses["cover_one"].active)
        self.assertEqual(
            self.engine.cover_motion["cover.one"].phase,
            "possible_external",
        )

    async def test_knx_feedback_after_twenty_seconds_confirms_external_move(self):
        first = FakeState("open", current_position=100, current_tilt_position=100)
        second = FakeState("closing", current_position=70, current_tilt_position=100)
        third = FakeState("closing", current_position=40, current_tilt_position=100)
        settled = FakeState("open", current_position=40, current_tilt_position=100)

        await self.engine._async_state_changed(FakeEvent("cover.one", first, second))
        observation = self.engine.cover_motion["cover.one"]
        observation.candidate_started_at -= timedelta(seconds=20)
        await self.engine._async_state_changed(FakeEvent("cover.one", second, third))
        await self.engine._async_state_changed(FakeEvent("cover.one", third, settled))

        self.assertTrue(self.engine.cover_pauses["cover_one"].active)
        self.assertEqual(self.hass.states.get("switch.cover_lock").state, "on")

    async def test_legacy_opt_out_still_ignores_external_cover_updates(self):
        self.engine.config[manual_mod.CONF_EXTERNAL_MOVEMENT_DETECTION] = False
        first = FakeState("open", current_position=100, current_tilt_position=100)
        second = FakeState("closing", current_position=70, current_tilt_position=100)
        third = FakeState("closing", current_position=40, current_tilt_position=100)

        await self.engine._async_state_changed(FakeEvent("cover.one", first, second))
        await self.engine._async_state_changed(FakeEvent("cover.one", second, third))

        self.assertFalse(self.engine.cover_pauses["cover_one"].active)
        self.assertEqual(self.hass.states.get("switch.cover_lock").state, "off")

    async def test_second_consistent_update_confirms_only_that_cover(self):
        config = base_config()
        config[manual_mod.CONF_EXTERNAL_MOVEMENT_DETECTION] = True
        covers = config["rooms"][0]["sectors"][0]["layers"][0]["covers"]
        covers.append(
            {
                **covers[0],
                "id": "cover_two",
                "entity": "cover.two",
                "name": "Cover two",
                "short": "C2",
                "lock": "switch.cover_two_lock",
            }
        )
        self.values["cover.two"] = FakeState(
            "open", current_position=100, current_tilt_position=100
        )
        self.values["switch.cover_two_lock"] = FakeState("off")
        engine = controller_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()

        first = FakeState("open", current_position=100, current_tilt_position=100)
        second = FakeState("closing", current_position=70, current_tilt_position=100)
        third = FakeState("closing", current_position=40, current_tilt_position=100)
        settled = FakeState("open", current_position=40, current_tilt_position=100)
        await engine._async_state_changed(FakeEvent("cover.one", first, second))
        await engine._async_state_changed(FakeEvent("cover.one", second, third))
        await engine._async_state_changed(FakeEvent("cover.one", third, settled))

        self.assertTrue(engine.cover_pauses["cover_one"].active)
        self.assertFalse(engine.cover_pauses["cover_two"].active)
        self.assertEqual(self.hass.states.get("switch.cover_lock").state, "on")
        self.assertEqual(self.hass.states.get("switch.cover_two_lock").state, "off")

    async def test_simultaneous_single_refreshes_never_pause_multiple_covers(self):
        config = base_config()
        config[manual_mod.CONF_EXTERNAL_MOVEMENT_DETECTION] = True
        covers = config["rooms"][0]["sectors"][0]["layers"][0]["covers"]
        covers.append(
            {
                **covers[0],
                "id": "cover_two",
                "entity": "cover.two",
                "name": "Cover two",
                "short": "C2",
                "lock": "switch.cover_two_lock",
            }
        )
        self.values["cover.two"] = FakeState(
            "open", current_position=100, current_tilt_position=100
        )
        self.values["switch.cover_two_lock"] = FakeState("off")
        engine = controller_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()

        for entity_id in ("cover.one", "cover.two"):
            await engine._async_state_changed(
                FakeEvent(
                    entity_id,
                    FakeState(
                        "open", current_position=100, current_tilt_position=100
                    ),
                    FakeState(
                        "closing", current_position=70, current_tilt_position=100
                    ),
                )
            )
        self.assertFalse(engine.cover_pauses["cover_one"].active)
        self.assertFalse(engine.cover_pauses["cover_two"].active)

    async def test_unavailable_recovery_only_reseeds_baseline(self):
        self.engine.config[manual_mod.CONF_EXTERNAL_MOVEMENT_DETECTION] = True
        await self.engine._async_state_changed(
            FakeEvent(
                "cover.one",
                FakeState("unavailable"),
                FakeState("open", current_position=75, current_tilt_position=100),
            )
        )
        self.assertFalse(self.engine.cover_pauses["cover_one"].active)
        self.assertEqual(self.engine.cover_motion["cover.one"].phase, "idle")

    async def test_identical_and_attribute_only_updates_are_ignored(self):
        self.engine.config[manual_mod.CONF_EXTERNAL_MOVEMENT_DETECTION] = True
        await self.engine._async_state_changed(
            FakeEvent(
                "cover.one",
                FakeState(
                    "open", current_position=100, current_tilt_position=100, battery=90
                ),
                FakeState(
                    "open", current_position=100, current_tilt_position=100, battery=89
                ),
            )
        )
        self.assertFalse(self.engine.cover_pauses["cover_one"].active)
        self.assertIsNone(
            self.engine.cover_motion["cover.one"].candidate_direction
        )

    async def test_state_only_opening_and_closing_are_informational(self):
        await self.engine._async_state_changed(
            FakeEvent(
                "cover.one",
                FakeState("open", current_position=100, current_tilt_position=100),
                FakeState("closing", current_position=100, current_tilt_position=100),
            )
        )
        await self.engine._async_state_changed(
            FakeEvent(
                "cover.one",
                FakeState("closing", current_position=100, current_tilt_position=100),
                FakeState("closed", current_position=100, current_tilt_position=100),
            )
        )

        observation = self.engine.cover_motion["cover.one"]
        self.assertFalse(self.engine.cover_pauses["cover_one"].active)
        self.assertEqual(observation.phase, "idle")
        self.assertIsNone(observation.candidate_direction)
        self.assertEqual(observation.last_decision_reason, "state_only_change_ignored")

    async def test_candidate_return_to_baseline_is_rejected(self):
        first = FakeState("open", current_position=100, current_tilt_position=100)
        away = FakeState("closing", current_position=70, current_tilt_position=100)
        baseline = FakeState("open", current_position=100, current_tilt_position=100)

        await self.engine._async_state_changed(FakeEvent("cover.one", first, away))
        await self.engine._async_state_changed(FakeEvent("cover.one", away, baseline))

        observation = self.engine.cover_motion["cover.one"]
        self.assertFalse(self.engine.cover_pauses["cover_one"].active)
        self.assertEqual(observation.phase, "idle")
        self.assertIsNone(observation.candidate_direction)
        self.assertEqual(
            observation.last_decision_reason,
            "external_candidate_returned_to_baseline",
        )

    async def test_tilt_only_feedback_requires_progress_and_stability(self):
        first = FakeState("open", current_position=100, current_tilt_position=100)
        second = FakeState("open", current_position=100, current_tilt_position=70)
        third = FakeState("open", current_position=100, current_tilt_position=40)
        settled = FakeState("open", current_position=100, current_tilt_position=40)

        await self.engine._async_state_changed(FakeEvent("cover.one", first, second))
        await self.engine._async_state_changed(FakeEvent("cover.one", second, third))
        self.assertFalse(self.engine.cover_pauses["cover_one"].active)
        await self.engine._async_state_changed(FakeEvent("cover.one", third, settled))

        self.assertTrue(self.engine.cover_pauses["cover_one"].active)
        self.assertEqual(self.hass.states.get("switch.cover_lock").state, "on")

    async def test_cover_without_numeric_feedback_uses_manual_entity_only(self):
        await self.engine._async_state_changed(
            FakeEvent("cover.one", FakeState("open"), FakeState("closing"))
        )
        await self.engine._async_state_changed(
            FakeEvent("cover.one", FakeState("closing"), FakeState("closed"))
        )

        self.assertFalse(self.engine.cover_pauses["cover_one"].active)
        self.assertEqual(self.hass.states.get("switch.cover_lock").state, "off")

    async def test_direction_reversal_restarts_confirmation(self):
        self.engine.config[manual_mod.CONF_EXTERNAL_MOVEMENT_DETECTION] = True
        first = FakeState("open", current_position=100, current_tilt_position=100)
        second = FakeState("closing", current_position=70, current_tilt_position=100)
        reverse = FakeState("opening", current_position=80, current_tilt_position=100)
        await self.engine._async_state_changed(FakeEvent("cover.one", first, second))
        await self.engine._async_state_changed(FakeEvent("cover.one", second, reverse))
        self.assertFalse(self.engine.cover_pauses["cover_one"].active)
        self.assertEqual(
            self.engine.cover_motion["cover.one"].candidate_direction,
            "opening",
        )

    async def test_own_command_feedback_never_becomes_external_candidate(self):
        self.engine.config[manual_mod.CONF_EXTERNAL_MOVEMENT_DETECTION] = True
        now = datetime.now(timezone.utc)
        self.engine.command_memory["cover.one"] = models_mod.CommandMemory(
            position=100,
            position_at=now,
            tilt=100,
            tilt_at=now,
            last_activity_at=now,
        )
        self.engine._begin_own_command_session(
            "cover.one", "position", 100.0, now
        )
        await self.engine._async_state_changed(
            FakeEvent(
                "cover.one",
                FakeState(
                    "opening", current_position=0, current_tilt_position=100
                ),
                FakeState(
                    "opening", current_position=40, current_tilt_position=100
                ),
            )
        )
        self.assertFalse(self.engine.cover_pauses["cover_one"].active)
        self.assertEqual(self.engine.cover_motion["cover.one"].phase, "own_command")

    async def test_delayed_non_monotonic_knx_feedback_stays_owned(self):
        now = datetime.now(timezone.utc)
        self.engine._begin_own_command_session(
            "cover.one", "tilt", 35.0, now
        )

        first = self.engine._classify_confirmed_cover_change(
            self.engine.config["rooms"][0],
            "cover.one",
            FakeState("open", current_position=100, current_tilt_position=100),
            FakeState("open", current_position=97, current_tilt_position=70),
            now + timedelta(seconds=20),
        )
        second = self.engine._classify_confirmed_cover_change(
            self.engine.config["rooms"][0],
            "cover.one",
            FakeState("open", current_position=97, current_tilt_position=70),
            FakeState("open", current_position=95, current_tilt_position=50),
            now + timedelta(seconds=60),
        )

        self.assertTrue(first.expected)
        self.assertTrue(second.expected)
        self.assertFalse(first.manual)
        self.assertFalse(second.manual)
        self.assertEqual(first.reason, "active_own_command_session")
        self.assertEqual(self.engine.cover_motion["cover.one"].phase, "own_command")
        self.assertFalse(self.engine.cover_pauses["cover_one"].active)

    async def test_settled_own_session_releases_later_external_feedback(self):
        now = datetime.now(timezone.utc)
        self.engine._begin_own_command_session(
            "cover.one", "tilt", 35.0, now
        )
        room = self.engine.config["rooms"][0]

        reached = self.engine._classify_confirmed_cover_change(
            room,
            "cover.one",
            FakeState("open", current_position=100, current_tilt_position=50),
            FakeState("open", current_position=100, current_tilt_position=35),
            now + timedelta(seconds=20),
        )
        settled = self.engine._classify_confirmed_cover_change(
            room,
            "cover.one",
            FakeState("open", current_position=100, current_tilt_position=35),
            FakeState("open", current_position=100, current_tilt_position=35),
            now + timedelta(seconds=51),
        )
        first_external = self.engine._classify_confirmed_cover_change(
            room,
            "cover.one",
            FakeState("open", current_position=100, current_tilt_position=35),
            FakeState("open", current_position=100, current_tilt_position=55),
            now + timedelta(seconds=52),
        )
        confirmed_external = self.engine._classify_confirmed_cover_change(
            room,
            "cover.one",
            FakeState("open", current_position=100, current_tilt_position=55),
            FakeState("open", current_position=100, current_tilt_position=75),
            now + timedelta(seconds=72),
        )
        stable_external = self.engine._classify_confirmed_cover_change(
            room,
            "cover.one",
            FakeState("open", current_position=100, current_tilt_position=75),
            FakeState("open", current_position=100, current_tilt_position=75),
            now + timedelta(seconds=73),
        )

        self.assertTrue(reached.expected)
        self.assertFalse(settled.changed)
        self.assertNotIn("cover.one", self.engine.own_command_sessions)
        self.assertFalse(first_external.manual)
        self.assertFalse(confirmed_external.manual)
        self.assertTrue(stable_external.manual)

    async def test_own_session_exists_before_cover_service_dispatch(self):
        room = self.engine.config["rooms"][0]
        sector = room["sectors"][0]
        layer = sector["layers"][0]
        cover = layer["covers"][0]
        calls = []
        original_call = self.hass.services.async_call

        async def inspect_call(domain, service, data, blocking=False):
            if domain == "cover":
                session = self.engine.own_command_sessions.get("cover.one")
                self.assertIsNotNone(session)
                if service == "set_cover_position":
                    self.assertTrue(session.position_commanded)
                    self.assertEqual(session.position_target, 0.0)
                if service == "set_cover_tilt_position":
                    self.assertTrue(session.tilt_commanded)
                    self.assertEqual(session.tilt_target, 35.0)
                calls.append(service)
            await original_call(domain, service, data, blocking=blocking)

        self.hass.services.async_call = inspect_call
        await self.engine._apply_cover(
            room,
            sector,
            layer,
            cover,
            self.engine.rooms["room"],
            "solar",
            0.0,
            35.0,
            "test",
        )

        self.assertEqual(
            calls, ["set_cover_position", "set_cover_tilt_position"]
        )

    async def test_explicit_ha_command_overrides_active_own_session(self):
        now = datetime.now(timezone.utc)
        self.engine._begin_own_command_session(
            "cover.one", "position", 0.0, now
        )
        await self.engine._async_cover_service_called(
            SimpleNamespace(
                data={
                    "domain": "cover",
                    "service": "set_cover_position",
                    "service_data": {
                        "entity_id": "cover.one",
                        "position": 50,
                    },
                },
                context=SimpleNamespace(
                    id="external-context",
                    user_id="user-id",
                    parent_id=None,
                ),
            )
        )
        self.engine._manual_service_intents()[
            "cover.one"
        ].created_at -= timedelta(seconds=20)
        await self.engine._async_state_changed(
            FakeEvent(
                "cover.one",
                FakeState("open", current_position=100, current_tilt_position=100),
                FakeState("closing", current_position=80, current_tilt_position=100),
            )
        )

        self.assertTrue(self.engine.cover_pauses["cover_one"].active)
        self.assertNotIn("cover.one", self.engine.own_command_sessions)
        self.assertEqual(
            self.engine.cover_pauses["cover_one"].reason,
            "home_assistant_manual_service",
        )

    async def test_confirmed_external_move_during_safety_rechecks_immediately(self):
        config = base_config()
        config[manual_mod.CONF_EXTERNAL_MOVEMENT_DETECTION] = True
        config["rooms"][0]["safety_blockers"] = ["binary_sensor.wind"]
        self.values["binary_sensor.wind"] = FakeState("on")
        engine = controller_mod.SmartShadingEngine(self.hass, FakeEntry(config))
        await engine.async_initialize()
        calls = []

        async def fake_evaluate(trigger):
            calls.append(trigger)

        engine.async_evaluate_all = fake_evaluate
        first = FakeState("open", current_position=100, current_tilt_position=100)
        second = FakeState("closing", current_position=70, current_tilt_position=100)
        third = FakeState("closing", current_position=40, current_tilt_position=100)
        settled = FakeState("open", current_position=40, current_tilt_position=100)
        await engine._async_state_changed(FakeEvent("cover.one", first, second))
        self.assertEqual(calls, [])
        await engine._async_state_changed(FakeEvent("cover.one", second, third))
        self.assertFalse(engine.cover_pauses["cover_one"].active)
        await engine._async_state_changed(FakeEvent("cover.one", third, settled))
        self.assertTrue(engine.cover_pauses["cover_one"].active)
        self.assertEqual(calls, ["safety_manual_cover:cover.one"])

    async def test_window_open_and_close_movements_do_not_pause_cover(self):
        self._configure_window_return()
        evaluations = []

        async def fake_evaluate(trigger):
            evaluations.append(trigger)

        self.engine.async_evaluate_all = fake_evaluate
        await self._window_transition("on", "off")
        await self.engine._async_state_changed(
            FakeEvent(
                "cover.one",
                FakeState("open", current_position=90, current_tilt_position=100),
                FakeState("opening", current_position=96, current_tilt_position=100),
            )
        )
        await self.engine._async_state_changed(
            FakeEvent(
                "cover.one",
                FakeState("opening", current_position=96, current_tilt_position=100),
                FakeState("open", current_position=100, current_tilt_position=100),
            )
        )

        await self._window_transition("off", "on")
        await self.engine._async_state_changed(
            FakeEvent(
                "cover.one",
                FakeState("open", current_position=100, current_tilt_position=100),
                FakeState("closing", current_position=96, current_tilt_position=100),
            )
        )
        await self.engine._async_state_changed(
            FakeEvent(
                "cover.one",
                FakeState("closing", current_position=96, current_tilt_position=100),
                FakeState("open", current_position=90, current_tilt_position=100),
            )
        )

        self.assertFalse(self.engine.cover_pauses["cover_one"].active)
        self.assertEqual(self.hass.states.get("switch.cover_lock").state, "off")
        self.assertEqual(
            evaluations,
            [
                "critical_state:binary_sensor.window",
                "critical_state:binary_sensor.window",
            ],
        )

    async def test_manual_detection_resumes_after_window_recovery_settles(self):
        self._configure_window_return()

        async def fake_evaluate(_trigger):
            return None

        self.engine.async_evaluate_all = fake_evaluate
        await self._window_transition("on", "off")
        await self._window_transition("off", "on")
        await self.engine._async_state_changed(
            FakeEvent(
                "cover.one",
                FakeState("open", current_position=100, current_tilt_position=100),
                FakeState("open", current_position=90, current_tilt_position=100),
            )
        )
        context = self.engine.window_automation_contexts["cover.one"]
        context.last_feedback_at -= timedelta(seconds=31)

        await self.engine._async_state_changed(
            FakeEvent(
                "cover.one",
                FakeState("open", current_position=90, current_tilt_position=100),
                FakeState("closing", current_position=70, current_tilt_position=100),
            )
        )
        await self.engine._async_state_changed(
            FakeEvent(
                "cover.one",
                FakeState("closing", current_position=70, current_tilt_position=100),
                FakeState("closing", current_position=40, current_tilt_position=100),
            )
        )
        await self.engine._async_state_changed(
            FakeEvent(
                "cover.one",
                FakeState("closing", current_position=40, current_tilt_position=100),
                FakeState("open", current_position=40, current_tilt_position=100),
            )
        )

        self.assertTrue(self.engine.cover_pauses["cover_one"].active)
        self.assertEqual(self.hass.states.get("switch.cover_lock").state, "on")

    async def test_window_close_preserves_explicit_manual_entity_pause(self):
        self._configure_window_return()

        async def fake_evaluate(_trigger):
            return None

        self.engine.async_evaluate_all = fake_evaluate
        await self._window_transition("on", "off")
        self.hass.states.values["switch.cover_lock"] = FakeState("on")
        await self.engine._async_state_changed(
            FakeEvent("switch.cover_lock", FakeState("off"), FakeState("on"))
        )
        await self._window_transition("off", "on")

        pause = self.engine.cover_pauses["cover_one"]
        self.assertTrue(pause.active)
        self.assertEqual(pause.reason, "manual_lock_entity")
        self.assertEqual(self.hass.states.get("switch.cover_lock").state, "on")

    async def test_window_return_can_be_disabled_per_cover(self):
        self.hass.states.values["cover.one"] = FakeState(
            "open", current_position=90, current_tilt_position=100
        )
        self._configure_window_return(enabled=False)

        async def fake_evaluate(_trigger):
            return None

        self.engine.async_evaluate_all = fake_evaluate
        await self._window_transition("on", "off")
        await self.engine._async_state_changed(
            FakeEvent(
                "cover.one",
                FakeState("open", current_position=90, current_tilt_position=100),
                FakeState("opening", current_position=96, current_tilt_position=100),
            )
        )
        await self.engine._async_state_changed(
            FakeEvent(
                "cover.one",
                FakeState("opening", current_position=96, current_tilt_position=100),
                FakeState("open", current_position=100, current_tilt_position=100),
            )
        )
        await self.engine._async_state_changed(
            FakeEvent(
                "cover.one",
                FakeState("open", current_position=100, current_tilt_position=100),
                FakeState("open", current_position=100, current_tilt_position=100),
            )
        )

        self.assertTrue(self.engine.cover_pauses["cover_one"].active)


if __name__ == "__main__":
    unittest.main()
