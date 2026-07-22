"""Focused runtime coverage for stale normal-command cancellation."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import sys
import unittest

try:  # ``unittest discover -s tests`` and package execution use different roots.
    from test_engine_runtime import (
        FakeEntry,
        FakeHass,
        FakeState,
        base_config,
        engine_mod,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by package runners.
    from tests.test_engine_runtime import (  # type: ignore[no-redef]
        FakeEntry,
        FakeHass,
        FakeState,
        base_config,
        engine_mod,
    )


execution_mod = sys.modules["custom_components.smart_shading.execution"]


class QueueCancellationTests(unittest.IsolatedAsyncioTestCase):
    """Cancellation must be durable, explainable, and facade-scoped."""

    async def asyncSetUp(self) -> None:
        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        self.now = datetime.now(timezone.utc)
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
            "cover.two": FakeState(
                "open", current_position=100, current_tilt_position=100
            ),
            "switch.cover_lock": FakeState("off"),
        }
        config = base_config()
        south = config["rooms"][0]["sectors"][0]
        west = deepcopy(south)
        west.update({"id": "west", "name": "West", "short": "W"})
        west_layer = west["layers"][0]
        west_layer.update({"id": "layer_west", "name": "West blinds"})
        west_cover = west_layer["covers"][0]
        west_cover.update(
            {
                "id": "cover_two",
                "entity": "cover.two",
                "name": "Cover two",
                "short": "C2",
            }
        )
        config["rooms"][0]["sectors"].append(west)
        self.hass = FakeHass(self.values)
        self.engine = engine_mod.SmartShadingEngine(
            self.hass, FakeEntry(config)
        )
        await self.engine.async_initialize()

    def _plan(
        self,
        cover_id: str,
        *,
        rule: str,
        sector_id: str,
        group_id: str,
        safety: bool = False,
        stagger_seconds: float = 60.0,
    ):
        request = execution_mod.CommandRequest(
            cover_id=cover_id,
            profile="curtain",
            target=execution_mod.CommandTarget(position=0.0),
            rule=rule,
            reason_code=f"{rule}_test_target",
            context=execution_mod.CommandContext(
                room_id="room",
                sector_id=sector_id,
                group_id=group_id,
            ),
            priority=self.engine._command_priority(rule),
            current_position=100.0,
            position_tolerance=1.0,
            feedback_quality=execution_mod.FeedbackQuality.TRUSTED,
            verification_delay=timedelta(seconds=30),
            stagger_seconds=stagger_seconds,
            stagger_scope="room",
            safety=safety,
        )
        return self.engine.command_planner.plan(request, now=self.now)

    def _seed_target_trace(self, lifecycle_id: str) -> None:
        runtime = self.engine.rooms["room"]
        runtime.targets = [
            {
                "cover_id": "cover_one",
                "lifecycle_id": lifecycle_id,
                "command_result": "queued",
            }
        ]
        runtime.decision_trace = {
            "target_decisions": [
                {
                    "covers": [
                        {
                            "cover_id": "cover_one",
                            "command": {
                                "trace": {"command_result": {"details": {}}}
                            },
                        }
                    ]
                }
            ]
        }
        self.engine._decision_target_traces["room"] = []

    async def test_source_hold_cancels_only_its_sector_and_persists_trace(self):
        south = self._plan(
            "cover_one",
            rule="solar",
            sector_id="south",
            group_id="layer",
        )
        west = self._plan(
            "cover_two",
            rule="solar",
            sector_id="west",
            group_id="layer_west",
        )
        self.assertEqual(south.status.value, "planned")
        self.assertEqual(west.status.value, "queued")
        self._seed_target_trace(south.ledger.lifecycle_id)

        cancelled = await self.engine._cancel_pending_normal_lifecycles(
            "room",
            "selected_sun_source_unavailable",
            sector_id="south",
        )

        self.assertEqual(cancelled, ("cover_one",))
        south_entry = self.engine.command_planner.ledger_entry("cover_one")
        west_entry = self.engine.command_planner.ledger_entry("cover_two")
        self.assertEqual(south_entry.result.value, "cancelled")
        self.assertEqual(
            south_entry.failure_reason, "selected_sun_source_unavailable"
        )
        self.assertEqual(west_entry.result.value, "queued")
        self.assertEqual(
            [step.cover_id for step in self.engine.command_planner.pending_steps],
            ["cover_two"],
        )
        self.assertEqual(
            self.engine.store.data["command_ledger"]["cover_one"]["result"],
            "cancelled",
        )
        self.assertEqual(
            [step["cover_id"] for step in self.engine.store.queued_commands()],
            ["cover_two"],
        )
        self.assertIsNotNone(self.engine._command_step_timer_unsub)

        target = self.engine.rooms["room"].targets[0]
        self.assertEqual(target["command_result"], "cancelled")
        self.assertEqual(
            target["command_reason_code"],
            "selected_sun_source_unavailable",
        )
        command_result = self.engine.rooms["room"].decision_trace[
            "target_decisions"
        ][0]["covers"][0]["command"]["trace"]["command_result"]
        self.assertEqual(command_result["status"], "cancelled")
        self.assertEqual(
            command_result["reason_code"], "selected_sun_source_unavailable"
        )

    async def test_quality_hold_does_not_cancel_heat_in_the_same_sector(self):
        normal = self._plan(
            "cover_one",
            rule="comfort",
            sector_id="south",
            group_id="layer",
        )
        await self.engine._cancel_pending_normal_lifecycles(
            "room",
            "normal_input_quality_invalid_hold",
            sector_id="south",
        )
        self.assertEqual(
            self.engine.command_planner.ledger_entry("cover_one").result.value,
            "cancelled",
        )

        heat = self._plan(
            "cover_one",
            rule="heat",
            sector_id="south",
            group_id="layer",
            stagger_seconds=0.0,
        )
        self.assertNotEqual(normal.ledger.lifecycle_id, heat.ledger.lifecycle_id)
        self.assertEqual(heat.status.value, "planned")

        cancelled = await self.engine._cancel_pending_normal_lifecycles(
            "room",
            "normal_input_quality_invalid_hold",
            sector_id="south",
        )

        self.assertEqual(cancelled, ())
        self.assertEqual(
            self.engine.command_planner.ledger_entry("cover_one").result.value,
            "planned",
        )

    async def test_full_room_hold_cancels_non_safety_sent_lifecycle(self):
        heat = self._plan(
            "cover_one",
            rule="heat",
            sector_id="south",
            group_id="layer",
            stagger_seconds=0.0,
        )
        self.engine.command_planner.take_due(now=self.now)
        safety = self._plan(
            "cover_two",
            rule="safety",
            sector_id="west",
            group_id="layer_west",
            safety=True,
            stagger_seconds=0.0,
        )

        cancelled = await self.engine._cancel_pending_normal_lifecycles(
            "room",
            "room_automation_paused",
            include_non_safety=True,
        )

        self.assertEqual(cancelled, ("cover_one",))
        heat_entry = self.engine.command_planner.ledger_entry("cover_one")
        safety_entry = self.engine.command_planner.ledger_entry("cover_two")
        self.assertEqual(heat_entry.lifecycle_id, heat.ledger.lifecycle_id)
        self.assertEqual(heat_entry.result.value, "cancelled")
        self.assertIsNone(heat_entry.expected_deadline)
        self.assertEqual(safety_entry.lifecycle_id, safety.ledger.lifecycle_id)
        self.assertEqual(safety_entry.result.value, "planned")
