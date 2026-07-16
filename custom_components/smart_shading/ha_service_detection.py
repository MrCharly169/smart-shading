from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.const import STATE_ON
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_POSITION_TOLERANCE,
    DEFAULT_TILT_TOLERANCE,
    PAUSE_MANUAL,
    PAUSE_NEXT_SUNRISE,
    PAUSE_NEXT_SUNSET,
    PAUSE_TIMED,
)
from .models import CoverPauseRuntime

EVENT_CALL_SERVICE = "call_service"
ATTR_DOMAIN = "domain"
ATTR_SERVICE = "service"
ATTR_SERVICE_DATA = "service_data"

MANUAL_COVER_SERVICES = {
    "open_cover",
    "close_cover",
    "stop_cover",
    "toggle",
    "set_cover_position",
    "open_cover_tilt",
    "close_cover_tilt",
    "stop_cover_tilt",
    "set_cover_tilt_position",
}


@dataclass(slots=True)
class PendingManualServiceIntent:
    """One explicit HA cover command awaiting feedback from the same entity."""

    entity_id: str
    room_id: str
    cover_id: str
    service: str
    created_at: datetime
    requested_entity_ids: tuple[str, ...]
    context_id: str | None


class HomeAssistantServiceDetectionMixin:
    """Detect explicit external cover commands issued through Home Assistant."""

    async def async_start(self) -> None:
        """Start runtime and watch explicit HA cover service calls."""
        await super().async_start()
        self._unsubs.append(
            self.hass.bus.async_listen(
                EVENT_CALL_SERVICE, self._async_cover_service_called
            )
        )

    @staticmethod
    def _service_entity_ids(service_data: dict[str, Any]) -> list[str]:
        value = service_data.get("entity_id")
        if isinstance(value, str):
            return [value] if value.startswith("cover.") else []
        if isinstance(value, (list, tuple, set)):
            return [
                str(entity_id)
                for entity_id in value
                if str(entity_id).startswith("cover.")
            ]
        return []

    def _service_requests_movement(
        self, service: str, service_data: dict[str, Any], entity_id: str
    ) -> bool:
        """Return False for no-op calls such as opening an already open cover."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return True
        position = self._state_attribute_number(state, "current_position")
        tilt = self._state_attribute_number(state, "current_tilt_position")
        position_tolerance = float(
            self.config.get("position_tolerance", DEFAULT_POSITION_TOLERANCE)
        )
        tilt_tolerance = float(
            self.config.get("tilt_tolerance", DEFAULT_TILT_TOLERANCE)
        )

        if service == "set_cover_position":
            target = service_data.get("position")
            try:
                return (
                    position is None
                    or abs(position - float(target)) > position_tolerance
                )
            except (TypeError, ValueError):
                return True
        if service == "set_cover_tilt_position":
            target = service_data.get("tilt_position")
            try:
                return tilt is None or abs(tilt - float(target)) > tilt_tolerance
            except (TypeError, ValueError):
                return True
        if service == "open_cover":
            if position is None:
                return state.state != "open"
            return position < 100.0 - position_tolerance
        if service == "close_cover":
            if position is None:
                return state.state != "closed"
            return position > position_tolerance
        if service == "open_cover_tilt":
            return tilt is None or tilt < 100.0 - tilt_tolerance
        if service == "close_cover_tilt":
            return tilt is None or tilt > tilt_tolerance
        if service in {"stop_cover", "stop_cover_tilt"}:
            return state.state in {"opening", "closing"}
        return service == "toggle"

    def _manual_service_intents(self) -> dict[str, PendingManualServiceIntent]:
        intents = getattr(self, "_pending_manual_service_intents", None)
        if intents is None:
            intents = {}
            self._pending_manual_service_intents = intents
        return intents

    @staticmethod
    def _state_value(state, key: str) -> float | None:
        if state is None:
            return None
        value = state.attributes.get(key)
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _state_change_confirms_manual_intent(self, old_state, new_state) -> bool:
        """Confirm that the exact service target produced real cover feedback."""
        if old_state is None or new_state is None:
            return False
        if getattr(old_state, "state", None) in {
            "unknown",
            "unavailable",
            "none",
            "",
        }:
            return False
        if getattr(new_state, "state", None) in {
            "unknown",
            "unavailable",
            "none",
            "",
        }:
            return False

        if getattr(old_state, "state", None) != getattr(new_state, "state", None):
            if getattr(new_state, "state", None) in {
                "opening",
                "closing",
                "open",
                "closed",
            }:
                return True

        for key in ("current_position", "current_tilt_position"):
            before = self._state_value(old_state, key)
            after = self._state_value(new_state, key)
            if (
                before is not None
                and after is not None
                and abs(after - before) >= 0.5
            ):
                return True
        return False

    async def _async_cover_service_called(self, event) -> None:
        """Record external HA cover intent; pause only after that entity moves."""
        if event.data.get(ATTR_DOMAIN) != "cover":
            return
        service = str(event.data.get(ATTR_SERVICE) or "")
        if service not in MANUAL_COVER_SERVICES:
            return

        # Smart Shading's own service calls use a fresh internal context without
        # a user or parent. Dashboard/app calls have a user; scripts and
        # automations have a parent context.
        context = getattr(event, "context", None)
        if context is None or not (
            getattr(context, "user_id", None)
            or getattr(context, "parent_id", None)
        ):
            return

        service_data = dict(event.data.get(ATTR_SERVICE_DATA) or {})
        requested = tuple(dict.fromkeys(self._service_entity_ids(service_data)))
        context_id = getattr(context, "id", None)
        now = dt_util.now()
        intents = self._manual_service_intents()

        for entity_id in requested:
            match = self._find_cover_by_entity(entity_id)
            if not match or not self._service_requests_movement(
                service, service_data, entity_id
            ):
                continue
            room, cover = match
            intents[entity_id] = PendingManualServiceIntent(
                entity_id=entity_id,
                room_id=str(room["id"]),
                cover_id=self._cover_id(cover),
                service=service,
                created_at=now,
                requested_entity_ids=requested,
                context_id=context_id,
            )
            self._diag(
                "manual_cover_service_intent",
                force=True,
                room_id=room["id"],
                cover=cover.get("name", entity_id),
                entity_id=entity_id,
                service=service,
                requested_entity_ids=list(requested),
                context_id=context_id,
            )

    async def _async_state_changed(self, event) -> None:
        entity_id = str(event.data.get("entity_id") or "")
        intents = self._manual_service_intents()
        intent = intents.get(entity_id)
        if intent is not None:
            now = dt_util.now()
            if (now - intent.created_at).total_seconds() > 15.0:
                intents.pop(entity_id, None)
                self._diag(
                    "manual_cover_service_intent_expired",
                    force=True,
                    entity_id=entity_id,
                    service=intent.service,
                )
            elif self._state_change_confirms_manual_intent(
                event.data.get("old_state"), event.data.get("new_state")
            ):
                intents.pop(entity_id, None)
                match = self._find_cover_by_entity(entity_id)
                if match:
                    room, cover = match
                    if (
                        str(room["id"]) == intent.room_id
                        and self._cover_id(cover) == intent.cover_id
                    ):
                        await self._activate_cover_pause(
                            room, cover, "home_assistant_manual_service"
                        )
                        self._diag(
                            "manual_cover_service_detected",
                            force=True,
                            room_id=room["id"],
                            cover=cover.get("name", entity_id),
                            entity_id=entity_id,
                            service=intent.service,
                            requested_entity_ids=list(intent.requested_entity_ids),
                            context_id=intent.context_id,
                        )
                        if self._room_safety_active(room):
                            await self.async_evaluate_all(
                                f"safety_manual_cover_service:{room['id']}"
                            )
                        return

        await super()._async_state_changed(event)

    def _configured_cover_pause_until(
        self, room: dict[str, Any], now: datetime
    ) -> tuple[str, datetime | None]:
        """Calculate a local pause from the room's wizard configuration."""
        room_id = room["id"]
        mode = str(
            self.room_value(
                room_id,
                "default_pause_mode",
                room.get("default_pause_mode", PAUSE_NEXT_SUNRISE),
            )
        )
        if mode in {PAUSE_NEXT_SUNRISE, PAUSE_NEXT_SUNSET}:
            due = self._pause_until_from_sun(room_id, mode, now)
            return mode, due or (now + timedelta(hours=12))
        if mode == PAUSE_TIMED:
            hours = float(
                self.room_value(
                    room_id,
                    "pause_duration_hours",
                    room.get("pause_duration_hours", 2.0),
                )
            )
            return mode, now + timedelta(hours=hours)
        if mode == PAUSE_MANUAL:
            return mode, None

        # A malformed legacy value must not create an unintended endless pause.
        due = self._pause_until_from_sun(room_id, PAUSE_NEXT_SUNRISE, now)
        return PAUSE_NEXT_SUNRISE, due or (now + timedelta(hours=12))

    async def _activate_cover_pause(
        self,
        room: dict[str, Any],
        cover: dict[str, Any],
        reason: str,
        *,
        set_lock: bool = True,
        notify: bool = True,
    ) -> None:
        """Activate only this cover using the pause mode chosen in the wizard."""
        entity_id = str(cover.get("entity") or "")
        observation = self.cover_motion.get(entity_id)
        if observation is not None:
            self._clear_motion_candidate(observation)
            observation.phase = "paused"

        cover_id = self._cover_id(cover)
        pause = self.cover_pauses.get(cover_id) or CoverPauseRuntime(
            cover_id, entity_id, room["id"]
        )
        now = dt_util.now()
        already_active = bool(
            pause.active and (pause.until is None or pause.until > now)
        )
        pause_mode = str(
            self.room_value(
                room["id"],
                "default_pause_mode",
                room.get("default_pause_mode", PAUSE_NEXT_SUNRISE),
            )
        )

        if not already_active:
            pause.active = True
            pause_mode, pause.until = self._configured_cover_pause_until(room, now)
            pause.reason = reason
            pause.started_at = now
            pause.lock_owned = False

        lock = str(cover.get("lock") or "")
        if set_lock and lock and not self.hass.states.is_state(lock, STATE_ON):
            domain = lock.split(".", 1)[0] if "." in lock else ""
            if domain in {"switch", "input_boolean"}:
                self._owned_lock_changes[lock] = (STATE_ON, now)
                await self.hass.services.async_call(
                    domain,
                    "turn_on",
                    {"entity_id": lock},
                    blocking=False,
                )
                pause.lock_owned = True

        self.cover_pauses[cover_id] = pause
        await self._save_cover_pause(pause)
        if pause.until:
            self._schedule_cover_pause_timer(cover_id, pause.until)
        else:
            timer = self._cover_pause_timer_unsubs.pop(cover_id, None)
            if timer:
                timer()

        if not already_active:
            self._diag(
                "cover_pause_started",
                room_id=room["id"],
                cover=cover.get("name", entity_id),
                pause_mode=pause_mode,
                until=pause.until.isoformat() if pause.until else None,
                reason=reason,
            )
        if notify:
            self._notify()
