from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util

from .const import DEFAULT_POSITION_TOLERANCE, DEFAULT_TILT_TOLERANCE
from .logic import CoverFeedbackDecision, classify_cover_feedback

CONF_EXTERNAL_MOVEMENT_DETECTION = "external_movement_detection"
DEFAULT_EXTERNAL_MOVEMENT_DETECTION = False
EXTERNAL_CONFIRMATION_WINDOW_SECONDS = 8.0


@dataclass(slots=True)
class CoverMotionObservation:
    """Ephemeral per-cover state used to confirm external movement."""

    entity_id: str
    phase: str = "baseline"
    last_position: float | None = None
    last_tilt: float | None = None
    last_state: str | None = None
    candidate_direction: str | None = None
    candidate_started_at: datetime | None = None
    candidate_updates: int = 0


class ManualOverrideDetectionMixin:
    """Protect local pauses from isolated KNX/Home Assistant state refreshes.

    Explicit automation-lock entities remain authoritative and immediate. Cover
    movement detection is an opt-in feature and requires two consistent updates
    from the same cover within a short confirmation window.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.cover_motion: dict[str, CoverMotionObservation] = {}

    def _rebuild_runtime(self) -> None:
        super()._rebuild_runtime()
        self._seed_cover_motion_baselines()

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
                observation.last_state = state.state
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
        observation.candidate_started_at = None
        observation.candidate_updates = 0
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

    @staticmethod
    def _movement_direction(
        *,
        old_position: float | None,
        new_position: float | None,
        old_tilt: float | None,
        new_tilt: float | None,
        new_state: str | None,
        position_threshold: float,
        tilt_threshold: float,
    ) -> str | None:
        state_direction = new_state if new_state in {"opening", "closing"} else None
        position_direction = None
        if old_position is not None and new_position is not None:
            delta = float(new_position) - float(old_position)
            if abs(delta) >= position_threshold:
                position_direction = "opening" if delta > 0 else "closing"

        # Contradicting direction data is not reliable enough to pause a cover.
        if state_direction and position_direction and state_direction != position_direction:
            return None
        if state_direction or position_direction:
            return state_direction or position_direction

        if old_tilt is not None and new_tilt is not None:
            delta = float(new_tilt) - float(old_tilt)
            if abs(delta) >= tilt_threshold:
                return "tilt_opening" if delta > 0 else "tilt_closing"
        return None

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

        # Startup, reconnect and unavailable recovery only establish a baseline.
        if not old_valid or not new_valid or observation.phase == "baseline":
            self._clear_motion_candidate(observation)
            if new_valid:
                observation.phase = "idle"
                self._update_motion_observation(
                    observation, new_state, new_position, new_tilt
                )
            else:
                observation.phase = "baseline"
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

        if raw.expected:
            self._clear_motion_candidate(observation)
            observation.phase = "own_command"
            self._update_motion_observation(
                observation, new_state, new_position, new_tilt
            )
            return raw

        if not raw.changed:
            if (
                observation.candidate_started_at is not None
                and (now - observation.candidate_started_at).total_seconds()
                > EXTERNAL_CONFIRMATION_WINDOW_SECONDS
            ):
                self._clear_motion_candidate(observation)
            self._update_motion_observation(
                observation, new_state, new_position, new_tilt
            )
            return raw

        # Safe default: explicit automation-lock entities are the only source of
        # local pauses until detection is deliberately enabled.
        if not self._external_movement_detection_enabled(room):
            self._clear_motion_candidate(observation)
            observation.phase = "idle"
            self._update_motion_observation(
                observation, new_state, new_position, new_tilt
            )
            return CoverFeedbackDecision(
                True,
                False,
                False,
                raw.position_complete,
                raw.tilt_complete,
                "external_movement_detection_disabled",
            )

        direction = self._movement_direction(
            old_position=old_position,
            new_position=new_position,
            old_tilt=old_tilt,
            new_tilt=new_tilt,
            new_state=new_value,
            position_threshold=position_threshold,
            tilt_threshold=tilt_threshold,
        )
        if direction is None:
            self._clear_motion_candidate(observation)
            observation.phase = "idle"
            self._update_motion_observation(
                observation, new_state, new_position, new_tilt
            )
            return CoverFeedbackDecision(
                True,
                False,
                False,
                raw.position_complete,
                raw.tilt_complete,
                "ambiguous_external_change",
            )

        candidate_fresh = (
            observation.phase == "possible_external"
            and observation.candidate_started_at is not None
            and (now - observation.candidate_started_at).total_seconds()
            <= EXTERNAL_CONFIRMATION_WINDOW_SECONDS
            and observation.candidate_direction == direction
        )
        if candidate_fresh:
            observation.candidate_updates += 1
            observation.phase = "confirmed_external"
            self._update_motion_observation(
                observation, new_state, new_position, new_tilt
            )
            return CoverFeedbackDecision(
                True,
                False,
                True,
                raw.position_complete,
                raw.tilt_complete,
                "confirmed_external_movement",
            )

        observation.phase = "possible_external"
        observation.candidate_direction = direction
        observation.candidate_started_at = now
        observation.candidate_updates = 1
        self._update_motion_observation(
            observation, new_state, new_position, new_tilt
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
            await self._activate_cover_pause(
                room, cover, "external_or_physical_control"
            )
            if self._room_safety_active(room):
                await self.async_evaluate_all(f"safety_manual_cover:{entity_id}")
            return

        if decision.changed:
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
            self._clear_motion_candidate(observation)
            state = self.hass.states.get(entity_id)
            if self._cover_state_valid(state):
                observation.phase = "idle"
                self._update_motion_observation(
                    observation,
                    state,
                    self._state_attribute_number(state, "current_position"),
                    self._state_attribute_number(state, "current_tilt_position"),
                )
            else:
                observation.phase = "baseline"
        await super()._clear_cover_pause(room, cover, **kwargs)
