from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import sys
import types
import unittest

try:
    from test_engine_runtime import (
        COMP, FakeEntry, FakeHass, FakeState, _load, base_config, engine_mod,
    )
except ModuleNotFoundError:  # package-style unittest invocation
    from tests.test_engine_runtime import (
        COMP, FakeEntry, FakeHass, FakeState, _load, base_config, engine_mod,
    )


sensor_component = types.ModuleType("homeassistant.components.sensor")
sensor_component.SensorEntity = type("SensorEntity", (), {})
sys.modules["homeassistant.components.sensor"] = sensor_component

entity_helper = types.ModuleType("homeassistant.helpers.entity")
entity_helper.Entity = type("Entity", (), {})
entity_helper.EntityCategory = type("EntityCategory", (), {"DIAGNOSTIC": "diagnostic"})
sys.modules["homeassistant.helpers.entity"] = entity_helper

device_registry = sys.modules["homeassistant.helpers.device_registry"]
device_registry.DeviceInfo = dict

_load("custom_components.smart_shading.entity", COMP / "entity.py")
sensor_mod = _load("custom_components.smart_shading.sensor", COMP / "sensor.py")


class StatusAttributeBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        self.hass = FakeHass(
            {
                "sun.sun": FakeState(
                    "above_horizon",
                    azimuth=180,
                    elevation=35,
                    next_rising=tomorrow.isoformat(),
                    next_setting=tomorrow.isoformat(),
                ),
                "sensor.lux": FakeState("36000", unit_of_measurement="lx"),
                "cover.one": FakeState(
                    "open", current_position=100, current_tilt_position=100
                ),
                "switch.cover_lock": FakeState("off"),
            }
        )
        self.engine = engine_mod.SmartShadingEngine(
            self.hass, FakeEntry(base_config())
        )
        await self.engine.async_initialize()

    async def test_room_status_attributes_stay_below_recorder_limit(self):
        runtime = self.engine.rooms["room"]
        room = self.engine.config["rooms"][0]
        room.update(
            {
                "advanced_features": ["night", "schedule"],
                "night_enabled": False,
                "night_source": "sun",
                "schedule_enabled": True,
            }
        )
        cover = room["sectors"][0]["layers"][0]["covers"][0]
        cover.update(
            {
                "enforce_max_open_position": True,
                "max_open_position": 90,
            }
        )
        room["sectors"][0]["protected_zones"] = [
            {
                "id": "dining_table",
                "name": "Dining table",
                "enabled": True,
                "cover_entity": "cover.one",
                "calculation_mode": "curtain",
                "window_width_m": 2.4,
                "internal_debug": "not public",
            }
        ]
        oversized = "x" * 50_000
        runtime.decision_trace = {
            "schema": 1,
            "winner": {
                "rule": "solar",
                "mode": "solar",
                "reason_code": "solar_conditions_matched",
                "target": {"position": 20, "tilt": 40},
                "internal_debug": oversized,
            },
            "entries": [
                {
                    "candidate": {
                        "rule": "solar",
                        "mode": "solar",
                        "reason_code": "solar_conditions_matched",
                        "target": {"position": index},
                        "debug": oversized,
                    },
                    "outcome": "winner" if index == 0 else "rejected",
                    "resolution_reason_code": "highest_matching_priority",
                }
                for index in range(20)
            ],
            "debug": oversized,
        }
        runtime.simulation_trace = {
            "schema": 1,
            "available": True,
            "results": [
                {
                    "sector_id": "south",
                    "layer_id": "layer",
                    "debug": oversized,
                    "result": {
                        "mode": "solar",
                        "target": {"position": 20},
                        "trace": runtime.decision_trace,
                    },
                }
                for _ in range(12)
            ],
        }
        runtime.day_preview = {
            "preview": {
                "day": "2031-06-21",
                "transitions": [
                    {"at": str(index), "mode": "solar", "debug": oversized}
                    for index in range(40)
                ],
                "samples": [{"debug": oversized}] * 200,
            }
        }
        original_trace = runtime.decision_trace

        sensor = sensor_mod.RoomStatusSensor(self.engine, "room")
        attributes = sensor.extra_state_attributes
        encoded = json.dumps(
            attributes, default=str, separators=(",", ":")
        ).encode()

        self.assertLessEqual(len(encoded), sensor_mod.STATE_ATTRIBUTE_BUDGET)
        self.assertLess(len(encoded), 16_384)
        self.assertNotIn("card_yaml", attributes)
        self.assertNotIn("badge_yaml", attributes)
        configuration = attributes["configuration"]
        self.assertEqual(
            ["night", "schedule"], configuration["advanced_features"]
        )
        self.assertIs(configuration["night_enabled"], False)
        self.assertEqual("sun", configuration["night_source"])
        self.assertIs(configuration["schedule_enabled"], True)
        compact_cover = configuration["sectors"][0]["layers"][0]["covers"][0]
        self.assertIs(compact_cover["enforce_max_open_position"], True)
        self.assertEqual(90, compact_cover["max_open_position"])
        compact_zone = configuration["sectors"][0]["protected_zones"][0]
        self.assertEqual(
            {
                "id": "dining_table",
                "name": "Dining table",
                "enabled": True,
                "cover_entity": "cover.one",
                "calculation_mode": "curtain",
            },
            compact_zone,
        )
        self.assertEqual("2031-06-21", attributes["day_preview"]["day"])
        self.assertIs(runtime.decision_trace, original_trace)
        self.assertIn("debug", runtime.decision_trace)

    async def test_house_status_does_not_repeat_dashboard_yaml(self):
        sensor = sensor_mod.HouseStatusSensor(self.engine)
        attributes = sensor.extra_state_attributes
        self.assertNotIn("card_yaml", attributes)
        self.assertNotIn("badge_yaml", attributes)
        self.assertLess(
            len(json.dumps(attributes, default=str).encode()), 16_384
        )


if __name__ == "__main__":
    unittest.main()
