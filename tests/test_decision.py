"""Pure regression coverage for the Issue #79 decision foundation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
import importlib.util
from pathlib import Path
import sys
import unittest


DECISION_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "smart_shading"
    / "decision.py"
)
spec = importlib.util.spec_from_file_location("smart_shading_decision", DECISION_PATH)
decision = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = decision
spec.loader.exec_module(decision)


CommandResultStatus = decision.CommandResultStatus
DecisionCommandResult = decision.CommandResult
DecisionCandidate = decision.DecisionCandidate
DecisionContext = decision.DecisionContext
DecisionPipeline = decision.DecisionPipeline
DecisionResolver = decision.DecisionResolver
InputKind = decision.InputKind
InputSnapshot = decision.InputSnapshot
MODE_DISABLED = decision.MODE_DISABLED
MODE_HEAT = decision.MODE_HEAT
MODE_IDLE = decision.MODE_IDLE
MODE_NIGHT = decision.MODE_NIGHT
MODE_OPEN = decision.MODE_OPEN
MODE_PAUSED = decision.MODE_PAUSED
MODE_SAFETY = decision.MODE_SAFETY
MODE_SOLAR = decision.MODE_SOLAR
PreviewPoint = decision.PreviewPoint
ProtectedZone = decision.ProtectedZone
ProtectedZoneStatus = decision.ProtectedZoneStatus
QualityState = decision.QualityState
SunGeometry = decision.SunGeometry
Target = decision.Target
apply_protected_zones = decision.apply_protected_zones
evaluate_protected_zone = decision.evaluate_protected_zone
evaluate_protected_zones = decision.evaluate_protected_zones
normalize_input = decision.normalize_input
preview_day = decision.preview_day
simulate = decision.simulate
validate_protected_zone = decision.validate_protected_zone


NOW = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)


def valid_snapshot(**values):
    """Build an explicit virtual snapshot without any Home Assistant import."""

    return InputSnapshot(
        evaluated_at=NOW,
        inputs={
            key: normalize_input(
                key,
                raw_value=value,
                expected=InputKind.NUMBER,
                evaluated_at=NOW,
                configured=True,
            )
            for key, value in values.items()
        },
    )


def base_context(**changes):
    values = {
        "snapshot": valid_snapshot(lux=25000),
        "normal_input_keys": ("lux",),
        "targets": {
            MODE_SAFETY: Target(position=100, tilt=0),
            MODE_NIGHT: Target(position=0, tilt=100),
            MODE_HEAT: Target(position=0, tilt=100),
            MODE_SOLAR: Target(position=30, tilt=45),
            MODE_OPEN: Target(position=100, tilt=0),
        },
        "sector_id": "south",
        "group_id": "blinds",
    }
    values.update(changes)
    return DecisionContext(**values)


class DecisionPriorityTests(unittest.TestCase):
    def setUp(self):
        self.pipeline = DecisionPipeline()

    def test_priority_contract_is_central_and_stable(self):
        cases = (
            (
                {
                    "safety_active": True,
                    "manual_override_active": True,
                    "night_active": True,
                    "heat_active": True,
                    "solar_active": True,
                },
                MODE_SAFETY,
            ),
            (
                {
                    "manual_override_active": True,
                    "night_active": True,
                    "heat_active": True,
                    "solar_active": True,
                },
                MODE_DISABLED,
            ),
            (
                {
                    "room_pause_active": True,
                    "night_active": True,
                    "heat_active": True,
                    "solar_active": True,
                },
                MODE_PAUSED,
            ),
            (
                {"night_active": True, "heat_active": True, "solar_active": True},
                MODE_NIGHT,
            ),
            ({"heat_active": True, "solar_active": True}, MODE_HEAT),
            ({"solar_active": True}, MODE_SOLAR),
            ({}, MODE_OPEN),
        )
        for state, expected_mode in cases:
            with self.subTest(state=state, expected_mode=expected_mode):
                result = self.pipeline.evaluate(base_context(**state))
                self.assertEqual(result.mode, expected_mode)
                self.assertEqual(result.trace.winner, result.winner)
                self.assertTrue(result.trace.rejected)

    def test_resolver_ignores_candidate_supplied_priority_numbers(self):
        resolution = DecisionResolver().resolve(
            (
                DecisionCandidate(
                    rule="solar",
                    matched=True,
                    mode=MODE_SOLAR,
                    priority=999_999,
                    reason_code="solar_active",
                ),
                DecisionCandidate(
                    rule="safety",
                    matched=True,
                    mode=MODE_SAFETY,
                    priority=-999_999,
                    reason_code="safety_active",
                ),
            )
        )
        self.assertEqual(resolution.winner.mode, MODE_SAFETY)
        self.assertGreater(resolution.winner.priority, 0)

    def test_equal_priority_trace_uses_an_explicit_tiebreak_reason(self):
        resolution = DecisionResolver().resolve(
            (
                DecisionCandidate(
                    rule="local_cover_pause",
                    matched=True,
                    mode=MODE_PAUSED,
                    reason_code="local",
                ),
                DecisionCandidate(
                    rule="room_pause",
                    matched=True,
                    mode=MODE_PAUSED,
                    reason_code="room",
                ),
            )
        )
        self.assertEqual(resolution.winner.rule, "room_pause")
        self.assertIn(
            "same_priority_tiebreaker",
            resolution.entries[0].resolution_reason_code,
        )

    def test_rule_mode_mismatch_cannot_claim_safety_priority(self):
        resolution = DecisionResolver().resolve(
            (
                DecisionCandidate(
                    rule="safety",
                    matched=True,
                    mode=MODE_OPEN,
                    reason_code="bad_public_candidate",
                ),
                DecisionCandidate(
                    rule="open",
                    matched=True,
                    mode=MODE_OPEN,
                    reason_code="open",
                ),
            )
        )
        self.assertEqual(resolution.winner.rule, "open")
        bad = next(item for item in resolution.entries if item.candidate.rule == "safety")
        self.assertFalse(bad.candidate.matched)
        self.assertEqual(bad.candidate.reason_code, "rule_mode_mismatch")

    def test_foreign_command_enum_uses_its_wire_value(self):
        class ForeignCommandStatus(Enum):
            SENT = "sent"

        result = DecisionCommandResult(
            status=ForeignCommandStatus.SENT,
            reason_code="adapter",
        )
        self.assertEqual(result.status, CommandResultStatus.SENT)

    def test_trace_has_a_non_execution_command_result(self):
        result = self.pipeline.evaluate(base_context(solar_active=True))
        self.assertEqual(result.trace.command_result.status, CommandResultStatus.NOT_PLANNED)
        outcomes = [entry.outcome.value for entry in result.trace.entries]
        self.assertEqual(outcomes.count("winner"), 1)
        self.assertGreaterEqual(outcomes.count("rejected"), 1)


class InputQualityTests(unittest.TestCase):
    def test_normalizer_distinguishes_unavailable_stale_invalid_and_pending(self):
        unavailable = normalize_input(
            "lux",
            raw_value="unavailable",
            expected=InputKind.NUMBER,
            configured=True,
        )
        stale = normalize_input(
            "temperature",
            raw_value="24,5",
            expected=InputKind.NUMBER,
            observed_at=NOW - timedelta(minutes=30),
            evaluated_at=NOW,
            max_age=timedelta(minutes=5),
            configured=True,
        )
        invalid = normalize_input(
            "lux",
            raw_value="not-a-number",
            expected=InputKind.NUMBER,
            configured=True,
        )
        pending = normalize_input(
            "lux",
            raw_value="25000",
            expected=InputKind.NUMBER,
            quality=QualityState.PENDING,
            configured=True,
        )

        self.assertEqual(unavailable.quality, QualityState.UNAVAILABLE)
        self.assertEqual(stale.quality, QualityState.STALE)
        self.assertEqual(stale.value, 24.5)
        self.assertEqual(invalid.quality, QualityState.INVALID_VALUE)
        self.assertEqual(pending.quality, QualityState.PENDING)

    def test_nonvalid_required_input_holds_normal_automation(self):
        for quality in (
            QualityState.UNAVAILABLE,
            QualityState.STALE,
            QualityState.INVALID_VALUE,
            QualityState.PENDING,
        ):
            with self.subTest(quality=quality):
                value = normalize_input(
                    "lux",
                    raw_value="25000",
                    expected=InputKind.NUMBER,
                    quality=quality,
                    configured=True,
                )
                context = base_context(
                    snapshot=InputSnapshot(evaluated_at=NOW, inputs={"lux": value}),
                    solar_active=True,
                )
                result = DecisionPipeline().evaluate(context)
                self.assertEqual(result.mode, MODE_IDLE)
                self.assertEqual(result.winner.rule, "input_quality_hold")
                solar = next(
                    candidate
                    for candidate in result.trace.rejected
                    if candidate.rule == "solar"
                )
                self.assertEqual(solar.reason_code, "solar_blocked_by_input_quality")

    def test_safety_remains_available_when_normal_input_is_bad(self):
        context = base_context(
            snapshot=InputSnapshot(
                evaluated_at=NOW,
                inputs={
                    "lux": normalize_input(
                        "lux",
                        raw_value="unavailable",
                        expected=InputKind.NUMBER,
                        configured=True,
                    )
                },
            ),
            solar_active=True,
            safety_active=True,
        )
        self.assertEqual(DecisionPipeline().evaluate(context).mode, MODE_SAFETY)


class ProtectedZoneTests(unittest.TestCase):
    def setUp(self):
        self.geometry = SunGeometry(
            elevation_degrees=30,
            azimuth_degrees=180,
            facade_azimuth_degrees=180,
            window_lower_height_m=0,
            window_upper_height_m=2.4,
        )

    def _zone(self, **changes):
        values = {
            "zone_id": "tv",
            "name": "TV",
            "sector_id": "south",
            "distance_m": 1.5,
            "lower_height_m": 0.2,
            "upper_height_m": 0.8,
            "target_position": 30,
            "target_tilt": 80,
        }
        values.update(changes)
        return ProtectedZone(**values)

    def test_valid_hit_adjusts_solar_target(self):
        zone = self._zone()
        self.assertEqual(validate_protected_zone(zone).status, ProtectedZoneStatus.VALID)
        evaluation = evaluate_protected_zone(
            zone, self.geometry, sector_id="south", group_id="blinds"
        )
        self.assertEqual(evaluation.status, ProtectedZoneStatus.HIT)
        adjustment = apply_protected_zones(Target(position=70, tilt=35), (evaluation,))
        self.assertEqual(adjustment.target, Target(position=30, tilt=80, details={"protected_zone_hit_ids": ("tv",)}))
        self.assertEqual(adjustment.applied_zone_ids, ("tv",))

    def test_zone_can_be_constructed_from_persisted_wizard_values(self):
        zone = ProtectedZone.from_config(
            {
                "id": "desk",
                "name": "Desk",
                "group_ids": ["blinds"],
                "enabled": True,
                "distance_m": 1.2,
                "lower_height_m": 0.4,
                "upper_height_m": 1.0,
                "target_position": 25,
                "target_tilt": 85,
            },
            sector_id="south",
        )
        self.assertEqual(zone.zone_id, "desk")
        self.assertEqual(zone.sector_id, "south")
        self.assertEqual(zone.group_ids, ("blinds",))

    def test_vertical_miss_keeps_ordinary_solar_target(self):
        zone = self._zone(
            distance_m=5,
            lower_height_m=0,
            upper_height_m=0.2,
        )
        evaluation = evaluate_protected_zone(zone, self.geometry, sector_id="south")
        self.assertEqual(evaluation.status, ProtectedZoneStatus.MISS)
        ordinary = Target(position=70, tilt=35)
        self.assertEqual(apply_protected_zones(ordinary, (evaluation,)).target, ordinary)

    def test_multiple_hit_zones_choose_most_protective_axis_values(self):
        position_zone = self._zone(zone_id="tv", target_position=20, target_tilt=None)
        tilt_zone = self._zone(
            zone_id="desk",
            name="Desk",
            target_position=None,
            target_tilt=90,
        )
        evaluations = evaluate_protected_zones(
            (position_zone, tilt_zone), self.geometry, sector_id="south", group_id="blinds"
        )
        adjustment = apply_protected_zones(Target(position=70, tilt=35), evaluations)
        self.assertEqual(adjustment.target.position, 20)
        self.assertEqual(adjustment.target.tilt, 90)
        self.assertEqual(set(adjustment.applied_zone_ids), {"tv", "desk"})

    def test_invalid_geometry_is_visible_but_cannot_block_solar(self):
        invalid = self._zone(lower_height_m=1.0, upper_height_m=0.5)
        evaluation = evaluate_protected_zone(invalid, self.geometry, sector_id="south")
        self.assertEqual(evaluation.status, ProtectedZoneStatus.INVALID)
        context = base_context(
            solar_active=True,
            sun_geometry=self.geometry,
            protected_zones=(invalid,),
        )
        result = DecisionPipeline().evaluate(context)
        self.assertEqual(result.mode, MODE_SOLAR)
        self.assertEqual(result.target, Target(position=30, tilt=45))
        self.assertEqual(result.trace.protected_zones[0].status, ProtectedZoneStatus.INVALID)

    def test_sector_and_group_isolation_prevents_cross_target_changes(self):
        scoped = self._zone(group_ids=("living",))
        wrong_sector = evaluate_protected_zone(
            scoped, self.geometry, sector_id="west", group_id="living"
        )
        wrong_group = evaluate_protected_zone(
            scoped, self.geometry, sector_id="south", group_id="bedroom"
        )
        self.assertEqual(wrong_sector.status, ProtectedZoneStatus.INACTIVE)
        self.assertEqual(wrong_group.status, ProtectedZoneStatus.INACTIVE)

        context = base_context(
            solar_active=True,
            sector_id="south",
            group_id="bedroom",
            sun_geometry=self.geometry,
            protected_zones=(scoped,),
        )
        result = DecisionPipeline().evaluate(context)
        self.assertEqual(result.target, Target(position=30, tilt=45))
        self.assertEqual(
            result.trace.protected_zones[0].reason_code,
            "protected_zone_other_group",
        )

    def test_missing_sector_context_fails_closed(self):
        evaluation = evaluate_protected_zone(self._zone(), self.geometry)
        self.assertEqual(evaluation.status, ProtectedZoneStatus.INACTIVE)
        self.assertEqual(
            evaluation.reason_code,
            "protected_zone_sector_context_required",
        )

    def test_lateral_zone_needs_azimuth_geometry_and_grazing_sun_misses(self):
        zone = self._zone(lateral_min_m=-1.0, lateral_max_m=1.0)
        missing = evaluate_protected_zone(
            zone,
            SunGeometry(elevation_degrees=20, direct_sun=True),
            sector_id="south",
        )
        self.assertEqual(missing.status, ProtectedZoneStatus.INACTIVE)
        self.assertEqual(
            missing.reason_code,
            "protected_zone_lateral_geometry_required",
        )
        grazing = evaluate_protected_zone(
            zone,
            SunGeometry(
                elevation_degrees=20,
                azimuth_degrees=270,
                facade_azimuth_degrees=180,
                direct_sun=True,
            ),
            sector_id="south",
        )
        self.assertEqual(grazing.status, ProtectedZoneStatus.MISS)
        self.assertEqual(grazing.reason_code, "protected_zone_sun_behind_facade")

    def test_oblique_ray_uses_facade_normal_distance_for_vertical_projection(self):
        zone = self._zone(distance_m=1.5)
        straight = evaluate_protected_zone(
            zone,
            SunGeometry(
                elevation_degrees=20,
                azimuth_degrees=180,
                facade_azimuth_degrees=180,
                direct_sun=True,
            ),
            sector_id="south",
        )
        oblique = evaluate_protected_zone(
            zone,
            SunGeometry(
                elevation_degrees=20,
                azimuth_degrees=240,
                facade_azimuth_degrees=180,
                direct_sun=True,
            ),
            sector_id="south",
        )
        self.assertGreater(
            oblique.details["vertical_drop_m"], straight.details["vertical_drop_m"]
        )
        self.assertAlmostEqual(
            oblique.details["vertical_drop_m"],
            straight.details["vertical_drop_m"] * 2,
            places=6,
        )

    def test_hit_without_stricter_target_preserves_baseline_details(self):
        baseline = Target(position=30, tilt=80, details={"source": "profile"})
        evaluation = evaluate_protected_zone(
            self._zone(target_position=30, target_tilt=80),
            self.geometry,
            sector_id="south",
        )
        adjustment = apply_protected_zones(baseline, (evaluation,))
        self.assertIs(adjustment.target, baseline)
        self.assertEqual(adjustment.applied_zone_ids, ())
        self.assertEqual(
            adjustment.reason_code,
            "protected_zone_hit_no_stricter_target",
        )


class SimulationAndPreviewTests(unittest.TestCase):
    def test_simulation_uses_pipeline_without_mutating_live_context(self):
        context = base_context(solar_active=True)
        original_snapshot = context.snapshot
        result = simulate(context, overrides={"lux": "unavailable"})

        self.assertTrue(result.simulation)
        self.assertEqual(result.trace.command_result.status, CommandResultStatus.SIMULATED)
        self.assertEqual(result.mode, MODE_IDLE)
        self.assertIs(context.snapshot, original_snapshot)
        self.assertEqual(context.snapshot.quality("lux"), QualityState.VALID)

    def test_trace_exports_normalized_input_snapshot(self):
        result = DecisionPipeline().evaluate(base_context(solar_active=True))
        trace = result.trace.as_dict()
        self.assertEqual(trace["input_snapshot"]["inputs"]["lux"]["quality"], "valid")
        self.assertEqual(trace["input_snapshot"]["inputs"]["lux"]["value"], 25000.0)

    def test_day_preview_reuses_the_same_pipeline_for_every_virtual_point(self):
        class CountingPipeline(DecisionPipeline):
            def __init__(self):
                super().__init__()
                self.calls = 0

            def evaluate(self, context, *, simulation=False):
                self.calls += 1
                return super().evaluate(context, simulation=simulation)

        pipeline = CountingPipeline()
        preview = preview_day(
            (
                PreviewPoint(
                    at=NOW.replace(hour=9),
                    context=base_context(solar_active=False),
                    label="before sector",
                ),
                PreviewPoint(
                    at=NOW.replace(hour=11),
                    context=base_context(solar_active=True),
                    label="inside sector",
                ),
            ),
            pipeline=pipeline,
        )

        self.assertEqual(pipeline.calls, 2)
        self.assertEqual([sample.result.mode for sample in preview.samples], [MODE_OPEN, MODE_SOLAR])
        self.assertEqual(len(preview.transitions), 1)
        self.assertEqual(preview.transitions[0].mode, MODE_SOLAR)
        self.assertTrue(all(sample.result.simulation for sample in preview.samples))

    def test_preview_regrades_input_staleness_at_each_virtual_time(self):
        snapshot = InputSnapshot(
            evaluated_at=NOW,
            inputs={
                "lux": normalize_input(
                    "lux",
                    raw_value=25000,
                    expected=InputKind.NUMBER,
                    observed_at=NOW,
                    evaluated_at=NOW,
                    max_age=1,
                    configured=True,
                )
            },
        )
        context = base_context(snapshot=snapshot, solar_active=True)
        preview = preview_day(
            (
                PreviewPoint(at=NOW, context=context, label="fresh"),
                PreviewPoint(
                    at=NOW + timedelta(seconds=2),
                    context=context,
                    label="stale",
                ),
            )
        )
        self.assertEqual(
            [sample.result.mode for sample in preview.samples],
            [MODE_SOLAR, MODE_IDLE],
        )
        self.assertEqual(
            preview.samples[1].result.trace.input_snapshot.quality("lux"),
            QualityState.STALE,
        )


if __name__ == "__main__":
    unittest.main()
