from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import sys
import unittest

from test_engine_runtime import (
    FakeEntry,
    FakeEvent,
    FakeHass,
    FakeState,
    _load,
    base_config,
    COMP,
)

_load(
    "custom_components.smart_shading.manual_detection",
    COMP / "manual_detection.py",
)
controller_mod = _load(
    "custom_components.smart_shading.controller",
    COMP / "controller.py",
)
engine_mod = sys.modules["custom_components.smart_shading.engine"]


class ServiceEvent:
    def __init__(
        self,
        service: str,
        service_data: dict,
        *,
        user_id: str | None = "user-1",
        parent_id: str | None = None,
        context_id: str = "context-1",
    ) -> None:
        self.data = {
            "domain": "cover",
            "service": service,
            "service_data": service_data,
        }
        self.context = SimpleNamespace(
            id=context_id,
            user_id=user_id,
            parent_id=parent_id,
        )


class ManualServiceDetectionTests(unittest.IsolatedAsyncioTestCase):
    async def _engine(self, mode: str = "next_sunrise", **room_values):
        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        values = {
            "sun.sun": FakeState(
                "above_horizon",
                azimuth=180,
                elevation=35,
                next_rising=tomorrow.isoformat(),
                next_setting=(tomorrow + timedelta(hours=8)).isoformat(),
            ),
            "sensor.lux": FakeState("26398.72", unit_of_measurement="lx"),
            "cover.one": FakeState(
                "open", current_position=100, current_tilt_position=100
            ),
            "switch.cover_lock": FakeState("off"),
        }
        config = base_config()
        config["rooms"][0]["default_pause_mode"] = mode
        config["rooms"][0].update(room_values)
        hass = FakeHass(values)
        engine = controller_mod.SmartShadingEngine(hass, FakeEntry(config))
        await engine.async_initialize()
        return hass, engine, tomorrow

    @staticmethod
    def _add_second_cover(hass, engine, *, shared_lock: bool) -> None:
        covers = engine.config["rooms"][0]["sectors"][0]["layers"][0]["covers"]
        covers.append(
            {
                **covers[0],
                "id": "cover_two",
                "entity": "cover.two",
                "name": "Cover two",
                "short": "C2",
                "lock": (
                    "switch.cover_lock"
                    if shared_lock
                    else "switch.cover_two_lock"
                ),
            }
        )
        hass.states.values["cover.two"] = FakeState(
            "open", current_position=100, current_tilt_position=100
        )
        if not shared_lock:
            hass.states.values["switch.cover_two_lock"] = FakeState("off")
        engine._rebuild_runtime()

    async def _position_call_and_feedback(
        self,
        engine,
        *,
        entity_id: str = "cover.one",
        target: int = 40,
        old_position: int = 100,
        new_position: int = 70,
        user_id: str | None = "user-1",
        parent_id: str | None = None,
    ) -> None:
        await engine._async_cover_service_called(
            ServiceEvent(
                "set_cover_position",
                {"entity_id": entity_id, "position": target},
                user_id=user_id,
                parent_id=parent_id,
            )
        )
        await engine._async_state_changed(
            FakeEvent(
                entity_id,
                FakeState(
                    "open",
                    current_position=old_position,
                    current_tilt_position=100,
                ),
                FakeState(
                    "closing",
                    current_position=new_position,
                    current_tilt_position=100,
                ),
            )
        )

    async def test_direct_ha_position_call_waits_for_exact_cover_feedback(self):
        hass, engine, _tomorrow = await self._engine()
        await engine._async_cover_service_called(
            ServiceEvent(
                "set_cover_position",
                {"entity_id": "cover.one", "position": 40},
            )
        )

        self.assertFalse(engine.cover_pauses["cover_one"].active)
        self.assertIn("cover.one", engine._manual_service_intents())

        await engine._async_state_changed(
            FakeEvent(
                "cover.one",
                FakeState("open", current_position=100, current_tilt_position=100),
                FakeState("closing", current_position=70, current_tilt_position=100),
            )
        )
        pause = engine.cover_pauses["cover_one"]
        self.assertTrue(pause.active)
        self.assertEqual(pause.reason, "home_assistant_manual_service")
        self.assertIsNotNone(pause.until)
        self.assertEqual(hass.states.get("switch.cover_lock").state, "on")

    async def test_state_only_feedback_does_not_confirm_manual_service_intent(self):
        hass, engine, _tomorrow = await self._engine()
        await engine._async_cover_service_called(
            ServiceEvent(
                "set_cover_position",
                {"entity_id": "cover.one", "position": 40},
            )
        )
        await engine._async_state_changed(
            FakeEvent(
                "cover.one",
                FakeState("open", current_position=100, current_tilt_position=100),
                FakeState("closing", current_position=100, current_tilt_position=100),
            )
        )

        self.assertFalse(engine.cover_pauses["cover_one"].active)
        self.assertIn("cover.one", engine._manual_service_intents())
        self.assertEqual(hass.states.get("switch.cover_lock").state, "off")

    async def test_multi_target_call_pauses_only_cover_that_really_moves(self):
        hass, engine, _tomorrow = await self._engine()
        room = engine.config["rooms"][0]
        covers = room["sectors"][0]["layers"][0]["covers"]
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
        hass.states.values["cover.two"] = FakeState(
            "open", current_position=100, current_tilt_position=100
        )
        hass.states.values["switch.cover_two_lock"] = FakeState("off")
        engine._rebuild_runtime()

        await engine._async_cover_service_called(
            ServiceEvent(
                "set_cover_position",
                {"entity_id": ["cover.one", "cover.two"], "position": 40},
            )
        )
        await engine._async_state_changed(
            FakeEvent(
                "cover.one",
                FakeState("open", current_position=100, current_tilt_position=100),
                FakeState("closing", current_position=70, current_tilt_position=100),
            )
        )

        self.assertTrue(engine.cover_pauses["cover_one"].active)
        self.assertFalse(engine.cover_pauses["cover_two"].active)
        self.assertEqual(hass.states.get("switch.cover_lock").state, "on")
        self.assertEqual(hass.states.get("switch.cover_two_lock").state, "off")
        self.assertIn("cover.two", engine._manual_service_intents())

    async def test_shared_manual_entity_pauses_whole_room_group_with_one_write(self):
        hass, engine, _tomorrow = await self._engine()
        self._add_second_cover(hass, engine, shared_lock=True)
        hass.services.calls.clear()

        await self._position_call_and_feedback(engine)

        first = engine.cover_pauses["cover_one"]
        second = engine.cover_pauses["cover_two"]
        self.assertTrue(first.active)
        self.assertTrue(second.active)
        self.assertEqual(second.pause_mode, first.pause_mode)
        self.assertEqual(second.until, first.until)
        self.assertEqual(second.started_at, first.started_at)
        self.assertEqual(
            [
                call
                for call in hass.services.calls
                if call[0:2] == ("switch", "turn_on")
            ],
            [
                (
                    "switch",
                    "turn_on",
                    {"entity_id": "switch.cover_lock"},
                    False,
                )
            ],
        )
        self.assertEqual(
            engine.manual_override_groups("room"),
            [
                {
                    "entity_id": "switch.cover_lock",
                    "covers": ["cover.one", "cover.two"],
                    "cover_ids": ["cover_one", "cover_two"],
                    "size": 2,
                }
            ],
        )

    async def test_shared_manual_entity_off_releases_group_once(self):
        _hass, engine, _tomorrow = await self._engine()
        self._add_second_cover(_hass, engine, shared_lock=True)
        await self._position_call_and_feedback(engine)

        # Consume the state acknowledgement for Smart Shading's own ON write.
        await engine._async_state_changed(
            FakeEvent(
                "switch.cover_lock",
                FakeState("off"),
                FakeState("on"),
            )
        )
        calls = []

        async def fake_evaluate(trigger):
            calls.append(trigger)

        engine.async_evaluate_all = fake_evaluate
        await engine._async_state_changed(
            FakeEvent(
                "switch.cover_lock",
                FakeState("on"),
                FakeState("off"),
            )
        )

        self.assertFalse(engine.cover_pauses["cover_one"].active)
        self.assertFalse(engine.cover_pauses["cover_two"].active)
        self.assertNotEqual(engine.cover_motion["cover.one"].phase, "paused")
        self.assertNotEqual(engine.cover_motion["cover.two"].phase, "paused")
        self.assertIsNone(engine.cover_motion["cover.one"].candidate_direction)
        self.assertIsNone(engine.cover_motion["cover.two"].candidate_direction)
        self.assertEqual(calls, ["manual_group_released:switch.cover_lock"])

    async def test_shared_manual_entity_timer_clears_group_once(self):
        hass, engine, _tomorrow = await self._engine()
        self._add_second_cover(hass, engine, shared_lock=True)
        callbacks = []
        original = engine_mod.async_call_later
        engine_mod.async_call_later = lambda _hass, _seconds, callback: (
            callbacks.append(callback) or (lambda: None)
        )
        try:
            await self._position_call_and_feedback(engine)
        finally:
            engine_mod.async_call_later = original

        calls = []

        async def fake_evaluate(trigger):
            calls.append(trigger)

        engine.async_evaluate_all = fake_evaluate
        self.assertEqual(len(callbacks), 2)
        await callbacks[0](datetime.now(timezone.utc))
        await callbacks[1](datetime.now(timezone.utc))

        self.assertFalse(engine.cover_pauses["cover_one"].active)
        self.assertFalse(engine.cover_pauses["cover_two"].active)
        self.assertEqual(hass.states.get("switch.cover_lock").state, "off")
        self.assertEqual(
            calls, ["manual_group_released:switch.cover_lock"]
        )

    async def test_expired_shared_group_is_not_reactivated_by_stale_lock_state(self):
        hass, engine, _tomorrow = await self._engine()
        self._add_second_cover(hass, engine, shared_lock=True)
        expired = datetime.now(timezone.utc) - timedelta(minutes=1)
        for cover_id in ("cover_one", "cover_two"):
            pause = engine.cover_pauses[cover_id]
            pause.active = True
            pause.until = expired
            pause.reason = "external_or_physical_control"
            pause.lock_owned = True
        hass.states.values["switch.cover_lock"] = FakeState("on")
        hass.services.calls.clear()
        original_call = hass.services.async_call

        async def delayed_lock_off(domain, service, data, blocking=False):
            if (
                domain in {"switch", "input_boolean"}
                and service == "turn_off"
                and data.get("entity_id") == "switch.cover_lock"
            ):
                hass.services.calls.append(
                    (domain, service, dict(data), blocking)
                )
                return
            await original_call(domain, service, data, blocking=blocking)

        hass.services.async_call = delayed_lock_off
        await engine._async_sync_configured_locks()

        self.assertFalse(engine.cover_pauses["cover_one"].active)
        self.assertFalse(engine.cover_pauses["cover_two"].active)
        self.assertEqual(hass.states.get("switch.cover_lock").state, "on")
        self.assertEqual(
            len(
                [
                    call
                    for call in hass.services.calls
                    if call[0:2] == ("switch", "turn_off")
                    and call[2].get("entity_id") == "switch.cover_lock"
                ]
            ),
            1,
        )

    async def test_multi_target_call_pauses_second_cover_only_after_its_feedback(self):
        hass, engine, _tomorrow = await self._engine()
        room = engine.config["rooms"][0]
        covers = room["sectors"][0]["layers"][0]["covers"]
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
        hass.states.values["cover.two"] = FakeState(
            "open", current_position=100, current_tilt_position=100
        )
        hass.states.values["switch.cover_two_lock"] = FakeState("off")
        engine._rebuild_runtime()

        await engine._async_cover_service_called(
            ServiceEvent(
                "set_cover_position",
                {"entity_id": ["cover.one", "cover.two"], "position": 40},
            )
        )
        await engine._async_state_changed(
            FakeEvent(
                "cover.two",
                FakeState("open", current_position=100, current_tilt_position=100),
                FakeState("closing", current_position=80, current_tilt_position=100),
            )
        )

        self.assertFalse(engine.cover_pauses["cover_one"].active)
        self.assertTrue(engine.cover_pauses["cover_two"].active)
        self.assertEqual(hass.states.get("switch.cover_lock").state, "off")
        self.assertEqual(hass.states.get("switch.cover_two_lock").state, "on")

    async def test_noop_ha_position_call_does_not_create_intent_or_pause(self):
        hass, engine, _tomorrow = await self._engine()
        await engine._async_cover_service_called(
            ServiceEvent(
                "set_cover_position",
                {"entity_id": "cover.one", "position": 100},
            )
        )

        self.assertFalse(engine.cover_pauses["cover_one"].active)
        self.assertNotIn("cover.one", engine._manual_service_intents())
        self.assertEqual(hass.states.get("switch.cover_lock").state, "off")

    async def test_internal_context_without_user_or_parent_is_ignored(self):
        hass, engine, _tomorrow = await self._engine()
        await engine._async_cover_service_called(
            ServiceEvent(
                "set_cover_position",
                {"entity_id": "cover.one", "position": 40},
                user_id=None,
                parent_id=None,
            )
        )

        self.assertFalse(engine.cover_pauses["cover_one"].active)
        self.assertNotIn("cover.one", engine._manual_service_intents())
        self.assertEqual(hass.states.get("switch.cover_lock").state, "off")

    async def test_disabled_external_detection_ignores_explicit_ha_service(self):
        hass, engine, _tomorrow = await self._engine(
            external_movement_detection=False
        )
        await engine._async_cover_service_called(
            ServiceEvent(
                "set_cover_position",
                {"entity_id": "cover.one", "position": 40},
            )
        )

        self.assertFalse(engine.cover_pauses["cover_one"].active)
        self.assertNotIn("cover.one", engine._manual_service_intents())
        self.assertEqual(hass.states.get("switch.cover_lock").state, "off")

    async def test_automation_parent_context_is_external_intent(self):
        hass, engine, _tomorrow = await self._engine()
        await self._position_call_and_feedback(
            engine,
            user_id=None,
            parent_id="automation-context",
        )

        self.assertTrue(engine.cover_pauses["cover_one"].active)
        self.assertEqual(hass.states.get("switch.cover_lock").state, "on")

    async def test_window_automation_service_does_not_create_manual_pause(self):
        hass, engine, _tomorrow = await self._engine()
        cover = engine.config["rooms"][0]["sectors"][0]["layers"][0]["covers"][0]
        cover.update(
            {
                "window": "binary_sensor.window",
                "window_safe_state": "on",
                "window_policy": "block_closing",
                "window_returns_to_automation": True,
            }
        )
        hass.states.values["binary_sensor.window"] = FakeState("off")
        engine._rebuild_runtime()

        await self._position_call_and_feedback(
            engine,
            target=100,
            old_position=90,
            new_position=96,
            user_id=None,
            parent_id="window-automation-context",
        )

        self.assertFalse(engine.cover_pauses["cover_one"].active)
        self.assertNotIn("cover.one", engine._manual_service_intents())
        self.assertEqual(hass.states.get("switch.cover_lock").state, "off")

    async def test_direct_user_service_still_pauses_while_window_is_unsafe(self):
        hass, engine, _tomorrow = await self._engine()
        cover = engine.config["rooms"][0]["sectors"][0]["layers"][0]["covers"][0]
        cover.update(
            {
                "window": "binary_sensor.window",
                "window_safe_state": "on",
                "window_policy": "block_closing",
                "window_returns_to_automation": True,
            }
        )
        hass.states.values["binary_sensor.window"] = FakeState("off")
        engine._rebuild_runtime()

        await self._position_call_and_feedback(
            engine,
            target=40,
            old_position=90,
            new_position=70,
            user_id="user-1",
            parent_id=None,
        )

        self.assertTrue(engine.cover_pauses["cover_one"].active)
        self.assertEqual(
            engine.cover_pauses["cover_one"].reason,
            "home_assistant_manual_service",
        )
        self.assertEqual(hass.states.get("switch.cover_lock").state, "on")

    async def test_room_pause_sets_every_configured_manual_entity_on(self):
        hass, engine, _tomorrow = await self._engine("manual")
        covers = engine.config["rooms"][0]["sectors"][0]["layers"][0]["covers"]
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
        hass.states.values["cover.two"] = FakeState(
            "open", current_position=100, current_tilt_position=100
        )
        hass.states.values["switch.cover_two_lock"] = FakeState("off")
        engine._rebuild_runtime()

        await engine.async_pause_default("room")

        self.assertEqual(engine.rooms["room"].pause_mode, "manual")
        self.assertEqual(hass.states.get("switch.cover_lock").state, "on")
        self.assertEqual(hass.states.get("switch.cover_two_lock").state, "on")
        self.assertFalse(engine.cover_pauses["cover_one"].active)
        self.assertFalse(engine.cover_pauses["cover_two"].active)

    async def test_identical_knx_off_refresh_does_not_cancel_cover_pause(self):
        hass, engine, _tomorrow = await self._engine()
        await self._position_call_and_feedback(engine)

        await engine._async_state_changed(
            FakeEvent(
                "switch.cover_lock",
                FakeState("off"),
                FakeState("off"),
            )
        )

        self.assertTrue(engine.cover_pauses["cover_one"].active)
        self.assertEqual(hass.states.get("switch.cover_lock").state, "on")

    async def test_external_manual_entity_off_releases_cover_pause(self):
        _hass, engine, _tomorrow = await self._engine()
        await self._position_call_and_feedback(engine)
        await engine._async_state_changed(
            FakeEvent(
                "switch.cover_lock",
                FakeState("off"),
                FakeState("on"),
            )
        )
        calls = []

        async def fake_evaluate(trigger):
            calls.append(trigger)

        engine.async_evaluate_all = fake_evaluate
        await engine._async_state_changed(
            FakeEvent(
                "switch.cover_lock",
                FakeState("on"),
                FakeState("off"),
            )
        )

        self.assertFalse(engine.cover_pauses["cover_one"].active)
        self.assertEqual(calls, ["manual_group_released:switch.cover_lock"])

    async def test_resume_room_clears_local_cover_pause_and_owned_lock(self):
        hass, engine, _tomorrow = await self._engine()
        covers = engine.config["rooms"][0]["sectors"][0]["layers"][0]["covers"]
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
        hass.states.values["cover.two"] = FakeState(
            "open", current_position=100, current_tilt_position=100
        )
        hass.states.values["switch.cover_two_lock"] = FakeState("on")
        engine._rebuild_runtime()
        await self._position_call_and_feedback(engine)
        self.assertTrue(engine.cover_pauses["cover_one"].active)
        self.assertEqual(hass.states.get("switch.cover_lock").state, "on")

        calls = []

        async def fake_evaluate(trigger):
            calls.append(trigger)

        engine.async_evaluate_all = fake_evaluate
        await engine.async_resume_room("room")

        self.assertFalse(engine.cover_pauses["cover_one"].active)
        self.assertIsNone(engine.cover_pauses["cover_one"].until)
        self.assertEqual(hass.states.get("switch.cover_lock").state, "off")
        self.assertEqual(hass.states.get("switch.cover_two_lock").state, "off")
        self.assertEqual(calls, ["resume"])

    async def test_resume_room_clears_stale_lock_without_active_pause(self):
        hass, engine, _tomorrow = await self._engine()
        hass.states.values["switch.cover_lock"] = FakeState("on")
        self.assertFalse(engine.cover_pauses["cover_one"].active)

        calls = []

        async def fake_evaluate(trigger):
            calls.append(trigger)

        engine.async_evaluate_all = fake_evaluate
        await engine.async_resume_room("room")

        self.assertFalse(engine.cover_pauses["cover_one"].active)
        self.assertEqual(hass.states.get("switch.cover_lock").state, "off")
        self.assertEqual(calls, ["resume"])

    async def test_next_sunrise_uses_wizard_offset(self):
        _hass, engine, tomorrow = await self._engine(
            "next_sunrise", pause_sun_offset_minutes=30
        )
        await self._position_call_and_feedback(engine)
        self.assertEqual(
            engine.cover_pauses["cover_one"].until,
            tomorrow + timedelta(minutes=30),
        )

    async def test_next_sunset_uses_wizard_offset(self):
        _hass, engine, tomorrow = await self._engine(
            "next_sunset", pause_sun_offset_minutes=-15
        )
        await self._position_call_and_feedback(engine)
        self.assertEqual(
            engine.cover_pauses["cover_one"].until,
            tomorrow + timedelta(hours=8, minutes=-15),
        )

    async def test_timed_pause_uses_wizard_duration(self):
        _hass, engine, _tomorrow = await self._engine(
            "timed", pause_duration_hours=3.5
        )
        before = datetime.now(timezone.utc)
        await self._position_call_and_feedback(engine)
        due = engine.cover_pauses["cover_one"].until
        self.assertIsNotNone(due)
        self.assertGreaterEqual(due, before + timedelta(hours=3.5))
        self.assertLess(due, before + timedelta(hours=3.5, seconds=2))

    async def test_unavailable_night_source_cannot_start_endless_cover_pause(self):
        hass, engine, tomorrow = await self._engine(
            "next_night_end",
            night_enabled=True,
            night_source="entity",
            night_entity="schedule.night",
        )
        hass.states.values["schedule.night"] = FakeState("unavailable")

        await self._position_call_and_feedback(engine)

        pause = engine.cover_pauses["cover_one"]
        self.assertTrue(pause.active)
        self.assertEqual(pause.pause_mode, "next_sunrise")
        self.assertEqual(pause.until, tomorrow)
        self.assertFalse(pause.waiting_for_night)
        self.assertIn("cover_one", engine._cover_pause_timer_unsubs)
        saved = engine.store.cover_runtime("cover_one")
        self.assertEqual(saved["pause_mode"], "next_sunrise")
        self.assertEqual(saved["until"], tomorrow.isoformat())
        self.assertFalse(saved["waiting_for_night"])

    async def test_manual_pause_has_no_expiry(self):
        _hass, engine, _tomorrow = await self._engine("manual")
        await self._position_call_and_feedback(engine)
        pause = engine.cover_pauses["cover_one"]
        self.assertTrue(pause.active)
        self.assertIsNone(pause.until)


if __name__ == "__main__":
    unittest.main()
