from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    CONF_WINDOW_RETURNS_TO_AUTOMATION,
    DEFAULT_POSITION_TOLERANCE,
    DEFAULT_TILT_TOLERANCE,
    DEFAULT_WINDOW_RETURNS_TO_AUTOMATION,
    WINDOW_POLICY_IGNORE,
)
from .logic import CoverFeedbackDecision, classify_cover_feedback

CONF_EXTERNAL_MOVEMENT_DETECTION = "external_movement_detection"
DEFAULT_EXTERNAL_MOVEMENT_DETECTION = True
# KNX actuators may publish movement feedback at wider intervals. Keep isolated
# updates harmless and require consistent numeric progress plus a stable value.
EXTERNAL_CONFIRMATION_WINDOW_SECONDS = 60.0
EXTERNAL_MIN_CHANGED_UPDATES = 2
EXTERNAL_MIN_STABLE_UPDATES = 1
EXTERNAL_STABLE_EPSILON = 0.5
OWN_COMMAND_SETTLE_SECONDS = 30.0
WINDOW_AUTOMATION_SETTLE_SECONDS = 30.0
WINDOW_AUTOMATION_TIMEOUT_SECONDS = 180.0


@dataclass(slots=True)
class CoverMotionObservation:
    """Ephemeral per-cover state used to confirm external movement."""

    entity_id: str
    phase: str = "baseline"
    last_position: float | None = None
    last_tilt: float | None = None
    last_state: str | None = None
    baseline_position: float | None = None
    baseline_tilt: float | None = None
    candidate_axis: str | None = None
    candidate_direction: str | None = None
    candidate_started_at: datetime | None = None
    candidate_last_changed_at: datetime | None = None
    candidate_start_position: float | None = None
    candidate_start_tilt: float | None = None
    candidate_latest_position: float | None = None
    candidate_latest_tilt: float | None = None
    candidate_updates: int = 0
    candidate_stable_updates: int = 0
    last_decision_reason: str = "baseline"


@dataclass(slots=True)
class WindowAutomationContext:
    """Transient ownership of movement caused by a configured window contact."""

    entity_id: str
    window_entity_id: str
    phase: str
    started_at: datetime
    expires_at: datetime | None = None
    last_feedback_at: datetime | None = None


