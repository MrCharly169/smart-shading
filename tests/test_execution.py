"""Deterministic tests for the pure command planner/executor boundary."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "custom_components" / "smart_shading" / "execution.py"
SPEC = importlib.util.spec_from_file_location("smart_shading_execution_test", MODULE_PATH)
assert SPEC and SPEC.loader
execution = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = execution
SPEC.loader.exec_module(execution)

CommandContext = execution.CommandContext
CommandLedgerEntry = execution.CommandLedgerEntry
CommandPlanner = execution.CommandPlanner
CommandRequest = execution.CommandRequest
CommandResult = execution.CommandResult
CommandTarget = execution.CommandTarget
FeedbackQuality = execution.FeedbackQuality


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **values: float) -> datetime:
        self.now += timedelta(**values)
        return self.now


class CommandPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.planner = CommandPlanner(self.clock)

    @staticmethod
    def request(
        cover_id: str = "cover.study",
        *,
        profile: str = "roller_shutter",
        position: float | None = 0,
        tilt: float | None = None,
        current_position: float | None = 100,
        current_tilt: float | None = None,
        rule: str = "solar",
        priority: int = 100,
        safety: bool = False,
        feedback_quality: FeedbackQuality = FeedbackQuality.TRUSTED,
        retry_limit: int = 1,
        verification_seconds: float = 10,
        settle_seconds: float = 7,
        opening_order: str = "height_then_tilt",
        stagger_seconds: float = 0,
        stagger_scope: str | None = None,
        room_id: str = "study",
        constraints: tuple[str, ...] = (),
        allow_automatic_reverse: bool = True,
    ) -> CommandRequest:
        return CommandRequest(
            cover_id=cover_id,
            profile=profile,
            target=CommandTarget(position=position, tilt=tilt),
            rule=rule,
            reason_code=f"{rule}_matched",
            context=CommandContext(room_id, "south", "window_group"),
            priority=priority,
            current_position=current_position,
            current_tilt=current_tilt,
            position_tolerance=2,
            tilt_tolerance=2,
            feedback_quality=feedback_quality,
            verification_delay=timedelta(seconds=verification_seconds),
            retry_limit=retry_limit,
            settle_delay=timedelta(seconds=settle_seconds),
            opening_order=opening_order,
            constraint_reasons=constraints,
            stagger_seconds=stagger_seconds,
            stagger_scope=stagger_scope,
            safety=safety,
            allow_automatic_reverse=allow_automatic_reverse,
        )

    def test_persisted_ledger_keeps_ownership_context_targets_and_deadline(self):
        plan = self.planner.plan(self.request())
        self.assertEqual(plan.status, CommandResult.PLANNED)
        self.planner.take_due()
        original = self.planner.ledger_entry("cover.study")
        self.assertIsNotNone(original)
        assert original is not None
        self.assertTrue(original.owned_by_smart_shading)
        self.assertEqual(original.owner, "smart_shading")
        self.assertEqual(original.context.group_id, "window_group")
        self.assertEqual(original.target.position, 0)
        self.assertEqual(original.result, CommandResult.SENT)
        self.assertEqual(original.expected_deadline, self.clock.now + timedelta(seconds=10))

        serialized = original.to_dict()
        restored = CommandLedgerEntry.from_dict(serialized)
        self.assertEqual(restored.to_dict(), serialized)

        recovered_planner = CommandPlanner(self.clock)
        recovered_planner.restore_ledger({"cover.study": serialized})
        recovered = recovered_planner.ledger_entry("cover.study")
        self.assertIsNotNone(recovered)
        assert recovered is not None
        self.assertTrue(recovered.owned_by_smart_shading)
        self.assertEqual(recovered.expected_deadline, original.expected_deadline)
        self.assertEqual(recovered.last_valid_position, 100)
        replacement = recovered_planner.plan(
            self.request(position=50, current_position=100)
        )
        self.assertNotEqual(replacement.ledger.lifecycle_id, original.lifecycle_id)

    def test_corrupt_truthy_text_cannot_restore_automatic_reverse_or_ownership(self):
        """Persisted booleans fail closed instead of trusting strings."""
        plan = self.planner.plan(
            self.request(allow_automatic_reverse=False)
        )
        payload = plan.ledger.to_dict()
        payload["allow_automatic_reverse"] = "false"
        payload["owned_by_smart_shading"] = "false"

        restored = CommandLedgerEntry.from_dict(payload)

        self.assertFalse(restored.allow_automatic_reverse)
        self.assertFalse(restored.owned_by_smart_shading)

    def test_pending_steps_round_trip_and_reject_stale_lifecycle(self):
        original = self.planner.plan(
            self.request(profile="venetian", position=20, tilt=35, settle_seconds=9)
        )
        ledger_payload = self.planner.export_ledger()
        steps_payload = self.planner.export_pending_steps()

        recovered = CommandPlanner(self.clock)
        recovered.restore_ledger(ledger_payload)
        restored_steps = recovered.restore_pending_steps(steps_payload)
        self.assertEqual(
            [step.to_dict() for step in restored_steps], steps_payload
        )
        self.assertEqual(
            [step.axis for step in recovered.take_due()], ["position"]
        )

        stale_payload = [dict(step) for step in steps_payload]
        stale_payload[0]["lifecycle_id"] = "obsolete:99"
        pending_before = recovered.pending_steps
        with self.assertRaisesRegex(ValueError, "stale lifecycle"):
            recovered.restore_pending_steps(stale_payload)
        self.assertEqual(recovered.pending_steps, pending_before)
        self.assertEqual(original.ledger.pending_axes, ("position", "tilt"))

    def test_constraints_block_and_current_target_is_suppressed(self):
        blocked = self.planner.plan(
            self.request(constraints=("unsafe_window_closing_blocked",))
        )
        self.assertEqual(blocked.status, CommandResult.BLOCKED)
        self.assertEqual(blocked.reason_code, "unsafe_window_closing_blocked")
        self.assertEqual(blocked.steps, ())
        self.assertEqual(blocked.ledger.result, CommandResult.BLOCKED)

        suppressed = self.planner.plan(
            self.request(
                cover_id="cover.already_correct",
                position=80,
                current_position=81,
            )
        )
        self.assertEqual(suppressed.status, CommandResult.SUPPRESSED)
        self.assertEqual(suppressed.reason_code, "target_within_tolerance")
        self.assertEqual(suppressed.steps, ())
        self.assertTrue(suppressed.ledger.target_reached)

    def test_new_constraint_cancels_stale_queued_work(self):
        original = self.planner.plan(
            self.request(profile="venetian", position=0, tilt=0, settle_seconds=30)
        )
        blocked = self.planner.plan(
            self.request(
                profile="venetian",
                position=0,
                tilt=0,
                constraints=("unsafe_window_closing_blocked",),
            )
        )
        self.assertEqual(blocked.status, CommandResult.BLOCKED)
        self.assertEqual(
            [step.step_id for step in blocked.cancelled_steps],
            [step.step_id for step in original.steps],
        )
        self.assertEqual(self.planner.pending_steps, ())

    def test_venetian_height_precedes_tilt_and_tilt_only_stays_single_axis(self):
        plan = self.planner.plan(
            self.request(
                profile="venetian",
                position=20,
                tilt=35,
                current_position=100,
                current_tilt=100,
                settle_seconds=9,
            )
        )
        self.assertEqual([step.axis for step in plan.steps], ["position", "tilt"])
        self.assertEqual(plan.steps[0].execute_at, self.clock.now)
        self.assertEqual(
            plan.steps[1].execute_at, self.clock.now + timedelta(seconds=9)
        )
        self.assertFalse(plan.steps[0].final_step)
        self.assertTrue(plan.steps[1].final_step)
        self.assertEqual([step.axis for step in self.planner.take_due()], ["position"])
        self.clock.advance(seconds=9)
        self.assertEqual([step.axis for step in self.planner.take_due()], ["tilt"])

        tilt_only_planner = CommandPlanner(self.clock)
        tilt_only = tilt_only_planner.plan(
            self.request(
                cover_id="cover.tilt_only",
                profile="vertical_blind",
                position=20,
                tilt=35,
                current_position=20,
                current_tilt=100,
            )
        )
        self.assertEqual([step.axis for step in tilt_only.steps], ["tilt"])

    def test_venetian_can_open_slats_before_raising_when_profile_requires_it(self):
        opening = self.planner.plan(
            self.request(
                profile="venetian",
                position=100,
                tilt=0,
                current_position=0,
                current_tilt=100,
                settle_seconds=12,
                opening_order="tilt_then_height",
            )
        )
        self.assertEqual([step.axis for step in opening.steps], ["tilt", "position"])
        self.assertEqual(opening.steps[0].execute_at, self.clock.now)
        self.assertEqual(
            opening.steps[1].execute_at,
            self.clock.now + timedelta(seconds=12),
        )
        self.assertEqual(opening.ledger.opening_order, "tilt_then_height")

        # The same profile still uses the conservative height-first sequence
        # when closing, and a tilt-only correction remains one command.
        closing = CommandPlanner(self.clock).plan(
            self.request(
                profile="venetian",
                position=0,
                tilt=100,
                current_position=100,
                current_tilt=0,
                opening_order="tilt_then_height",
            )
        )
        self.assertEqual([step.axis for step in closing.steps], ["position", "tilt"])
        tilt_only = CommandPlanner(self.clock).plan(
            self.request(
                profile="venetian",
                position=100,
                tilt=0,
                current_position=100,
                current_tilt=100,
                opening_order="tilt_then_height",
            )
        )
        self.assertEqual([step.axis for step in tilt_only.steps], ["tilt"])
        self.assertTrue(tilt_only.steps[0].final_step)
        self.assertEqual(tilt_only.steps[0].execute_at, self.clock.now)

    def test_safety_replaces_stale_sequence_and_cancels_queued_tilt(self):
        normal = self.planner.plan(
            self.request(profile="venetian", position=0, tilt=0, settle_seconds=30)
        )
        normal_lifecycle = normal.ledger.lifecycle_id
        self.assertEqual([step.axis for step in self.planner.take_due()], ["position"])
        self.assertEqual([step.axis for step in self.planner.pending_steps], ["tilt"])

        self.clock.advance(seconds=1)
        safety = self.planner.plan(
            self.request(
                profile="venetian",
                position=100,
                tilt=100,
                current_position=0,
                current_tilt=0,
                rule="safety",
                priority=1,
                safety=True,
            )
        )
        self.assertEqual(safety.reason_code, "safety_replacement")
        self.assertEqual([step.axis for step in safety.cancelled_steps], ["tilt"])
        self.assertTrue(all(step.lifecycle_id != normal_lifecycle for step in self.planner.pending_steps))
        self.assertEqual([step.axis for step in safety.steps], ["position", "tilt"])
        self.assertEqual(safety.steps[0].execute_at, self.clock.now)

    def test_stagger_queues_normal_commands_but_safety_bypasses_the_queue(self):
        first = self.planner.plan(
            self.request("cover.one", stagger_seconds=15)
        )
        second = self.planner.plan(
            self.request("cover.two", stagger_seconds=15)
        )
        self.assertEqual(first.status, CommandResult.PLANNED)
        self.assertEqual(second.status, CommandResult.QUEUED)
        self.assertEqual(second.steps[0].execute_at, self.clock.now + timedelta(seconds=15))

        safety = self.planner.plan(
            self.request(
                "cover.two",
                position=100,
                current_position=0,
                rule="safety",
                safety=True,
            )
        )
        self.assertEqual(safety.steps[0].execute_at, self.clock.now)
        self.assertEqual([step.cover_id for step in safety.cancelled_steps], ["cover.two"])
        self.assertNotIn("cover.two", [step.cover_id for step in self.planner.pending_steps if step.execute_at > self.clock.now])

    def test_restored_stagger_queue_reserves_the_next_normal_slot(self):
        """A restart must not let a new cover jump ahead of persisted work."""

        self.planner.plan(self.request("cover.one", stagger_seconds=15))
        second = self.planner.plan(self.request("cover.two", stagger_seconds=15))
        self.assertEqual(second.status, CommandResult.QUEUED)

        recovered = CommandPlanner(self.clock)
        recovered.restore_ledger(self.planner.export_ledger())
        recovered.restore_pending_steps(self.planner.export_pending_steps())

        third = recovered.plan(self.request("cover.three", stagger_seconds=15))
        self.assertEqual(third.status, CommandResult.QUEUED)
        self.assertEqual(
            third.steps[0].execute_at,
            self.clock.now + timedelta(seconds=30),
        )
        self.assertEqual(
            [step.cover_id for step in recovered.pending_steps],
            ["cover.one", "cover.two", "cover.three"],
        )

    def test_restored_house_stagger_scope_stays_shared_across_rooms(self):
        """A persisted house queue must not become room-local after restart."""
        self.planner.plan(
            self.request(
                "cover.study", stagger_seconds=20, stagger_scope="house", room_id="study"
            )
        )
        second = self.planner.plan(
            self.request(
                "cover.living", stagger_seconds=20, stagger_scope="house", room_id="living"
            )
        )
        self.assertEqual(second.status, CommandResult.QUEUED)
        self.assertEqual(
            second.steps[0].execute_at, self.clock.now + timedelta(seconds=20)
        )

        recovered = CommandPlanner(self.clock)
        recovered.restore_ledger(self.planner.export_ledger())
        recovered.restore_pending_steps(self.planner.export_pending_steps())

        third = recovered.plan(
            self.request(
                "cover.bedroom", stagger_seconds=20, stagger_scope="house", room_id="bedroom"
            )
        )
        self.assertEqual(third.status, CommandResult.QUEUED)
        self.assertEqual(
            third.steps[0].execute_at, self.clock.now + timedelta(seconds=40)
        )
        self.assertEqual(
            [step.cover_id for step in recovered.pending_steps],
            ["cover.study", "cover.living", "cover.bedroom"],
        )

    def test_higher_priority_target_replaces_lower_priority_queue(self):
        low = self.planner.plan(
            self.request("cover.priority", stagger_seconds=20, priority=100)
        )
        high = self.planner.plan(
            self.request(
                "cover.priority",
                position=50,
                current_position=100,
                priority=200,
                rule="heat",
            )
        )
        self.assertEqual(high.status, CommandResult.PLANNED)
        self.assertEqual(high.steps[0].target, 50)
        self.assertEqual([step.step_id for step in high.cancelled_steps], [step.step_id for step in low.steps])
        self.assertEqual([step.target for step in self.planner.pending_steps], [50])

    def test_unchanged_active_target_is_suppressed_without_duplicate_steps(self):
        first = self.planner.plan(self.request())
        repeated = self.planner.plan(self.request())
        self.assertEqual(repeated.status, CommandResult.SUPPRESSED)
        self.assertEqual(repeated.reason_code, "target_already_active")
        self.assertEqual(repeated.steps, ())
        self.assertEqual(
            [step.step_id for step in self.planner.pending_steps],
            [step.step_id for step in first.steps],
        )

    def test_bounded_verification_retries_once_then_marks_target_not_reached(self):
        plan = self.planner.plan(self.request(retry_limit=1, verification_seconds=5))
        self.planner.take_due()
        entry = self.planner.ledger_entry("cover.study")
        self.assertEqual(entry.result, CommandResult.SENT)
        self.assertEqual(entry.retry_count, 0)

        self.clock.advance(seconds=5)
        first_verification = self.planner.verify_due()
        self.assertEqual(len(first_verification), 1)
        self.assertEqual(first_verification[0].status, CommandResult.PLANNED)
        self.assertEqual(first_verification[0].reason_code, "verification_retry_planned")
        self.assertEqual(entry.retry_count, 1)
        self.assertEqual([step.axis for step in first_verification[0].steps], ["position"])

        self.planner.take_due()
        self.clock.advance(seconds=5)
        final_verification = self.planner.verify_due()
        self.assertEqual(len(final_verification), 1)
        self.assertEqual(final_verification[0].status, CommandResult.TARGET_NOT_REACHED)
        self.assertFalse(entry.target_reached)
        self.assertEqual(entry.failure_reason, "feedback_not_at_target_after_retry_limit")
        self.assertEqual(self.planner.pending_steps, ())

    def test_trusted_feedback_completes_lifecycle_and_no_feedback_never_retries(self):
        self.planner.plan(self.request())
        self.planner.take_due()
        reached = self.planner.record_feedback("cover.study", position=0)
        self.assertEqual(reached.result, CommandResult.TARGET_REACHED)
        self.assertTrue(reached.target_reached)
        self.clock.advance(minutes=1)
        self.assertEqual(self.planner.verify_due(), ())

        no_feedback_planner = CommandPlanner(self.clock)
        no_feedback_planner.plan(
            self.request(
                cover_id="cover.binary",
                profile="binary_cover",
                feedback_quality=FeedbackQuality.NONE,
                retry_limit=3,
            )
        )
        no_feedback_planner.take_due()
        entry = no_feedback_planner.ledger_entry("cover.binary")
        self.assertEqual(entry.result, CommandResult.SENT)
        self.assertIsNone(entry.expected_deadline)
        self.clock.advance(minutes=5)
        self.assertEqual(no_feedback_planner.verify_due(), ())
        self.assertEqual(entry.retry_count, 0)

    def test_dispatch_failure_and_manual_ownership_release_are_final_and_cancelable(self):
        self.planner.plan(
            self.request(profile="venetian", position=0, tilt=0, settle_seconds=20)
        )
        self.planner.take_due()
        failed = self.planner.mark_failed("cover.study", "cover_service_unavailable")
        self.assertEqual(failed.status, CommandResult.FAILED)
        self.assertEqual([step.axis for step in failed.cancelled_steps], ["tilt"])
        self.assertEqual(failed.ledger.failure_reason, "cover_service_unavailable")

        replacement = self.planner.plan(self.request())
        released = self.planner.release_ownership("cover.study", "external_numeric_movement")
        self.assertEqual(released.status, CommandResult.CANCELLED)
        self.assertFalse(released.ledger.owned_by_smart_shading)
        self.assertEqual(released.ledger.owner, "external")
        self.assertEqual(released.ledger.failure_reason, "external_numeric_movement")
        self.assertEqual(len(released.cancelled_steps), len(replacement.steps))

    def test_unowned_cover_blocks_normal_reversal_when_disabled(self):
        self.planner.plan(
            self.request(position=0, allow_automatic_reverse=False)
        )
        released = self.planner.release_ownership(
            "cover.study", "external_numeric_movement"
        )
        self.assertIsNotNone(released)
        assert released is not None
        self.assertFalse(released.ledger.owned_by_smart_shading)

        blocked = self.planner.plan(
            self.request(
                position=0,
                current_position=100,
                allow_automatic_reverse=False,
            )
        )

        self.assertEqual(blocked.status, CommandResult.BLOCKED)
        self.assertEqual(blocked.reason_code, "automatic_reverse_not_allowed")
        self.assertEqual(blocked.steps, ())
        self.assertFalse(blocked.ledger.owned_by_smart_shading)
        self.assertEqual(
            blocked.ledger.failure_reason, "automatic_reverse_not_allowed"
        )
        self.assertEqual(
            self.planner.export_ledger()["cover.study"]["result"], "blocked"
        )
        self.assertEqual(
            self.planner.export_ledger()["cover.study"]["failure_reason"],
            "automatic_reverse_not_allowed",
        )

    def test_startup_noop_does_not_imply_external_ownership(self):
        """A cover already at its initial target may still be automated later."""
        no_op = self.planner.plan(
            self.request(
                position=100,
                current_position=100,
                allow_automatic_reverse=False,
            )
        )
        self.assertEqual(no_op.status, CommandResult.SUPPRESSED)
        self.assertEqual(no_op.ledger.owner, "none")

        movement = self.planner.plan(
            self.request(
                position=0,
                current_position=100,
                allow_automatic_reverse=False,
            )
        )

        self.assertEqual(movement.status, CommandResult.PLANNED)
        self.assertEqual([step.axis for step in movement.steps], ["position"])

    def test_unowned_active_target_is_cancelled_before_normal_reverse_is_blocked(self):
        original = self.planner.plan(
            self.request(
                profile="venetian",
                position=0,
                tilt=0,
                allow_automatic_reverse=False,
            )
        )
        # This represents persisted external ownership observed between
        # planning and dispatch. The old sequence must not survive the block.
        original.ledger.owned_by_smart_shading = False
        original.ledger.owner = "external"

        blocked = self.planner.plan(
            self.request(
                profile="venetian",
                position=0,
                tilt=0,
                current_position=100,
                current_tilt=100,
                allow_automatic_reverse=False,
            )
        )

        self.assertEqual(blocked.status, CommandResult.BLOCKED)
        self.assertEqual(blocked.reason_code, "automatic_reverse_not_allowed")
        self.assertEqual(
            [step.step_id for step in blocked.cancelled_steps],
            [step.step_id for step in original.steps],
        )
        self.assertEqual(self.planner.pending_steps, ())

    def test_safety_can_reverse_an_unowned_cover_and_noop_stays_suppressed(self):
        self.planner.plan(
            self.request(position=0, allow_automatic_reverse=False)
        )
        self.planner.release_ownership(
            "cover.study", "external_numeric_movement"
        )

        no_op = self.planner.plan(
            self.request(
                position=100,
                current_position=100,
                allow_automatic_reverse=False,
            )
        )
        self.assertEqual(no_op.status, CommandResult.SUPPRESSED)
        self.assertEqual(no_op.reason_code, "target_within_tolerance")

        safety = self.planner.plan(
            self.request(
                position=0,
                current_position=100,
                rule="safety",
                safety=True,
                allow_automatic_reverse=False,
            )
        )
        self.assertEqual(safety.status, CommandResult.PLANNED)
        self.assertEqual(safety.reason_code, "target_planned")
        self.assertTrue(safety.ledger.owned_by_smart_shading)
        self.assertEqual([step.axis for step in safety.steps], ["position"])


if __name__ == "__main__":
    unittest.main()
