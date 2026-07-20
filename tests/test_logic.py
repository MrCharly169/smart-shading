from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

import importlib.util
from pathlib import Path

LOGIC_PATH = Path(__file__).parents[1] / "custom_components" / "smart_shading" / "logic.py"
spec = importlib.util.spec_from_file_location("smart_shading_logic", LOGIC_PATH)
logic = importlib.util.module_from_spec(spec)
assert spec and spec.loader
import sys
sys.modules[spec.name] = logic
spec.loader.exec_module(logic)
adaptive_tilt = logic.adaptive_tilt
azimuth_inside = logic.azimuth_inside
sun_presence_step = logic.sun_presence_step
finalize_sector_identity = logic.finalize_sector_identity
needs_custom_sun_settings = logic.needs_custom_sun_settings
parse_numeric_value = logic.parse_numeric_value
classify_cover_feedback = logic.classify_cover_feedback


class LogicTests(unittest.TestCase):
    def test_azimuth_normal_range(self):
        self.assertTrue(azimuth_inside(180, 120, 240))
        self.assertFalse(azimuth_inside(80, 120, 240))

    def test_azimuth_north_wrapping_range(self):
        self.assertTrue(azimuth_inside(350, 300, 40))
        self.assertTrue(azimuth_inside(20, 300, 40))
        self.assertFalse(azimuth_inside(180, 300, 40))

    def test_sun_on_delay(self):
        start = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
        first = sun_presence_step(
            now=start,
            lux=20000,
            is_on=False,
            pending_target=None,
            pending_since=None,
            on_lux=15000,
            off_lux=10000,
            on_delay_minutes=3,
            off_delay_minutes=10,
        )
        self.assertFalse(first.is_on)
        self.assertTrue(first.pending_target)
        second = sun_presence_step(
            now=start + timedelta(minutes=3),
            lux=20000,
            is_on=first.is_on,
            pending_target=first.pending_target,
            pending_since=first.pending_since,
            on_lux=15000,
            off_lux=10000,
            on_delay_minutes=3,
            off_delay_minutes=10,
        )
        self.assertTrue(second.is_on)
        self.assertTrue(second.transitioned)

    def test_sun_pending_cancels_when_threshold_lost(self):
        start = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
        first = sun_presence_step(
            now=start,
            lux=20000,
            is_on=False,
            pending_target=None,
            pending_since=None,
            on_lux=15000,
            off_lux=10000,
            on_delay_minutes=3,
            off_delay_minutes=10,
        )
        cancelled = sun_presence_step(
            now=start + timedelta(minutes=1),
            lux=12000,
            is_on=False,
            pending_target=first.pending_target,
            pending_since=first.pending_since,
            on_lux=15000,
            off_lux=10000,
            on_delay_minutes=3,
            off_delay_minutes=10,
        )
        self.assertIsNone(cancelled.pending_target)
        self.assertFalse(cancelled.is_on)

    def test_sun_off_delay(self):
        start = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
        first = sun_presence_step(
            now=start,
            lux=4000,
            is_on=True,
            pending_target=None,
            pending_since=None,
            on_lux=15000,
            off_lux=10000,
            on_delay_minutes=3,
            off_delay_minutes=10,
        )
        self.assertFalse(first.pending_target)
        second = sun_presence_step(
            now=start + timedelta(minutes=10),
            lux=4000,
            is_on=True,
            pending_target=first.pending_target,
            pending_since=first.pending_since,
            on_lux=15000,
            off_lux=10000,
            on_delay_minutes=3,
            off_delay_minutes=10,
        )
        self.assertFalse(second.is_on)
        self.assertTrue(second.transitioned)

    def test_adaptive_tilt(self):
        points = [
            {"elevation": 10, "tilt": 10},
            {"elevation": 20, "tilt": 35},
            {"elevation": 40, "tilt": 65},
            {"elevation": 60, "tilt": 85},
        ]
        self.assertEqual(adaptive_tilt(15, 100, points), 10)
        self.assertEqual(adaptive_tilt(30, 100, points), 35)
        self.assertEqual(adaptive_tilt(55, 100, points), 65)
        self.assertEqual(adaptive_tilt(70, 100, points), 85)


    def test_compact_sector_identity_is_always_created(self):
        sector = finalize_sector_identity(
            {"direction": "south"},
            name="South",
            short="s",
            id_factory=lambda name: f"id_{name.lower()}",
        )
        self.assertEqual(sector["id"], "id_south")
        self.assertEqual(sector["name"], "South")
        self.assertEqual(sector["short"], "S")
        self.assertEqual(sector["layers"], [])

    def test_custom_sun_page_only_for_custom_with_lux(self):
        self.assertTrue(needs_custom_sun_settings(preset="custom", lux_sensor="sensor.lux"))
        self.assertFalse(needs_custom_sun_settings(preset="medium", lux_sensor="sensor.lux"))
        self.assertFalse(needs_custom_sun_settings(preset="custom", lux_sensor=""))

    def test_numeric_parser_reads_real_lux_formats(self):
        self.assertEqual(parse_numeric_value("26398.72"), 26398.72)
        self.assertEqual(parse_numeric_value("26,398.72"), 26398.72)
        self.assertEqual(parse_numeric_value("26.398,72"), 26398.72)
        self.assertEqual(parse_numeric_value("26 398,72 lx"), 26398.72)
        self.assertIsNone(parse_numeric_value("unavailable"))
        self.assertIsNone(parse_numeric_value("not-a-number"))

    def test_real_lux_value_turns_balanced_sun_presence_on_after_delay(self):
        start = datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)
        first = sun_presence_step(
            now=start,
            lux=parse_numeric_value("26398.72"),
            is_on=False,
            pending_target=None,
            pending_since=None,
            on_lux=18000,
            off_lux=9000,
            on_delay_minutes=3,
            off_delay_minutes=12,
        )
        self.assertFalse(first.is_on)
        self.assertTrue(first.pending_target)
        completed = sun_presence_step(
            now=start + timedelta(minutes=3),
            lux=parse_numeric_value("26398.72"),
            is_on=first.is_on,
            pending_target=first.pending_target,
            pending_since=first.pending_since,
            on_lux=18000,
            off_lux=9000,
            on_delay_minutes=3,
            off_delay_minutes=12,
        )
        self.assertTrue(completed.is_on)
        self.assertTrue(completed.transitioned)


    def test_initial_cover_state_does_not_create_manual_override(self):
        decision = classify_cover_feedback(
            old_position=None,
            new_position=100,
            old_tilt=None,
            new_tilt=100,
            old_state=None,
            new_state="open",
            target_position=None,
            target_tilt=None,
            command_age_seconds=None,
        )
        self.assertFalse(decision.changed)
        self.assertFalse(decision.manual)

    def test_direct_open_to_closed_transition_is_manual_without_own_command(self):
        decision = classify_cover_feedback(
            old_position=100,
            new_position=0,
            old_tilt=100,
            new_tilt=100,
            old_state="open",
            new_state="closed",
            target_position=None,
            target_tilt=None,
            command_age_seconds=None,
        )
        self.assertTrue(decision.changed)
        self.assertTrue(decision.manual)

    def test_own_cover_feedback_moves_toward_target(self):
        decision = classify_cover_feedback(
            old_position=0,
            new_position=40,
            old_tilt=100,
            new_tilt=100,
            old_state="opening",
            new_state="opening",
            target_position=100,
            target_tilt=100,
            command_age_seconds=8,
        )
        self.assertTrue(decision.expected)
        self.assertFalse(decision.manual)

    def test_cover_feedback_away_from_target_is_manual(self):
        decision = classify_cover_feedback(
            old_position=100,
            new_position=70,
            old_tilt=100,
            new_tilt=100,
            old_state="open",
            new_state="closing",
            target_position=100,
            target_tilt=100,
            command_age_seconds=8,
        )
        self.assertFalse(decision.expected)
        self.assertTrue(decision.manual)

    def test_cover_change_without_fresh_command_is_manual(self):
        decision = classify_cover_feedback(
            old_position=100,
            new_position=0,
            old_tilt=100,
            new_tilt=100,
            old_state="open",
            new_state="closed",
            target_position=100,
            target_tilt=100,
            command_age_seconds=300,
        )
        self.assertTrue(decision.manual)

    def test_small_cover_feedback_jitter_is_ignored(self):
        decision = classify_cover_feedback(
            old_position=100,
            new_position=99,
            old_tilt=100,
            new_tilt=99,
            old_state="open",
            new_state="open",
            target_position=None,
            target_tilt=None,
            command_age_seconds=None,
            position_change_threshold=2,
            tilt_change_threshold=3,
        )
        self.assertFalse(decision.changed)
        self.assertFalse(decision.manual)

    def test_state_string_transition_without_numeric_feedback_is_ignored(self):
        decision = classify_cover_feedback(
            old_position=100,
            new_position=100,
            old_tilt=100,
            new_tilt=100,
            old_state="open",
            new_state="closing",
            target_position=None,
            target_tilt=None,
            command_age_seconds=None,
        )
        self.assertFalse(decision.changed)
        self.assertFalse(decision.manual)
        self.assertEqual(decision.reason, "state_only_change_ignored")


if __name__ == "__main__":
    unittest.main()
