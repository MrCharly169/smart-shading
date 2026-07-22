"""Pure command planning and lifecycle primitives for Smart Shading.

This module intentionally has no Home Assistant imports.  It converts an
already-resolved logical cover target into deterministic command steps and
keeps the minimum persisted state needed to reason about ownership, feedback
and bounded target verification.  An HA adapter can dispatch ``CommandStep``
objects, feed real feedback back through :meth:`CommandPlanner.record_feedback`
and persist :meth:`CommandPlanner.export_ledger`.

The module does *not* send services, sleep, or poll.  The caller owns the
clock and calls ``take_due`` / ``verify_due`` at the appropriate event or
timer boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import math
from typing import Callable, Iterable, Mapping


SEQUENCED_PROFILES = frozenset({"venetian", "vertical_blind"})
SAFETY_PRIORITY = 1_000
OPENING_ORDER_HEIGHT_THEN_TILT = "height_then_tilt"
OPENING_ORDER_TILT_THEN_HEIGHT = "tilt_then_height"
OPENING_ORDERS = frozenset(
    {OPENING_ORDER_HEIGHT_THEN_TILT, OPENING_ORDER_TILT_THEN_HEIGHT}
)


class CommandResult(str, Enum):
    """Externally useful lifecycle states for one cover target."""

    PLANNED = "planned"
    QUEUED = "queued"
    SENT = "sent"
    SUPPRESSED = "suppressed"
    BLOCKED = "blocked"
    TARGET_REACHED = "target_reached"
    TARGET_NOT_REACHED = "target_not_reached"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FeedbackQuality(str, Enum):
    """How safely feedback can be used for target verification."""

    TRUSTED = "trusted_position"
    UNRELIABLE = "unreliable_or_intermediate"
    END_POSITIONS = "end_positions_only"
    NONE = "no_usable_position_feedback"


def _as_datetime(value: object | None) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise TypeError(f"Unsupported datetime value: {value!r}")


def _as_float(value: object | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _opening_order(value: object | None) -> str:
    """Return a persisted sequencer policy without trusting unknown values."""

    candidate = str(value or OPENING_ORDER_HEIGHT_THEN_TILT)
    return (
        candidate
        if candidate in OPENING_ORDERS
        else OPENING_ORDER_HEIGHT_THEN_TILT
    )


@dataclass(frozen=True)
class CommandContext:
    """Stable hierarchy context for a planned physical command."""

    room_id: str
    sector_id: str | None = None
    group_id: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "room_id": self.room_id,
            "sector_id": self.sector_id,
            "group_id": self.group_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "CommandContext":
        return cls(
            room_id=str(value.get("room_id") or ""),
            sector_id=(
                str(value["sector_id"])
                if value.get("sector_id") not in (None, "")
                else None
            ),
            group_id=(
                str(value["group_id"])
                if value.get("group_id") not in (None, "")
                else None
            ),
        )


@dataclass(frozen=True)
class CommandTarget:
    """Logical target in Home Assistant position/tilt coordinates."""

    position: float | None = None
    tilt: float | None = None

    def to_dict(self) -> dict[str, float | None]:
        return {"position": self.position, "tilt": self.tilt}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "CommandTarget":
        return cls(
            position=_as_float(value.get("position")),
            tilt=_as_float(value.get("tilt")),
        )


@dataclass(frozen=True)
class CommandRequest:
    """A resolved target presented to the physical command planner.

    ``constraint_reasons`` is intentionally declarative: decision and
    constraint layers can make a command impossible without this module
    knowing Home Assistant, windows, locks, or safety entities.
    """

    cover_id: str
    profile: str
    target: CommandTarget
    rule: str
    reason_code: str
    context: CommandContext
    priority: int = 0
    current_position: float | None = None
    current_tilt: float | None = None
    position_tolerance: float = 5.0
    tilt_tolerance: float = 5.0
    feedback_quality: FeedbackQuality = FeedbackQuality.TRUSTED
    verification_delay: timedelta = timedelta(seconds=30)
    retry_limit: int = 1
    settle_delay: timedelta = timedelta(seconds=5)
    opening_order: str = OPENING_ORDER_HEIGHT_THEN_TILT
    constraint_reasons: tuple[str, ...] = ()
    stagger_seconds: float = 0.0
    stagger_scope: str | None = None
    safety: bool = False
    safety_bypasses_stagger: bool = True
    # Direct planner callers must opt in just like the customer-facing
    # Advanced setting; external ownership is never reclaimed by default.
    allow_automatic_reverse: bool = False

    @property
    def effective_priority(self) -> int:
        return max(self.priority, SAFETY_PRIORITY) if self.safety else self.priority


@dataclass(frozen=True)
class CommandStep:
    """One executable axis command; adapters map this to a real service call."""

    step_id: str
    lifecycle_id: str
    cover_id: str
    axis: str
    target: float
    execute_at: datetime
    priority: int
    rule: str
    reason_code: str
    context: CommandContext
    stagger_scope: str
    final_step: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "step_id": self.step_id,
            "lifecycle_id": self.lifecycle_id,
            "cover_id": self.cover_id,
            "axis": self.axis,
            "target": self.target,
            "execute_at": self.execute_at.isoformat(),
            "priority": self.priority,
            "rule": self.rule,
            "reason_code": self.reason_code,
            "context": self.context.to_dict(),
            "stagger_scope": self.stagger_scope,
            "final_step": self.final_step,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "CommandStep":
        """Restore a JSON-safe pending-step representation.

        Lifecycle membership is intentionally checked by
        :meth:`CommandPlanner.restore_pending_steps`, where the corresponding
        ledger entry is available.
        """

        context_data = value.get("context")
        execute_at = _as_datetime(value.get("execute_at"))
        axis = str(value.get("axis") or "")
        target = _as_float(value.get("target"))
        if not isinstance(context_data, Mapping):
            raise ValueError("Pending command step needs a context mapping")
        if execute_at is None:
            raise ValueError("Pending command step needs execute_at")
        if axis not in {"position", "tilt"}:
            raise ValueError(f"Unsupported pending command axis {axis!r}")
        if target is None:
            raise ValueError("Pending command step needs a finite target")
        step_id = str(value.get("step_id") or "")
        lifecycle_id = str(value.get("lifecycle_id") or "")
        cover_id = str(value.get("cover_id") or "")
        if not step_id or not lifecycle_id or not cover_id:
            raise ValueError("Pending command step lacks a stable identifier")
        return cls(
            step_id=step_id,
            lifecycle_id=lifecycle_id,
            cover_id=cover_id,
            axis=axis,
            target=target,
            execute_at=execute_at,
            priority=int(value.get("priority") or 0),
            rule=str(value.get("rule") or ""),
            reason_code=str(value.get("reason_code") or ""),
            context=CommandContext.from_dict(context_data),
            stagger_scope=str(value.get("stagger_scope") or ""),
            final_step=bool(value.get("final_step", False)),
        )


@dataclass
class CommandLedgerEntry:
    """Persistable ownership and execution record for one controlled cover."""

    cover_id: str
    lifecycle_id: str
    owner: str
    rule: str
    reason_code: str
    context: CommandContext
    profile: str
    target: CommandTarget
    created_at: datetime
    updated_at: datetime
    priority: int
    feedback_quality: FeedbackQuality
    retry_limit: int
    verification_delay_seconds: float
    settle_delay_seconds: float
    position_tolerance: float
    tilt_tolerance: float
    result: CommandResult
    owned_by_smart_shading: bool
    allow_automatic_reverse: bool
    stagger_scope: str
    opening_order: str
    command_at: datetime | None = None
    expected_deadline: datetime | None = None
    target_reached: bool | None = None
    retry_count: int = 0
    last_valid_position: float | None = None
    last_valid_tilt: float | None = None
    pending_axes: tuple[str, ...] = ()
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe representation suitable for runtime storage."""

        return {
            "schema": 2,
            "cover_id": self.cover_id,
            "lifecycle_id": self.lifecycle_id,
            "owner": self.owner,
            "rule": self.rule,
            "reason_code": self.reason_code,
            "context": self.context.to_dict(),
            "profile": self.profile,
            "target": self.target.to_dict(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "priority": self.priority,
            "feedback_quality": self.feedback_quality.value,
            "retry_limit": self.retry_limit,
            "verification_delay_seconds": self.verification_delay_seconds,
            "settle_delay_seconds": self.settle_delay_seconds,
            "position_tolerance": self.position_tolerance,
            "tilt_tolerance": self.tilt_tolerance,
            "result": self.result.value,
            "owned_by_smart_shading": self.owned_by_smart_shading,
            "allow_automatic_reverse": self.allow_automatic_reverse,
            "stagger_scope": self.stagger_scope,
            "opening_order": self.opening_order,
            "command_at": self.command_at.isoformat() if self.command_at else None,
            "expected_deadline": (
                self.expected_deadline.isoformat() if self.expected_deadline else None
            ),
            "target_reached": self.target_reached,
            "retry_count": self.retry_count,
            "last_valid_position": self.last_valid_position,
            "last_valid_tilt": self.last_valid_tilt,
            "pending_axes": list(self.pending_axes),
            "failure_reason": self.failure_reason,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "CommandLedgerEntry":
        """Restore an entry written by :meth:`to_dict`.

        Unknown keys are ignored deliberately so future storage migrations can
        be performed by the integration without making this pure component
        brittle.
        """

        target_data = value.get("target")
        context_data = value.get("context")
        if not isinstance(target_data, Mapping) or not isinstance(context_data, Mapping):
            raise ValueError("Ledger entry needs target and context mappings")
        created_at = _as_datetime(value.get("created_at"))
        updated_at = _as_datetime(value.get("updated_at"))
        if created_at is None or updated_at is None:
            raise ValueError("Ledger entry needs created_at and updated_at")
        return cls(
            cover_id=str(value.get("cover_id") or ""),
            lifecycle_id=str(value.get("lifecycle_id") or ""),
            owner=str(value.get("owner") or "smart_shading"),
            rule=str(value.get("rule") or ""),
            reason_code=str(value.get("reason_code") or ""),
            context=CommandContext.from_dict(context_data),
            profile=str(value.get("profile") or ""),
            target=CommandTarget.from_dict(target_data),
            created_at=created_at,
            updated_at=updated_at,
            priority=int(value.get("priority") or 0),
            feedback_quality=FeedbackQuality(
                str(value.get("feedback_quality") or FeedbackQuality.NONE.value)
            ),
            retry_limit=max(0, int(value.get("retry_limit") or 0)),
            verification_delay_seconds=max(
                0.0, float(value.get("verification_delay_seconds") or 0.0)
            ),
            settle_delay_seconds=max(
                0.0, float(value.get("settle_delay_seconds") or 0.0)
            ),
            position_tolerance=max(
                0.0, float(value.get("position_tolerance") or 0.0)
            ),
            tilt_tolerance=max(0.0, float(value.get("tilt_tolerance") or 0.0)),
            result=CommandResult(
                str(value.get("result") or CommandResult.SUPPRESSED.value)
            ),
            owned_by_smart_shading=value.get("owned_by_smart_shading") is True,
            allow_automatic_reverse=value.get("allow_automatic_reverse") is True,
            stagger_scope=str(
                value.get("stagger_scope")
                or CommandContext.from_dict(context_data).room_id
                or "house"
            ),
            opening_order=_opening_order(value.get("opening_order")),
            command_at=_as_datetime(value.get("command_at")),
            expected_deadline=_as_datetime(value.get("expected_deadline")),
            target_reached=(
                bool(value["target_reached"])
                if value.get("target_reached") is not None
                else None
            ),
            retry_count=max(0, int(value.get("retry_count") or 0)),
            last_valid_position=_as_float(value.get("last_valid_position")),
            last_valid_tilt=_as_float(value.get("last_valid_tilt")),
            pending_axes=tuple(str(axis) for axis in value.get("pending_axes", ())),
            failure_reason=(
                str(value["failure_reason"])
                if value.get("failure_reason") not in (None, "")
                else None
            ),
        )


@dataclass(frozen=True)
class PlanResult:
    """Outcome of planning, verification, failure, or cancellation."""

    status: CommandResult
    cover_id: str
    reason_code: str
    steps: tuple[CommandStep, ...]
    ledger: CommandLedgerEntry | None
    cancelled_steps: tuple[CommandStep, ...] = ()


class CommandPlanner:
    """Plan finite, cancelable command lifecycles without executing them.

    The planner stores only state that is useful to persist or inspect.  A
    caller should serialize ``export_ledger`` on normal runtime saves and call
    ``restore_ledger`` after a restart.  Pending command *steps* deliberately
    remain an adapter/scheduler concern; a persisted verification deadline is
    sufficient to detect an overdue command after restart.
    """

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self.ledger: dict[str, CommandLedgerEntry] = {}
        self._steps: list[CommandStep] = []
        self._next_slot_by_scope: dict[str, datetime] = {}
        # A restored queue retains the planned command instants, but older
        # serialized steps intentionally do not carry a copy of the room's
        # stagger setting.  Keep the final restored reservation separately so
        # the first new normal request can apply its current stagger interval
        # after that reservation instead of jumping in front of it.
        self._restored_stagger_slots: dict[str, datetime] = {}
        self._sequence = 0
        self._lifecycle_sequence = 0

    @property
    def pending_steps(self) -> tuple[CommandStep, ...]:
        """Queued steps in deterministic execution order."""

        return tuple(sorted(self._steps, key=self._step_sort_key))

    def ledger_entry(self, cover_id: str) -> CommandLedgerEntry | None:
        return self.ledger.get(cover_id)

    def export_ledger(self) -> dict[str, dict[str, object]]:
        return {
            cover_id: entry.to_dict()
            for cover_id, entry in sorted(self.ledger.items())
        }

    def export_pending_steps(self) -> list[dict[str, object]]:
        """Return the exact queued sequence in JSON-safe execution order."""

        return [step.to_dict() for step in self.pending_steps]

    def restore_ledger(self, values: Mapping[str, Mapping[str, object]]) -> None:
        """Restore persisted ownership/deadline state without restoring calls."""

        self.ledger = {
            str(cover_id): CommandLedgerEntry.from_dict(value)
            for cover_id, value in values.items()
        }
        restored_sequences = [
            int(entry.lifecycle_id.rsplit(":", 1)[-1])
            for entry in self.ledger.values()
            if entry.lifecycle_id.rsplit(":", 1)[-1].isdigit()
        ]
        if restored_sequences:
            self._lifecycle_sequence = max(
                self._lifecycle_sequence, max(restored_sequences)
            )

    def restore_pending_steps(
        self, values: Iterable[Mapping[str, object]]
    ) -> tuple[CommandStep, ...]:
        """Restore a queue only when every step belongs to its live ledger.

        The operation is atomic: malformed, duplicate, stale, cross-cover, or
        otherwise inconsistent data raises ``ValueError`` and leaves the
        current queue unchanged.  This prevents old normal commands from being
        resurrected after a Safety replacement or a restart migration.
        """

        restored = [CommandStep.from_dict(value) for value in values]
        seen_step_ids: set[str] = set()
        by_cover: dict[str, list[CommandStep]] = {}
        for step in restored:
            if step.step_id in seen_step_ids:
                raise ValueError(f"Duplicate pending command step {step.step_id}")
            seen_step_ids.add(step.step_id)
            entry = self.ledger.get(step.cover_id)
            if entry is None:
                raise ValueError(
                    f"Pending command step {step.step_id} has no ledger entry"
                )
            if entry.lifecycle_id != step.lifecycle_id:
                raise ValueError(
                    f"Pending command step {step.step_id} belongs to stale lifecycle"
                )
            if not self._is_active(entry):
                raise ValueError(
                    f"Pending command step {step.step_id} has inactive lifecycle"
                )
            if step.context != entry.context or step.rule != entry.rule:
                raise ValueError(
                    f"Pending command step {step.step_id} does not match ledger context"
                )
            if step.stagger_scope and step.stagger_scope != entry.stagger_scope:
                raise ValueError(
                    f"Pending command step {step.step_id} does not match ledger stagger scope"
                )
            expected_target = (
                entry.target.position if step.axis == "position" else entry.target.tilt
            )
            if expected_target is None or step.target != expected_target:
                raise ValueError(
                    f"Pending command step {step.step_id} does not match ledger target"
                )
            by_cover.setdefault(step.cover_id, []).append(step)

        for cover_id, steps in by_cover.items():
            entry = self.ledger[cover_id]
            axes = tuple(step.axis for step in sorted(steps, key=self._step_sort_key))
            if len(axes) != len(set(axes)) or set(axes) != set(entry.pending_axes):
                raise ValueError(
                    f"Pending command steps for {cover_id} do not match ledger axes"
                )
            final_steps = [step for step in steps if step.final_step]
            if len(final_steps) != 1:
                raise ValueError(
                    f"Pending command steps for {cover_id} need exactly one final step"
                )
            if final_steps[0] != sorted(steps, key=self._step_sort_key)[-1]:
                raise ValueError(
                    f"Pending command final step for {cover_id} is out of order"
                )

        for cover_id, entry in self.ledger.items():
            if entry.pending_axes and cover_id not in by_cover:
                raise ValueError(
                    f"Ledger entry {cover_id} has pending axes but no pending steps"
                )

        self._steps = sorted(restored, key=self._step_sort_key)
        # ``_next_slot_by_scope`` is normally built while ``plan`` receives
        # requests.  It is process-local, so rebuilding only ``_steps`` after
        # Home Assistant restarts would let the next normal command execute at
        # once, ahead of a persisted future stagger reservation.  Group each
        # lifecycle by its first remaining step: a Venetian height/tilt pair
        # is one cover command, not two stagger slots.  Safety is deliberately
        # excluded because it bypasses staggering by contract.
        restored_reservations: dict[str, datetime] = {}
        lifecycle_bases: dict[tuple[str, str], datetime] = {}
        for step in self._steps:
            if step.priority >= SAFETY_PRIORITY:
                continue
            # New records carry the explicit coordination scope.  Old queued
            # records did not, so retain their documented room-local behavior
            # rather than guessing a global house reservation.
            entry = self.ledger[step.cover_id]
            scope = (
                step.stagger_scope
                or entry.stagger_scope
                or step.context.room_id
                or "house"
            )
            lifecycle_key = (scope, step.lifecycle_id)
            current = lifecycle_bases.get(lifecycle_key)
            if current is None or step.execute_at < current:
                lifecycle_bases[lifecycle_key] = step.execute_at
        for (scope, _lifecycle_id), execute_at in lifecycle_bases.items():
            existing = restored_reservations.get(scope)
            if existing is None or execute_at > existing:
                restored_reservations[scope] = execute_at
        self._restored_stagger_slots = restored_reservations
        self._next_slot_by_scope = dict(restored_reservations)
        restored_sequences = [
            int(step.step_id.rsplit(":", 1)[-1])
            for step in restored
            if step.step_id.rsplit(":", 1)[-1].isdigit()
        ]
        if restored_sequences:
            self._sequence = max(self._sequence, max(restored_sequences))
        return self.pending_steps

    def plan(self, request: CommandRequest, *, now: datetime | None = None) -> PlanResult:
        """Create the required command steps or an inspectable no-op result."""

        when = self._now(now)
        existing = self.ledger.get(request.cover_id)
        priority = request.effective_priority
        position_needed, tilt_needed = self._needed_axes(
            request.target,
            request.current_position,
            request.current_tilt,
            request.position_tolerance,
            request.tilt_tolerance,
        )

        if existing and self._is_active(existing):
            if (
                existing.target == request.target
                and existing.priority >= priority
                and not request.safety
                and not request.constraint_reasons
                and existing.owned_by_smart_shading
                and (position_needed or tilt_needed)
            ):
                return PlanResult(
                    CommandResult.SUPPRESSED,
                    request.cover_id,
                    "target_already_active",
                    (),
                    existing,
                )
            if existing.priority > priority and not request.safety:
                return PlanResult(
                    CommandResult.BLOCKED,
                    request.cover_id,
                    "higher_priority_lifecycle_active",
                    (),
                    existing,
                )

        # A new equally or higher-priority decision must make old queued work
        # impossible to dispatch, even if the new decision ends up blocked or
        # suppressed.  Otherwise a stale close can follow a newly opened
        # window, a target already reached by manual feedback, or Safety.
        cancelled = self._cancel_pending_for_cover(request.cover_id)
        if existing and self._is_active(existing):
            existing.result = CommandResult.CANCELLED
            existing.expected_deadline = None
            existing.pending_axes = ()
            existing.updated_at = when
            existing.failure_reason = "replaced_by_newer_target"

        if request.constraint_reasons:
            entry = self._new_entry(
                request,
                when,
                priority=priority,
                result=CommandResult.BLOCKED,
                owned=False,
            )
            entry.failure_reason = ",".join(request.constraint_reasons)
            self.ledger[request.cover_id] = entry
            return PlanResult(
                CommandResult.BLOCKED,
                request.cover_id,
                request.constraint_reasons[0],
                (),
                entry,
                tuple(cancelled),
            )

        if not position_needed and not tilt_needed:
            entry = self._new_entry(
                request,
                when,
                priority=priority,
                result=CommandResult.SUPPRESSED,
                owned=bool(existing and existing.owned_by_smart_shading),
            )
            entry.target_reached = True
            entry.last_valid_position = _as_float(request.current_position)
            entry.last_valid_tilt = _as_float(request.current_tilt)
            self.ledger[request.cover_id] = entry
            return PlanResult(
                CommandResult.SUPPRESSED,
                request.cover_id,
                "target_within_tolerance",
                (),
                entry,
                tuple(cancelled),
            )

        if (
            not request.safety
            and not request.allow_automatic_reverse
            and existing is not None
            and not existing.owned_by_smart_shading
        ):
            # ``release_ownership`` records an externally/manual-controlled
            # cover as not owned by Smart Shading.  A later normal target must
            # not reclaim that position when automatic reversal is disabled.
            # Safety is deliberately exempt: a safety target is an explicit
            # higher-priority intervention, not a normal automation reversal.
            entry = self._new_entry(
                request,
                when,
                priority=priority,
                result=CommandResult.BLOCKED,
                owned=False,
            )
            entry.failure_reason = "automatic_reverse_not_allowed"
            self.ledger[request.cover_id] = entry
            return PlanResult(
                CommandResult.BLOCKED,
                request.cover_id,
                entry.failure_reason,
                (),
                entry,
                tuple(cancelled),
            )

        entry = self._new_entry(
            request,
            when,
            priority=priority,
            result=CommandResult.PLANNED,
            owned=True,
        )
        base = self._execution_base(request, when)
        steps = self._build_steps(
            entry,
            position_needed=position_needed,
            tilt_needed=tilt_needed,
            base=base,
        )
        entry.pending_axes = tuple(step.axis for step in steps)
        if steps and steps[0].execute_at > when:
            entry.result = CommandResult.QUEUED
        self.ledger[request.cover_id] = entry
        self._steps.extend(steps)
        return PlanResult(
            entry.result,
            request.cover_id,
            "safety_replacement" if request.safety and cancelled else "target_planned",
            tuple(steps),
            entry,
            tuple(cancelled),
        )

    def take_due(self, *, now: datetime | None = None) -> tuple[CommandStep, ...]:
        """Return due steps and advance their ledger entries to ``sent``.

        The adapter must call this immediately before it dispatches the returned
        steps.  If a real service call fails, call :meth:`mark_failed` instead
        of pretending feedback will arrive.
        """

        when = self._now(now)
        due = [step for step in self._steps if step.execute_at <= when]
        self._steps = [step for step in self._steps if step.execute_at > when]
        due.sort(key=self._step_sort_key)
        delivered: list[CommandStep] = []
        for step in due:
            entry = self.ledger.get(step.cover_id)
            if entry is None or entry.lifecycle_id != step.lifecycle_id:
                continue
            entry.command_at = when
            entry.updated_at = when
            entry.result = CommandResult.SENT
            entry.failure_reason = None
            entry.pending_axes = tuple(
                axis for axis in entry.pending_axes if axis != step.axis
            )
            if step.final_step and entry.feedback_quality is FeedbackQuality.TRUSTED:
                entry.expected_deadline = when + timedelta(
                    seconds=entry.verification_delay_seconds
                )
            delivered.append(step)
        return tuple(delivered)

    def record_feedback(
        self,
        cover_id: str,
        *,
        position: float | None = None,
        tilt: float | None = None,
        now: datetime | None = None,
    ) -> CommandLedgerEntry | None:
        """Store numeric feedback and complete a trusted target when reached."""

        entry = self.ledger.get(cover_id)
        if entry is None:
            return None
        when = self._now(now)
        valid_position = _as_float(position)
        valid_tilt = _as_float(tilt)
        if valid_position is not None:
            entry.last_valid_position = valid_position
        if valid_tilt is not None:
            entry.last_valid_tilt = valid_tilt
        entry.updated_at = when
        if (
            entry.feedback_quality is FeedbackQuality.TRUSTED
            and entry.expected_deadline is not None
            and self._target_reached(entry)
        ):
            entry.target_reached = True
            entry.result = CommandResult.TARGET_REACHED
            entry.expected_deadline = None
            entry.pending_axes = ()
            entry.failure_reason = None
        return entry

    def verify_due(self, *, now: datetime | None = None) -> tuple[PlanResult, ...]:
        """Perform bounded verification; it never creates an infinite loop."""

        when = self._now(now)
        outcomes: list[PlanResult] = []
        for cover_id, entry in sorted(self.ledger.items()):
            if (
                entry.feedback_quality is not FeedbackQuality.TRUSTED
                or entry.expected_deadline is None
                or entry.expected_deadline > when
                or entry.result is not CommandResult.SENT
            ):
                continue
            if self._target_reached(entry):
                entry.target_reached = True
                entry.result = CommandResult.TARGET_REACHED
                entry.expected_deadline = None
                entry.updated_at = when
                outcomes.append(
                    PlanResult(
                        CommandResult.TARGET_REACHED,
                        cover_id,
                        "target_confirmed_at_deadline",
                        (),
                        entry,
                    )
                )
                continue
            if entry.retry_count >= entry.retry_limit:
                entry.target_reached = False
                entry.result = CommandResult.TARGET_NOT_REACHED
                entry.expected_deadline = None
                entry.updated_at = when
                entry.failure_reason = "feedback_not_at_target_after_retry_limit"
                outcomes.append(
                    PlanResult(
                        CommandResult.TARGET_NOT_REACHED,
                        cover_id,
                        entry.failure_reason,
                        (),
                        entry,
                    )
                )
                continue

            entry.retry_count += 1
            entry.expected_deadline = None
            entry.target_reached = None
            entry.updated_at = when
            retry_request = CommandRequest(
                cover_id=entry.cover_id,
                profile=entry.profile,
                target=entry.target,
                rule=entry.rule,
                reason_code=entry.reason_code,
                context=entry.context,
                priority=entry.priority,
                current_position=entry.last_valid_position,
                current_tilt=entry.last_valid_tilt,
                position_tolerance=entry.position_tolerance,
                tilt_tolerance=entry.tilt_tolerance,
                feedback_quality=entry.feedback_quality,
                verification_delay=timedelta(
                    seconds=entry.verification_delay_seconds
                ),
                retry_limit=entry.retry_limit,
                settle_delay=timedelta(seconds=entry.settle_delay_seconds),
                opening_order=entry.opening_order,
                stagger_scope=entry.stagger_scope,
                allow_automatic_reverse=entry.allow_automatic_reverse,
            )
            position_needed, tilt_needed = self._needed_axes(
                retry_request.target,
                retry_request.current_position,
                retry_request.current_tilt,
                retry_request.position_tolerance,
                retry_request.tilt_tolerance,
            )
            if not position_needed and not tilt_needed:
                entry.target_reached = True
                entry.result = CommandResult.TARGET_REACHED
                outcomes.append(
                    PlanResult(
                        CommandResult.TARGET_REACHED,
                        cover_id,
                        "target_confirmed_before_retry",
                        (),
                        entry,
                    )
                )
                continue
            steps = self._build_steps(
                entry,
                position_needed=position_needed,
                tilt_needed=tilt_needed,
                base=when,
            )
            entry.pending_axes = tuple(step.axis for step in steps)
            entry.result = CommandResult.PLANNED
            self._steps.extend(steps)
            outcomes.append(
                PlanResult(
                    CommandResult.PLANNED,
                    cover_id,
                    "verification_retry_planned",
                    tuple(steps),
                    entry,
                )
            )
        return tuple(outcomes)

    def mark_failed(
        self, cover_id: str, reason_code: str, *, now: datetime | None = None
    ) -> PlanResult | None:
        """Record a dispatch failure and cancel its obsolete queued steps."""

        entry = self.ledger.get(cover_id)
        if entry is None:
            return None
        when = self._now(now)
        cancelled = self._cancel_pending_for_cover(cover_id)
        entry.result = CommandResult.FAILED
        entry.target_reached = False
        entry.expected_deadline = None
        entry.pending_axes = ()
        entry.failure_reason = reason_code
        entry.updated_at = when
        return PlanResult(
            CommandResult.FAILED,
            cover_id,
            reason_code,
            (),
            entry,
            tuple(cancelled),
        )

    def cancel_cover(
        self, cover_id: str, reason_code: str, *, now: datetime | None = None
    ) -> PlanResult | None:
        """Cancel a queued lifecycle, for example after an external override."""

        entry = self.ledger.get(cover_id)
        if entry is None:
            return None
        when = self._now(now)
        cancelled = self._cancel_pending_for_cover(cover_id)
        entry.result = CommandResult.CANCELLED
        entry.expected_deadline = None
        entry.pending_axes = ()
        entry.updated_at = when
        entry.failure_reason = reason_code
        return PlanResult(
            CommandResult.CANCELLED,
            cover_id,
            reason_code,
            (),
            entry,
            tuple(cancelled),
        )

    def release_ownership(
        self, cover_id: str, reason_code: str, *, now: datetime | None = None
    ) -> PlanResult | None:
        """Transfer ownership after confirmed external/manual movement."""

        result = self.cancel_cover(cover_id, reason_code, now=now)
        if result and result.ledger:
            result.ledger.owned_by_smart_shading = False
        return result

    def _new_entry(
        self,
        request: CommandRequest,
        when: datetime,
        *,
        priority: int,
        result: CommandResult,
        owned: bool,
    ) -> CommandLedgerEntry:
        self._lifecycle_sequence += 1
        lifecycle_id = f"{request.cover_id}:{self._lifecycle_sequence}"
        return CommandLedgerEntry(
            cover_id=request.cover_id,
            lifecycle_id=lifecycle_id,
            owner="smart_shading" if owned else "none",
            rule=request.rule,
            reason_code=request.reason_code,
            context=request.context,
            profile=request.profile,
            target=request.target,
            created_at=when,
            updated_at=when,
            priority=priority,
            feedback_quality=FeedbackQuality(request.feedback_quality),
            retry_limit=max(0, int(request.retry_limit)),
            verification_delay_seconds=max(
                0.0, request.verification_delay.total_seconds()
            ),
            settle_delay_seconds=max(0.0, request.settle_delay.total_seconds()),
            position_tolerance=max(0.0, float(request.position_tolerance)),
            tilt_tolerance=max(0.0, float(request.tilt_tolerance)),
            result=result,
            owned_by_smart_shading=owned,
            allow_automatic_reverse=request.allow_automatic_reverse,
            stagger_scope=(
                request.stagger_scope or request.context.room_id or "house"
            ),
            opening_order=_opening_order(request.opening_order),
            last_valid_position=_as_float(request.current_position),
            last_valid_tilt=_as_float(request.current_tilt),
        )

    def _execution_base(self, request: CommandRequest, when: datetime) -> datetime:
        if (
            request.safety
            and request.safety_bypasses_stagger
        ) or request.stagger_seconds <= 0:
            return when
        scope = request.stagger_scope or request.context.room_id or "house"
        slot = self._next_slot_by_scope.get(scope, when)
        restored_slot = self._restored_stagger_slots.pop(scope, None)
        if restored_slot is not None:
            # A restored slot names the latest already-reserved command base,
            # not the next free slot.  The request supplies the current room
            # interval, so reserve one full interval after it before dispatch.
            slot = max(
                slot,
                restored_slot + timedelta(seconds=request.stagger_seconds),
            )
        base = max(when, slot)
        self._next_slot_by_scope[scope] = base + timedelta(
            seconds=request.stagger_seconds
        )
        return base

    def _build_steps(
        self,
        entry: CommandLedgerEntry,
        *,
        position_needed: bool,
        tilt_needed: bool,
        base: datetime,
    ) -> list[CommandStep]:
        axes: list[tuple[str, float, datetime]] = []
        tilt_first_for_safe_opening = bool(
            position_needed
            and tilt_needed
            and entry.profile in SEQUENCED_PROFILES
            and entry.opening_order == OPENING_ORDER_TILT_THEN_HEIGHT
            and entry.last_valid_position is not None
            and entry.target.position is not None
            and entry.target.position > entry.last_valid_position
        )
        if tilt_first_for_safe_opening:
            # Some hardware requires slats to reach their safe/open angle
            # before the blind rises.  This is a physical sequencing policy,
            # not a new decision priority, and is persisted with the target.
            if entry.target.tilt is not None:
                axes.append(("tilt", entry.target.tilt, base))
            if entry.target.position is not None:
                axes.append(
                    (
                        "position",
                        entry.target.position,
                        base + timedelta(seconds=entry.settle_delay_seconds),
                    )
                )
        else:
            if position_needed and entry.target.position is not None:
                axes.append(("position", entry.target.position, base))
            if tilt_needed and entry.target.tilt is not None:
                tilt_at = base
                if position_needed and entry.profile in SEQUENCED_PROFILES:
                    tilt_at = base + timedelta(seconds=entry.settle_delay_seconds)
                axes.append(("tilt", entry.target.tilt, tilt_at))
        steps: list[CommandStep] = []
        for index, (axis, target, execute_at) in enumerate(axes):
            self._sequence += 1
            steps.append(
                CommandStep(
                    step_id=f"{entry.lifecycle_id}:{self._sequence}",
                    lifecycle_id=entry.lifecycle_id,
                    cover_id=entry.cover_id,
                    axis=axis,
                    target=target,
                    execute_at=execute_at,
                    priority=entry.priority,
                    rule=entry.rule,
                    reason_code=entry.reason_code,
                    context=entry.context,
                    stagger_scope=entry.stagger_scope,
                    final_step=index == len(axes) - 1,
                )
            )
        return steps

    @staticmethod
    def _needed_axes(
        target: CommandTarget,
        current_position: float | None,
        current_tilt: float | None,
        position_tolerance: float,
        tilt_tolerance: float,
    ) -> tuple[bool, bool]:
        position = _as_float(current_position)
        tilt = _as_float(current_tilt)
        position_needed = target.position is not None and (
            position is None
            or abs(position - target.position) > max(0.0, position_tolerance)
        )
        tilt_needed = target.tilt is not None and (
            tilt is None or abs(tilt - target.tilt) > max(0.0, tilt_tolerance)
        )
        return position_needed, tilt_needed

    @staticmethod
    def _target_reached(entry: CommandLedgerEntry) -> bool:
        position_ok = entry.target.position is None or (
            entry.last_valid_position is not None
            and abs(entry.last_valid_position - entry.target.position)
            <= entry.position_tolerance
        )
        tilt_ok = entry.target.tilt is None or (
            entry.last_valid_tilt is not None
            and abs(entry.last_valid_tilt - entry.target.tilt)
            <= entry.tilt_tolerance
        )
        return position_ok and tilt_ok

    @staticmethod
    def _is_active(entry: CommandLedgerEntry) -> bool:
        return entry.result in {
            CommandResult.PLANNED,
            CommandResult.QUEUED,
            CommandResult.SENT,
        }

    def _cancel_pending_for_cover(self, cover_id: str) -> list[CommandStep]:
        cancelled = [step for step in self._steps if step.cover_id == cover_id]
        self._steps = [step for step in self._steps if step.cover_id != cover_id]
        return sorted(cancelled, key=self._step_sort_key)

    @staticmethod
    def _step_sort_key(step: CommandStep) -> tuple[datetime, int, str]:
        # Numeric suffix preserves height-before-tilt if both timestamps match.
        suffix = step.step_id.rsplit(":", 1)[-1]
        return (step.execute_at, int(suffix) if suffix.isdigit() else 0, step.step_id)

    def _now(self, value: datetime | None) -> datetime:
        return value if value is not None else self._clock()


__all__ = [
    "CommandContext",
    "CommandLedgerEntry",
    "CommandPlanner",
    "CommandRequest",
    "CommandResult",
    "CommandStep",
    "CommandTarget",
    "FeedbackQuality",
    "OPENING_ORDER_HEIGHT_THEN_TILT",
    "OPENING_ORDER_TILT_THEN_HEIGHT",
    "OPENING_ORDERS",
    "PlanResult",
    "SAFETY_PRIORITY",
    "SEQUENCED_PROFILES",
]
