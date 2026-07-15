from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest

from test_engine_runtime import (
    COMP,
    FakeEntry,
    FakeHass,
    FakeState,
    _load,
    base_config,
)

_load(
    "custom_components.smart_shading.manual_detection",
    COMP / "manual_detection.py",
)
controller_mod = _load(
    "custom_components.smart_shading.controller",
    COMP / "controller.py",
)


class ServiceEvent:
    def __init__(
        self,
        service: str,
        service_data: dict,
        *,
        user_id: str | None = "user-1",
        parent_id: str | None = None,
    ) -> None:
        self.data = {
            "domain": "cover",
            "service": service,
            "service_data": service_data,
        }
        self.context = SimpleNamespace(user_id=user_id, parent_id=parent_id)


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

    async def test_direct_ha_position_call_pauses_cover_and_sets_lock(self):
        hass, engine, _tomorrow = await self._engine()
        await engine._async_cover_service_called(
            ServiceEvent(
                "set_cover_position",
                {"entity_id": "cover.one", "position": 40},
            )
        )

        pause = engine.cover_pauses["cover_one"]
        self.assertTrue(pause.active)
        self.assertEqual(pause.reason, "home_assistant_manual_service")
        self.assertIsNotNone(pause.until)
        self.assertEqual(hass.states.get("switch.cover_lock").state, "on")

    async def test_noop_ha_position_call_does_not_pause(self):
        hass, engine, _tomorrow = await self._engine()
        await engine._async_cover_service_called(
            ServiceEvent(
                "set_cover_position",
                {"entity_id": "cover.one", "position": 100},
            )
        )

        self.assertFalse(engine.cover_pauses["cover_one"].active)
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
        self.assertEqual(hass.states.get("switch.cover_lock").state, "off")

    async def test_automation_parent_context_is_external_intent(self):
        hass, engine, _tomorrow = await self._engine()
        await engine._async_cover_service_called(
            ServiceEvent(
                "close_cover",
                {"entity_id": "cover.one"},
                user_id=None,
                parent_id="automation-context",
            )
        )

        self.assertTrue(engine.cover_pauses["cover_one"].active)
        self.assertEqual(hass.states.get("switch.cover_lock").state, "on")

    async def test_next_sunrise_uses_wizard_offset(self):
        _hass, engine, tomorrow = await self._engine(
            "next_sunrise", pause_sun_offset_minutes=30
        )
        await engine._async_cover_service_called(
            ServiceEvent(
                "set_cover_position",
                {"entity_id": "cover.one", "position": 40},
            )
        )
        self.assertEqual(
            engine.cover_pauses["cover_one"].until,
            tomorrow + timedelta(minutes=30),
        )

    async def test_next_sunset_uses_wizard_offset(self):
        _hass, engine, tomorrow = await self._engine(
            "next_sunset", pause_sun_offset_minutes=-15
        )
        await engine._async_cover_service_called(
            ServiceEvent(
                "set_cover_position",
                {"entity_id": "cover.one", "position": 40},
            )
        )
        self.assertEqual(
            engine.cover_pauses["cover_one"].until,
            tomorrow + timedelta(hours=8, minutes=-15),
        )

    async def test_timed_pause_uses_wizard_duration(self):
        _hass, engine, _tomorrow = await self._engine(
            "timed", pause_duration_hours=3.5
        )
        before = datetime.now(timezone.utc)
        await engine._async_cover_service_called(
            ServiceEvent(
                "set_cover_position",
                {"entity_id": "cover.one", "position": 40},
            )
        )
        due = engine.cover_pauses["cover_one"].until
        self.assertIsNotNone(due)
        self.assertGreaterEqual(due, before + timedelta(hours=3.5))
        self.assertLess(due, before + timedelta(hours=3.5, seconds=2))

    async def test_manual_pause_has_no_expiry(self):
        _hass, engine, _tomorrow = await self._engine("manual")
        await engine._async_cover_service_called(
            ServiceEvent(
                "set_cover_position",
                {"entity_id": "cover.one", "position": 40},
            )
        )
        pause = engine.cover_pauses["cover_one"]
        self.assertTrue(pause.active)
        self.assertIsNone(pause.until)


if __name__ == "__main__":
    unittest.main()