class ManualOverrideDetectionMixin:
    """Separate Smart Shading feedback from every other real cover movement.

    Explicit automation-lock entities remain authoritative and immediate. Cover
    movement outside an active Smart Shading target is enabled by default and
    requires directionally consistent numeric updates followed by stable numeric
    feedback from the same cover. Startup, recovery, state-only refreshes and
    own-command feedback remain harmless.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.cover_motion: dict[str, CoverMotionObservation] = {}
        self.window_automation_contexts: dict[str, WindowAutomationContext] = {}

    def _rebuild_runtime(self) -> None:
        super()._rebuild_runtime()
        self._seed_cover_motion_baselines()
        self._seed_window_automation_contexts()

    @staticmethod
    def _window_return_enabled(cover: dict[str, Any]) -> bool:
        return bool(
            cover.get("window")
            and cover.get("window_policy") != WINDOW_POLICY_IGNORE
            and cover.get(
                CONF_WINDOW_RETURNS_TO_AUTOMATION,
                DEFAULT_WINDOW_RETURNS_TO_AUTOMATION,
            )
        )

    @staticmethod
    def _window_state_is_safe(cover: dict[str, Any], state) -> bool:
        return bool(
            state is not None
            and getattr(state, "state", None)
            == cover.get("window_safe_state", "on")
        )

    def _seed_window_automation_contexts(self) -> None:
        """Own window-linked movement immediately after startup when unsafe."""
        now = dt_util.now()
        configured: set[str] = set()
        for _room, _sector, _layer, cover in self._iter_covers():
            if not self._window_return_enabled(cover):
                continue
            entity_id = str(cover.get("entity") or "")
            window_entity_id = str(cover.get("window") or "")
            if not entity_id or not window_entity_id:
                continue
            configured.add(entity_id)
            if not self._window_state_is_safe(
                cover, self.hass.states.get(window_entity_id)
            ):
                self.window_automation_contexts[entity_id] = (
                    WindowAutomationContext(
                        entity_id=entity_id,
                        window_entity_id=window_entity_id,
                        phase="unsafe",
                        started_at=now,
                    )
                )
            else:
                self.window_automation_contexts.pop(entity_id, None)

        for entity_id in list(self.window_automation_contexts):
            if entity_id not in configured:
                self.window_automation_contexts.pop(entity_id, None)

    @staticmethod
    def _window_feedback_changed(old_state, new_state) -> bool:
        if old_state is None or new_state is None:
            return False
        if getattr(old_state, "state", None) != getattr(new_state, "state", None):
            return True
        for key in ("current_position", "current_tilt_position"):
            try:
                before = float(old_state.attributes.get(key))
                after = float(new_state.attributes.get(key))
            except (TypeError, ValueError):
                continue
            if before is not None and after is not None and abs(after - before) >= 0.5:
                return True
        return False

    def _clear_pending_window_cover_detection(self, entity_id: str) -> None:
        observation = self.cover_motion.get(entity_id)
        if observation is not None:
            self._clear_motion_candidate(observation)
            observation.phase = "window_automation"

        intents = getattr(self, "_pending_manual_service_intents", None)
        if not intents:
            return
        intent = intents.get(entity_id)
        if intent is not None and not getattr(intent, "user_initiated", False):
            intents.pop(entity_id, None)

    def _window_automation_context_active(
        self,
        cover: dict[str, Any],
        *,
        now: datetime,
        feedback_changed: bool = False,
    ) -> bool:
        """Return whether this cover's feedback belongs to window automation."""
        if not self._window_return_enabled(cover):
            return False

        entity_id = str(cover.get("entity") or "")
        window_entity_id = str(cover.get("window") or "")
        if not entity_id or not window_entity_id:
            return False

        context = self.window_automation_contexts.get(entity_id)
        current_safe = self._window_state_is_safe(
            cover, self.hass.states.get(window_entity_id)
        )
        if context is None and not current_safe:
            context = WindowAutomationContext(
                entity_id=entity_id,
                window_entity_id=window_entity_id,
                phase="unsafe",
                started_at=now,
            )
            self.window_automation_contexts[entity_id] = context

        if context is None:
            return False
        if context.phase == "unsafe" and not current_safe:
            return True
        if context.phase == "unsafe":
            context.phase = "recovery"
            context.started_at = now
            context.expires_at = now + timedelta(
                seconds=WINDOW_AUTOMATION_TIMEOUT_SECONDS
            )
            context.last_feedback_at = None

        if context.expires_at is not None and now > context.expires_at:
            self.window_automation_contexts.pop(entity_id, None)
            self._diag(
                "window_automation_context_ended",
                full=True,
                entity_id=entity_id,
                window_entity_id=window_entity_id,
                reason="timeout",
            )
            return False
        if (
            feedback_changed
            and context.last_feedback_at is not None
            and (now - context.last_feedback_at).total_seconds()
            > WINDOW_AUTOMATION_SETTLE_SECONDS
        ):
            self.window_automation_contexts.pop(entity_id, None)
            self._diag(
                "window_automation_context_ended",
                full=True,
                entity_id=entity_id,
                window_entity_id=window_entity_id,
                reason="settled",
            )
            return False
        if feedback_changed:
            context.last_feedback_at = now
        return True

    def _handle_window_state_change(
        self, entity_id: str, old_state, new_state, now: datetime
    ) -> None:
        """Start or transition contexts for covers linked to this contact."""
        for room, _sector, _layer, cover in self._iter_covers():
            if (
                cover.get("window") != entity_id
                or not self._window_return_enabled(cover)
            ):
                continue
            cover_entity_id = str(cover.get("entity") or "")
            if not cover_entity_id:
                continue
            old_safe = self._window_state_is_safe(cover, old_state)
            new_safe = self._window_state_is_safe(cover, new_state)
            if old_safe == new_safe:
                if not new_safe and cover_entity_id not in self.window_automation_contexts:
                    self.window_automation_contexts[cover_entity_id] = (
                        WindowAutomationContext(
                            entity_id=cover_entity_id,
                            window_entity_id=entity_id,
                            phase="unsafe",
                            started_at=now,
                        )
                    )
                continue

            if not new_safe:
                self.window_automation_contexts[cover_entity_id] = (
                    WindowAutomationContext(
                        entity_id=cover_entity_id,
                        window_entity_id=entity_id,
                        phase="unsafe",
                        started_at=now,
                    )
                )
                event_name = "window_automation_context_started"
                phase = "unsafe"
            else:
                self.window_automation_contexts[cover_entity_id] = (
                    WindowAutomationContext(
                        entity_id=cover_entity_id,
                        window_entity_id=entity_id,
                        phase="recovery",
                        started_at=now,
                        expires_at=now
                        + timedelta(seconds=WINDOW_AUTOMATION_TIMEOUT_SECONDS),
                    )
                )
                event_name = "window_automation_recovery_started"
                phase = "recovery"

            self._clear_pending_window_cover_detection(cover_entity_id)
            self._diag(
                event_name,
                force=True,
                room_id=room.get("id"),
                entity_id=cover_entity_id,
                window_entity_id=entity_id,
                phase=phase,
            )

    @staticmethod
    def _cover_state_valid(state) -> bool:
        return state is not None and getattr(state, "state", None) not in {
            None,
            "",
            "unknown",
            "unavailable",
            "none",
        }

    def _seed_cover_motion_baselines(self) -> None:
        configured: set[str] = set()
        for _room, _sector, _layer, cover in self._iter_covers():
            entity_id = str(cover.get("entity") or "")
            if not entity_id:
                continue
            configured.add(entity_id)
            observation = self.cover_motion.get(entity_id) or CoverMotionObservation(
                entity_id
            )
            state = self.hass.states.get(entity_id)
            if self._cover_state_valid(state):
                observation.phase = "idle"
                observation.last_position = self._state_attribute_number(
                    state, "current_position"
                )
                observation.last_tilt = self._state_attribute_number(
                    state, "current_tilt_position"
                )
                observation.baseline_position = observation.last_position
                observation.baseline_tilt = observation.last_tilt
                observation.last_state = state.state
                observation.last_decision_reason = "baseline_seeded"
                self._clear_motion_candidate(observation)
            else:
                observation.phase = "baseline"
            self.cover_motion[entity_id] = observation

        for entity_id in list(self.cover_motion):
            if entity_id not in configured:
                self.cover_motion.pop(entity_id, None)

    @staticmethod
    def _clear_motion_candidate(observation: CoverMotionObservation) -> None:
        observation.candidate_direction = None
        observation.candidate_axis = None
        observation.candidate_started_at = None
        observation.candidate_last_changed_at = None
        observation.candidate_start_position = None
        observation.candidate_start_tilt = None
        observation.candidate_latest_position = None
        observation.candidate_latest_tilt = None
        observation.candidate_updates = 0
        observation.candidate_stable_updates = 0
        if observation.phase in {"possible_external", "confirmed_external"}:
            observation.phase = "idle"

    @staticmethod
    def _update_motion_observation(
        observation: CoverMotionObservation,
        new_state,
        new_position: float | None,
        new_tilt: float | None,
    ) -> None:
        observation.last_position = new_position
        observation.last_tilt = new_tilt
        observation.last_state = getattr(new_state, "state", None)

    @classmethod
    def _accept_motion_baseline(
        cls,
        observation: CoverMotionObservation,
        new_state,
        new_position: float | None,
        new_tilt: float | None,
        reason: str,
    ) -> None:
        """Accept feedback as the new harmless detector baseline."""
        cls._clear_motion_candidate(observation)
        observation.phase = "idle"
        if new_position is not None:
            observation.baseline_position = new_position
        if new_tilt is not None:
            observation.baseline_tilt = new_tilt
        observation.last_decision_reason = reason
        cls._update_motion_observation(
            observation, new_state, new_position, new_tilt
        )

    @staticmethod
    def _movement_direction(
        *,
        old_position: float | None,
        new_position: float | None,
        old_tilt: float | None,
        new_tilt: float | None,
        position_threshold: float,
        tilt_threshold: float,
    ) -> tuple[str, str] | None:
        if old_position is not None and new_position is not None:
            delta = float(new_position) - float(old_position)
            if abs(delta) >= position_threshold:
                return (
                    "position",
                    "opening" if delta > 0 else "closing",
                )

        if old_tilt is not None and new_tilt is not None:
            delta = float(new_tilt) - float(old_tilt)
            if abs(delta) >= tilt_threshold:
                return (
                    "tilt",
                    "opening" if delta > 0 else "closing",
                )
        return None

    @staticmethod
    def _candidate_returned_to_baseline(
        observation: CoverMotionObservation,
        new_position: float | None,
        new_tilt: float | None,
        position_threshold: float,
        tilt_threshold: float,
    ) -> bool:
        if observation.candidate_axis == "position":
            return bool(
                observation.candidate_start_position is not None
                and new_position is not None
                and abs(new_position - observation.candidate_start_position)
                <= position_threshold
            )
        if observation.candidate_axis == "tilt":
            return bool(
                observation.candidate_start_tilt is not None
                and new_tilt is not None
                and abs(new_tilt - observation.candidate_start_tilt)
                <= tilt_threshold
            )
        return False

    @staticmethod
    def _candidate_value_is_stable(
        observation: CoverMotionObservation,
        new_position: float | None,
        new_tilt: float | None,
    ) -> bool:
        if observation.candidate_axis == "position":
            return bool(
                observation.candidate_latest_position is not None
                and new_position is not None
                and abs(new_position - observation.candidate_latest_position)
                <= EXTERNAL_STABLE_EPSILON
            )
        if observation.candidate_axis == "tilt":
            return bool(
                observation.candidate_latest_tilt is not None
                and new_tilt is not None
                and abs(new_tilt - observation.candidate_latest_tilt)
                <= EXTERNAL_STABLE_EPSILON
            )
        return False

    def _start_motion_candidate(
        self,
        observation: CoverMotionObservation,
        *,
        axis: str,
        direction: str,
        old_position: float | None,
        new_position: float | None,
        old_tilt: float | None,
        new_tilt: float | None,
        new_state,
        now: datetime,
    ) -> None:
        observation.phase = "possible_external"
        observation.candidate_axis = axis
        observation.candidate_direction = direction
        observation.candidate_started_at = now
        observation.candidate_last_changed_at = now
        observation.candidate_start_position = (
            observation.baseline_position
            if observation.baseline_position is not None
            else old_position
        )
        observation.candidate_start_tilt = (
            observation.baseline_tilt
            if observation.baseline_tilt is not None
            else old_tilt
        )
        observation.candidate_latest_position = new_position
        observation.candidate_latest_tilt = new_tilt
        observation.candidate_updates = 1
        observation.candidate_stable_updates = 0
        observation.last_decision_reason = "possible_external_movement"
        self._update_motion_observation(
            observation, new_state, new_position, new_tilt
        )

    def _external_movement_detection_enabled(self, room: dict[str, Any]) -> bool:
        return bool(
            room.get(
                CONF_EXTERNAL_MOVEMENT_DETECTION,
                self.config.get(
                    CONF_EXTERNAL_MOVEMENT_DETECTION,
                    DEFAULT_EXTERNAL_MOVEMENT_DETECTION,
                ),
            )
        )

    def _own_command_session_active(
        self,
        entity_id: str,
        *,
        now: datetime,
        new_state: str | None,
        new_position: float | None,
        new_tilt: float | None,
        position_tolerance: float,
        tilt_tolerance: float,
    ) -> bool:
        """Return whether feedback still belongs to Smart Shading.

        KNX can publish delayed, non-monotonic and cross-axis feedback while a
        venetian blind is moving. Ownership therefore follows the command
        session, not every individual intermediate value. Once the commanded
        targets have been stable for a short grace period, the next movement is
        eligible for normal external-movement confirmation again.
        """
        session = self.own_command_sessions.get(entity_id)
        if session is None:
            return False
        if now > session.expires_at:
            self._cancel_own_command_session(entity_id)
            return False
        if (
            session.target_reached_at is not None
            and (now - session.target_reached_at).total_seconds()
            > OWN_COMMAND_SETTLE_SECONDS
        ):
            self._cancel_own_command_session(entity_id)
            return False

        position_complete = (
            not session.position_commanded
            or (
                new_position is not None
                and session.position_target is not None
                and abs(float(new_position) - session.position_target)
                <= position_tolerance
            )
        )
        tilt_complete = (
            not session.tilt_commanded
            or (
                new_tilt is not None
                and session.tilt_target is not None
                and abs(float(new_tilt) - session.tilt_target)
                <= tilt_tolerance
            )
        )
        target_complete = (
            position_complete
            and tilt_complete
            and new_state not in {"opening", "closing"}
        )
        if target_complete:
            if session.target_reached_at is None:
                session.target_reached_at = now
        else:
            session.target_reached_at = None
        return True

    def _classify_confirmed_cover_change(
        self,
        room: dict[str, Any],
        entity_id: str,
        old_state,
        new_state,
        now: datetime,
    ) -> CoverFeedbackDecision:
        observation = self.cover_motion.get(entity_id) or CoverMotionObservation(
            entity_id
        )
        self.cover_motion[entity_id] = observation

        old_valid = self._cover_state_valid(old_state)
        new_valid = self._cover_state_valid(new_state)
        old_position = self._state_attribute_number(old_state, "current_position")
        new_position = self._state_attribute_number(new_state, "current_position")
        old_tilt = self._state_attribute_number(old_state, "current_tilt_position")
        new_tilt = self._state_attribute_number(new_state, "current_tilt_position")
        old_value = getattr(old_state, "state", None)
        new_value = getattr(new_state, "state", None)

        cover_match = self._find_cover_by_entity(entity_id)
        cover = cover_match[1] if cover_match else {}
        window_feedback_changed = self._window_feedback_changed(
            old_state, new_state
        )
        if self._window_automation_context_active(
            cover,
            now=now,
            feedback_changed=window_feedback_changed,
        ):
            self._accept_motion_baseline(
                observation,
                new_state,
                new_position,
                new_tilt,
                "window_automation_context",
            )
            observation.phase = "window_automation"
            return CoverFeedbackDecision(
                window_feedback_changed,
                True,
                False,
                False,
                False,
                "window_automation_context",
            )

        # Startup, reconnect and unavailable recovery only establish a baseline.
        if not old_valid or not new_valid or observation.phase == "baseline":
            if new_valid:
                self._accept_motion_baseline(
                    observation,
                    new_state,
                    new_position,
                    new_tilt,
                    "baseline_or_recovery",
                )
            else:
                self._clear_motion_candidate(observation)
                observation.phase = "baseline"
                observation.last_decision_reason = "baseline_or_recovery"
            return CoverFeedbackDecision(
                False, False, False, False, False, "baseline_or_recovery"
            )

        memory = self.command_memory.get(entity_id)
        latest = None
        if memory is not None:
            latest = max(
                [
                    value
                    for value in (
                        memory.position_at,
                        memory.tilt_at,
                        memory.last_activity_at,
                    )
                    if value is not None
                ],
                default=None,
            )
        age = (now - latest).total_seconds() if latest is not None else None
        position_threshold = max(
            2.0,
            float(
                self.config.get(
                    "position_tolerance", DEFAULT_POSITION_TOLERANCE
                )
            ),
        )
        tilt_threshold = max(
            3.0,
            float(self.config.get("tilt_tolerance", DEFAULT_TILT_TOLERANCE)),
        )

        raw = classify_cover_feedback(
            old_position=old_position,
            new_position=new_position,
            old_tilt=old_tilt,
            new_tilt=new_tilt,
            old_state=old_value,
            new_state=new_value,
            target_position=memory.position if memory else None,
            target_tilt=memory.tilt if memory else None,
            command_age_seconds=age,
            position_tolerance=float(
                self.config.get("position_tolerance", DEFAULT_POSITION_TOLERANCE)
            ),
            tilt_tolerance=float(
                self.config.get("tilt_tolerance", DEFAULT_TILT_TOLERANCE)
            ),
            command_timeout_seconds=180.0,
            position_change_threshold=position_threshold,
            tilt_change_threshold=tilt_threshold,
        )

        if self._own_command_session_active(
            entity_id,
            now=now,
            new_state=new_value,
            new_position=new_position,
            new_tilt=new_tilt,
            position_tolerance=float(
                self.config.get("position_tolerance", DEFAULT_POSITION_TOLERANCE)
            ),
            tilt_tolerance=float(
                self.config.get("tilt_tolerance", DEFAULT_TILT_TOLERANCE)
            ),
        ):
            self._accept_motion_baseline(
                observation,
                new_state,
                new_position,
                new_tilt,
                "active_own_command_session",
            )
            observation.phase = "own_command"
            return CoverFeedbackDecision(
                raw.changed,
                True,
                False,
                raw.position_complete,
                raw.tilt_complete,
                "active_own_command_session",
            )

        # A legacy per-room or house override may still disable feedback-based
        # detection. Normal installations classify real movement outside a
        # Smart Shading target as external by default.
        if not self._external_movement_detection_enabled(room):
            self._accept_motion_baseline(
                observation,
                new_state,
                new_position,
                new_tilt,
                "external_movement_detection_disabled",
            )
            return CoverFeedbackDecision(
                raw.changed,
                False,
                False,
                raw.position_complete,
                raw.tilt_complete,
                "external_movement_detection_disabled",
            )

        candidate_active = (
            observation.phase == "possible_external"
            and observation.candidate_started_at is not None
        )
        if candidate_active and (
            now - observation.candidate_started_at
        ).total_seconds() > EXTERNAL_CONFIRMATION_WINDOW_SECONDS:
            self._accept_motion_baseline(
                observation,
                new_state,
                new_position,
                new_tilt,
                "external_candidate_expired",
            )
            return CoverFeedbackDecision(
                raw.changed,
                False,
                False,
                raw.position_complete,
                raw.tilt_complete,
                "external_candidate_expired",
            )

        if candidate_active and self._candidate_returned_to_baseline(
            observation,
            new_position,
            new_tilt,
            position_threshold,
            tilt_threshold,
        ):
            self._accept_motion_baseline(
                observation,
                new_state,
                new_position,
                new_tilt,
                "external_candidate_returned_to_baseline",
            )
            return CoverFeedbackDecision(
                raw.changed,
                False,
                False,
                raw.position_complete,
                raw.tilt_complete,
                "external_candidate_returned_to_baseline",
            )

        if not raw.changed:
            if candidate_active and self._candidate_value_is_stable(
                observation, new_position, new_tilt
            ):
                observation.candidate_stable_updates += 1
                self._update_motion_observation(
                    observation, new_state, new_position, new_tilt
                )
                if (
                    observation.candidate_updates >= EXTERNAL_MIN_CHANGED_UPDATES
                    and observation.candidate_stable_updates
                    >= EXTERNAL_MIN_STABLE_UPDATES
                ):
                    observation.phase = "confirmed_external"
                    observation.last_decision_reason = (
                        "confirmed_stable_external_movement"
                    )
                    return CoverFeedbackDecision(
                        True,
                        False,
                        True,
                        raw.position_complete,
                        raw.tilt_complete,
                        "confirmed_stable_external_movement",
                    )
                observation.last_decision_reason = (
                    "external_candidate_awaiting_corroboration"
                )
                return CoverFeedbackDecision(
                    False,
                    False,
                    False,
                    raw.position_complete,
                    raw.tilt_complete,
                    "external_candidate_awaiting_corroboration",
                )

            observation.last_decision_reason = raw.reason
            self._update_motion_observation(
                observation, new_state, new_position, new_tilt
            )
            return raw

        movement = self._movement_direction(
            old_position=old_position,
            new_position=new_position,
            old_tilt=old_tilt,
            new_tilt=new_tilt,
            position_threshold=position_threshold,
            tilt_threshold=tilt_threshold,
        )
        if movement is None:
            self._accept_motion_baseline(
                observation,
                new_state,
                new_position,
                new_tilt,
                "ambiguous_external_change",
            )
            return CoverFeedbackDecision(
                True,
                False,
                False,
                raw.position_complete,
                raw.tilt_complete,
                "ambiguous_external_change",
            )

        axis, direction = movement

        candidate_fresh = (
            candidate_active
            and observation.candidate_axis == axis
            and observation.candidate_direction == direction
        )
        if candidate_fresh:
            observation.candidate_updates += 1
            observation.candidate_stable_updates = 0
            observation.candidate_last_changed_at = now
            observation.candidate_latest_position = new_position
            observation.candidate_latest_tilt = new_tilt
            observation.last_decision_reason = "external_candidate_progress"
            self._update_motion_observation(
                observation, new_state, new_position, new_tilt
            )
            return CoverFeedbackDecision(
                True,
                False,
                False,
                raw.position_complete,
                raw.tilt_complete,
                "external_candidate_progress",
            )

        self._start_motion_candidate(
            observation,
            axis=axis,
            direction=direction,
            old_position=old_position,
            new_position=new_position,
            old_tilt=old_tilt,
            new_tilt=new_tilt,
            new_state=new_state,
            now=now,
        )
        return CoverFeedbackDecision(
            True,
            False,
            False,
            raw.position_complete,
            raw.tilt_complete,
            "possible_external_movement",
        )

    async def _async_state_changed(self, event) -> None:
        entity_id = event.data.get("entity_id")
        cover_match = self._find_cover_by_entity(entity_id)
        if not cover_match:
            if self._is_critical_entity(entity_id):
                self._handle_window_state_change(
                    str(entity_id or ""),
                    event.data.get("old_state"),
                    event.data.get("new_state"),
                    dt_util.now(),
                )
            await super()._async_state_changed(event)
            return

        room, cover = cover_match
        decision = self._classify_confirmed_cover_change(
            room,
            entity_id,
            event.data.get("old_state"),
            event.data.get("new_state"),
            dt_util.now(),
        )
        if decision.expected:
            self._diag(
                "own_cover_feedback",
                full=True,
                entity_id=entity_id,
                reason=decision.reason,
            )
            return

        if decision.manual:
            observation = self.cover_motion[entity_id]
            self._diag(
                "external_cover_movement_confirmed",
                force=True,
                room_id=room.get("id"),
                entity_id=entity_id,
                reason=decision.reason,
                axis=observation.candidate_axis,
                direction=observation.candidate_direction,
                baseline_position=observation.candidate_start_position,
                baseline_tilt=observation.candidate_start_tilt,
                latest_position=observation.candidate_latest_position,
                latest_tilt=observation.candidate_latest_tilt,
                changed_updates=observation.candidate_updates,
                stable_updates=observation.candidate_stable_updates,
            )
            await self._activate_cover_pause(
                room, cover, "external_or_physical_control"
            )
            if self._room_safety_active(room):
                await self.async_evaluate_all(f"safety_manual_cover:{entity_id}")
            return

        if decision.changed or decision.reason == "state_only_change_ignored":
            self._diag(
                "cover_change_observed",
                full=True,
                entity_id=entity_id,
                reason=decision.reason,
                phase=self.cover_motion[entity_id].phase,
            )

    async def _activate_cover_pause(self, room, cover, reason, **kwargs) -> None:
        entity_id = str(cover.get("entity") or "")
        observation = self.cover_motion.get(entity_id)
        if observation is not None:
            self._clear_motion_candidate(observation)
            observation.phase = "paused"
        await super()._activate_cover_pause(room, cover, reason, **kwargs)

    async def _clear_cover_pause(self, room, cover, **kwargs) -> None:
        entity_id = str(cover.get("entity") or "")
        observation = self.cover_motion.get(entity_id)
        if observation is not None:
            state = self.hass.states.get(entity_id)
            if self._cover_state_valid(state):
                self._accept_motion_baseline(
                    observation,
                    state,
                    self._state_attribute_number(state, "current_position"),
                    self._state_attribute_number(state, "current_tilt_position"),
                    "pause_cleared_baseline",
                )
            else:
                self._clear_motion_candidate(observation)
                observation.phase = "baseline"
                observation.last_decision_reason = "pause_cleared_without_state"
        await super()._clear_cover_pause(room, cover, **kwargs)
