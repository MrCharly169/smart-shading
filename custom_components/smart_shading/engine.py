from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components.cover import CoverEntityFeature
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import (
    CARD_RESOURCE,
    CONF_ADVANCED_MODE,
    CONF_DIAGNOSTIC_LEVEL,
    CONF_EVALUATION_INTERVAL,
    CONF_EXTERNAL_MOVEMENT_DETECTION,
    CONF_ROOMS,
    CONF_SUN_PRESENCE_ENTITY,
    CONF_SUN_ENTITY,
    DAY_WINDOW_ALL_DAY,
    DAY_WINDOW_FIXED,
    DEFAULT_COMMAND_COOLDOWN,
    DEFAULT_EVALUATION_INTERVAL,
    DEFAULT_POSITION_TOLERANCE,
    DEFAULT_TILT_TOLERANCE,
    DIAGNOSTIC_EVENTS,
    DIAGNOSTIC_FULL,
    DIAGNOSTIC_OFF,
    DEVICE_AWNING,
    DEVICE_BINARY,
    DEVICE_CURTAIN,
    DEVICE_VERTICAL,
    DEVICE_VENETIAN,
    DOMAIN,
    MODE_COMFORT,
    MODE_DISABLED,
    MODE_FINISHED,
    MODE_HEAT,
    MODE_IDLE,
    MODE_NIGHT,
    MODE_OPEN,
    MODE_PAUSED,
    MODE_SAFETY,
    MODE_SOLAR,
    OUTSIDE_OPEN,
    PAUSE_AUTO,
    PAUSE_DURATION_MAX_HOURS,
    PAUSE_DURATION_MIN_HOURS,
    PAUSE_MANUAL,
    PAUSE_NEXT_NIGHT_END,
    PAUSE_NEXT_SUNRISE,
    PAUSE_NEXT_SUNSET,
    PAUSE_TIMED,
    PRESET_CUSTOM,
    PRESET_MEDIUM,
    PROFILE_DEFAULTS,
    profile_supports_position,
    SUN_PRESETS,
    VERSION,
    WINDOW_POLICY_BLOCK_ALL,
    WINDOW_POLICY_BLOCK_CLOSING,
)
from .logic import (
    adaptive_tilt,
    azimuth_inside,
    clamp_percent,
    classify_cover_feedback,
    parse_numeric_value,
    sun_presence_step,
)
from .flow_contract import sun_source_for_sector, working_config
from .models import (
    CommandMemory,
    CoverPauseRuntime,
    OwnCommandSession,
    RoomRuntime,
    SectorSunRuntime,
)
from .storage import RuntimeStore

_LOGGER = logging.getLogger(__name__)
OWN_COMMAND_SESSION_TIMEOUT_SECONDS = 180.0

def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return dt_util.parse_datetime(value)
    return None


def _serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _state_valid(hass: HomeAssistant, entity_id: str) -> bool:
    state = hass.states.get(entity_id) if entity_id else None
    return state is not None and state.state not in {
        "unknown",
        "unavailable",
        "none",
        "",
    }


def _state_number(hass: HomeAssistant, entity_id: str) -> float | None:
    """Return a numeric entity state, or None when it cannot be parsed."""
    state = hass.states.get(entity_id) if entity_id else None
    if state is None:
        return None
    return parse_numeric_value(state.state)


def _temperature_celsius(value: Any, unit: Any = None) -> float | None:
    """Normalize a Home Assistant temperature value to degrees Celsius."""
    parsed = parse_numeric_value(value)
    if parsed is None:
        return None
    normalized_unit = str(unit or "").strip().lower().replace("°", "")
    if normalized_unit in {"f", "fahrenheit", "degf"}:
        return (parsed - 32.0) * 5.0 / 9.0
    if normalized_unit in {"k", "kelvin"}:
        return parsed - 273.15
    return parsed


def _temperature_state_celsius(
    hass: HomeAssistant,
    entity_id: str,
    *,
    attribute: str | None = None,
) -> float | None:
    """Read a valid entity temperature and normalize it to Celsius."""
    state = hass.states.get(entity_id) if entity_id else None
    if state is None or str(state.state).lower() in {
        "unknown",
        "unavailable",
        "none",
        "",
    }:
        return None
    if attribute:
        value = state.attributes.get(attribute)
        unit = (
            state.attributes.get(f"{attribute}_unit")
            or state.attributes.get("temperature_unit")
            or state.attributes.get("unit_of_measurement")
        )
    else:
        value = state.state
        unit = state.attributes.get("unit_of_measurement")
    return _temperature_celsius(value, unit)


def _is_on(hass: HomeAssistant, entity_id: str) -> bool:
    return bool(entity_id) and hass.states.is_state(entity_id, STATE_ON)


def _friendly_state_name(hass: HomeAssistant, entity_id: str, fallback: str) -> str:
    state = hass.states.get(entity_id) if entity_id else None
    if state:
        return str(state.attributes.get("friendly_name") or fallback)
    return fallback


async def _async_set_boolean_entity(
    hass: HomeAssistant, entity_id: str, enabled: bool
) -> None:
    """Turn a configured switch or input_boolean on/off."""
    if not entity_id or "." not in entity_id:
        return
    domain = entity_id.split(".", 1)[0]
    if domain not in {"switch", "input_boolean"}:
        _LOGGER.warning("Unsupported manual lock entity domain for %s", entity_id)
        return
    await hass.services.async_call(
        domain,
        "turn_on" if enabled else "turn_off",
        {"entity_id": entity_id},
        blocking=False,
    )


class SmartShadingEngine:
    """House-level adaptive shading controller."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        self.hass = hass
        self.entry = entry
        self.store = RuntimeStore(hass, entry.entry_id)
        self.config: dict[str, Any] = {}
        self.rooms: dict[str, RoomRuntime] = {}
        self.sun_runtime: dict[str, SectorSunRuntime] = {}
        self.command_memory: dict[str, CommandMemory] = {}
        self.own_command_sessions: dict[str, OwnCommandSession] = {}
        self.cover_pauses: dict[str, CoverPauseRuntime] = {}
        self._cover_pause_timer_unsubs: dict[str, Callable[[], None]] = {}
        self._room_pause_timer_unsubs: dict[str, Callable[[], None]] = {}
        self._night_timer_unsubs: dict[str, Callable[[], None]] = {}
        self._owned_lock_changes: dict[str, tuple[str, datetime]] = {}
        self.diagnostic_journal: deque[dict[str, Any]] = deque(maxlen=1000)
        self._last_logged_mode: dict[str, str] = {}
        self._current_trigger = "startup"
        self._listeners: list[Callable[[], None]] = []
        self._last_diag_signature: dict[str, datetime] = {}
        self._unsubs: list[Callable[[], None]] = []
        self._sun_timer_unsubs: dict[str, Callable[[], None]] = {}
        self._evaluate_lock = asyncio.Lock()
        self._day_key: str | None = None
        self.reload_config()

    def _begin_own_command_session(
        self,
        entity_id: str,
        axis: str,
        target: float,
        now: datetime,
    ) -> OwnCommandSession:
        """Claim feedback before dispatching a Smart Shading cover command."""
        session = self.own_command_sessions.get(entity_id)
        if (
            session is None
            or now > session.expires_at
            or session.target_reached_at is not None
        ):
            session = OwnCommandSession(
                entity_id=entity_id,
                started_at=now,
                updated_at=now,
                expires_at=now + timedelta(
                    seconds=OWN_COMMAND_SESSION_TIMEOUT_SECONDS
                ),
            )
            self.own_command_sessions[entity_id] = session

        session.updated_at = now
        session.expires_at = now + timedelta(
            seconds=OWN_COMMAND_SESSION_TIMEOUT_SECONDS
        )
        session.target_reached_at = None
        if axis == "position":
            session.position_target = float(target)
            session.position_commanded = True
        elif axis == "tilt":
            session.tilt_target = float(target)
            session.tilt_commanded = True
        else:
            raise ValueError(f"unsupported cover command axis {axis!r}")
        return session

    def _cancel_own_command_session(self, entity_id: str) -> None:
        """Release feedback ownership after an explicit external override."""
        self.own_command_sessions.pop(entity_id, None)

    def _entity_display_name(self, entity_id: str, fallback: str) -> str:
        return _friendly_state_name(self.hass, entity_id, fallback)

    async def async_initialize(self) -> None:
        await self.store.async_load()
        self._day_key = self.store.day_key()
        self._rebuild_runtime()
        await self._async_reconcile_night_end_pauses()

    def reload_config(self) -> None:
        self.config = working_config(self.entry.data, self.entry.options)

    def _rebuild_runtime(self) -> None:
        configured_room_ids: set[str] = set()
        configured_sector_ids: set[str] = set()

        for room in self.config.get(CONF_ROOMS, []):
            room_id = room["id"]
            configured_room_ids.add(room_id)
            saved = self.store.room_runtime(room_id)
            runtime = self.rooms.get(room_id) or RoomRuntime(
                room_id=room_id, name=room["name"]
            )
            runtime.name = room["name"]
            runtime.enabled = bool(saved.get("enabled", room.get("enabled", True)))
            legacy_pause_modes = {
                "Auto": PAUSE_AUTO,
                "Today": PAUSE_NEXT_SUNRISE,
                "Timed": PAUSE_TIMED,
                "Manual": PAUSE_MANUAL,
            }
            saved_pause_mode = saved.get("pause_mode", PAUSE_AUTO)
            runtime.pause_mode = legacy_pause_modes.get(saved_pause_mode, saved_pause_mode)
            runtime.pause_hours = self._configured_pause_duration(
                room_id, room
            )
            runtime.pause_until = _parse_datetime(saved.get("pause_until"))
            runtime.pause_waiting_for_night = bool(
                saved.get("pause_waiting_for_night", False)
            )
            runtime.heat_active = bool(saved.get("heat_active", False))
            runtime.shading_active = bool(saved.get("shading_active", False))
            runtime.finished_today = bool(saved.get("finished_today", False))
            runtime.sent_commands = int(saved.get("sent_commands", 0))
            runtime.suppressed_commands = int(
                saved.get("suppressed_commands", 0)
            )
            self.rooms[room_id] = runtime
            if (
                self.advanced_mode
                and runtime.pause_mode
                in {PAUSE_NEXT_SUNRISE, PAUSE_NEXT_SUNSET, PAUSE_TIMED}
                and runtime.pause_until
            ):
                if runtime.pause_until > dt_util.now():
                    self._schedule_room_pause_timer(room_id, runtime.pause_until)
                else:
                    runtime.pause_mode = PAUSE_AUTO
                    runtime.pause_until = None

            for sector in room.get("sectors", []):
                sector_id = sector["id"]
                configured_sector_ids.add(sector_id)
                saved_sun = self.store.sun_runtime(sector_id)
                sun = self.sun_runtime.get(sector_id) or SectorSunRuntime(
                    sector_id=sector_id
                )
                sun.is_on = bool(saved_sun.get("is_on", False))
                sun.pending_target = saved_sun.get("pending_target")
                sun.pending_since = _parse_datetime(saved_sun.get("pending_since"))
                sun.pending_until = _parse_datetime(saved_sun.get("pending_until"))
                sun.last_transition = _parse_datetime(
                    saved_sun.get("last_transition")
                )
                sun.reason = saved_sun.get("reason", "Not evaluated")
                sun.status = saved_sun.get("status", "not_evaluated")
                sun.status_reason = saved_sun.get("status_reason", sun.reason)
                sun.geometry_active = bool(saved_sun.get("geometry_active", False))
                sun.shading_active = bool(saved_sun.get("shading_active", False))
                sun.mode = saved_sun.get("mode", "idle")
                self.sun_runtime[sector_id] = sun

        for room_id in list(self.rooms):
            if room_id not in configured_room_ids:
                self.rooms.pop(room_id)
        for sector_id in list(self.sun_runtime):
            if sector_id not in configured_sector_ids:
                self.sun_runtime.pop(sector_id)
        configured_cover_ids: set[str] = set()
        for room in self.config.get(CONF_ROOMS, []):
            for sector in room.get("sectors", []):
                for layer in sector.get("layers", []):
                    for cover in layer.get("covers", []):
                        cover_id = cover.get("id") or cover.get("entity")
                        configured_cover_ids.add(cover_id)
                        saved_cover = self.store.cover_runtime(cover_id)
                        pause = self.cover_pauses.get(cover_id) or CoverPauseRuntime(
                            cover_id=cover_id, entity_id=cover.get("entity", ""), room_id=room["id"]
                        )
                        pause.entity_id = cover.get("entity", "")
                        pause.room_id = room["id"]
                        pause.active = bool(saved_cover.get("active", False))
                        pause.until = _parse_datetime(saved_cover.get("until"))
                        pause.reason = str(saved_cover.get("reason", ""))
                        pause.lock_owned = bool(saved_cover.get("lock_owned", False))
                        pause.started_at = _parse_datetime(saved_cover.get("started_at"))
                        pause.pause_mode = str(saved_cover.get("pause_mode", PAUSE_AUTO))
                        pause.waiting_for_night = bool(
                            saved_cover.get("waiting_for_night", False)
                        )
                        self.cover_pauses[cover_id] = pause
                        if self.advanced_mode and pause.active and pause.until:
                            self._schedule_cover_pause_timer(cover_id, pause.until)
        for cover_id in list(self.cover_pauses):
            if cover_id not in configured_cover_ids:
                self.cover_pauses.pop(cover_id, None)

    async def async_start(self) -> None:
        self.async_stop()
        self.reload_config()
        self._rebuild_runtime()
        await self._async_reconcile_night_end_pauses()
        await self._async_sync_sun_requirement_notification()

        entities = sorted(self.referenced_entities())
        if entities:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, entities, self._async_state_changed
                )
            )

        interval = max(
            30,
            int(
                self.config.get(
                    CONF_EVALUATION_INTERVAL, DEFAULT_EVALUATION_INTERVAL
                )
            ),
        )
        self._unsubs.append(
            async_track_time_interval(
                self.hass,
                self._async_interval,
                timedelta(seconds=interval),
            )
        )
        await self._async_sync_configured_locks()
        for room_id, runtime in self.rooms.items():
            if self.advanced_mode and runtime.pause_mode != PAUSE_AUTO:
                await self._async_room_pause_state_changed(room_id, True)
        await self.async_evaluate_all("startup")
        notifications_ready = await self.async_sync_card_notifications()
        if not notifications_ready:
            self._schedule_card_notification_retry(1)

    async def _async_sync_sun_requirement_notification(self) -> None:
        entity_id = self.config.get(CONF_SUN_ENTITY, "sun.sun")
        state = self.hass.states.get(entity_id)
        notification_id = f"smart_shading_sun_{self.entry.entry_id}"
        invalid = state is None or state.state in {"unknown", "unavailable"}
        if invalid:
            german = (getattr(self.hass.config, "language", "en") or "en").lower().startswith("de")
            title = "Smart Shading – Sonnenentität fehlt" if german else "Smart Shading – Sun entity unavailable"
            message = (
                "`sun.sun` fehlt oder ist nicht verfügbar. Prüfen Sie Standort, Zeitzone und Sonnenintegration. Sektorbasierte Beschattung bleibt bis zur Behebung inaktiv."
                if german else
                "`sun.sun` is missing or unavailable. Check location, time zone and the Sun integration. Sector-based shading remains inactive until this is fixed."
            )
            await self.hass.services.async_call(
                "persistent_notification", "create",
                {"title": title, "message": message, "notification_id": notification_id},
                blocking=False,
            )
        else:
            await self.hass.services.async_call(
                "persistent_notification", "dismiss",
                {"notification_id": notification_id}, blocking=False,
            )

    def _schedule_card_notification_retry(self, attempt: int) -> None:
        """Retry notification generation until room entities are registered."""
        delays = (1, 3, 10, 30)
        if attempt > len(delays):
            return

        async def _retry(_now) -> None:
            ready = await self.async_sync_card_notifications()
            if not ready:
                self._schedule_card_notification_retry(attempt + 1)

        self._unsubs.append(async_call_later(self.hass, delays[attempt - 1], _retry))

    async def async_sync_card_notifications(self) -> bool:
        """Create one persistent card-code notification for each new room.

        Return True when every configured room status entity was available.
        """
        registry = er.async_get(self.hass)
        previous_ids = set(self.store.card_notification_ids())
        configured_ids = {
            f"smart_shading_card_{self.entry.entry_id}_{room['id']}"
            for room in self.config.get(CONF_ROOMS, [])
        }
        successful_ids = previous_ids & configured_ids
        missing_entities = 0
        german = (getattr(self.hass.config, "language", "en") or "en").lower().startswith("de")

        for room in self.config.get(CONF_ROOMS, []):
            room_id = room["id"]
            notification_id = f"smart_shading_card_{self.entry.entry_id}_{room_id}"
            if notification_id in previous_ids:
                continue
            unique_id = f"{self.entry.entry_id}_{room_id}_status"
            entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
            if entity_id is None:
                missing_entities += 1
                _LOGGER.debug("Room status entity not yet registered for %s", room.get("name"))
                continue

            card_yaml = (
                "type: custom:smart-shading-card\n"
                f"entity: {entity_id}\n"
            )
            if german:
                title = f"Smart Shading – Dashboard-Karte für {room['name']}"
                message = (
                    "Der Raum wurde erstellt. Der folgende Code fügt seine "
                    "Smart-Shading-Karte zum Dashboard hinzu.\n\n"
                    "```yaml\n"
                    f"{card_yaml}"
                    "```\n\n"
                    "**So fügen Sie die Karte ein:** Dashboard bearbeiten → Karte "
                    "hinzufügen → Manuell → Code einfügen → Speichern.\n\n"
                    f"Falls die Karte noch nicht registriert ist, fügen Sie unter "
                    f"Dashboard-Ressourcen `{CARD_RESOURCE}` als JavaScript-Modul hinzu.\n\n"
                    f"Verwendete Raumstatus-Entität: `{entity_id}`"
                )
            else:
                title = f"Smart Shading – Dashboard card for {room['name']}"
                message = (
                    "The room was created. The following code adds its Smart "
                    "Shading card to a dashboard.\n\n"
                    "```yaml\n"
                    f"{card_yaml}"
                    "```\n\n"
                    "**Add the card:** Edit dashboard → Add card → Manual → paste "
                    "the code → Save.\n\n"
                    f"If the card resource is not registered yet, add `{CARD_RESOURCE}` "
                    "as a JavaScript module in Dashboard resources.\n\n"
                    f"Room status entity: `{entity_id}`"
                )
            try:
                await self.hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": title,
                        "message": message,
                        "notification_id": notification_id,
                    },
                    blocking=True,
                )
                successful_ids.add(notification_id)
            except Exception:
                missing_entities += 1
                _LOGGER.exception("Could not create Smart Shading card notification")

        for stale_id in previous_ids - configured_ids:
            try:
                await self.hass.services.async_call(
                    "persistent_notification",
                    "dismiss",
                    {"notification_id": stale_id},
                    blocking=True,
                )
            except Exception:
                _LOGGER.exception("Could not dismiss stale Smart Shading notification")
        await self.store.async_set_card_notification_ids(sorted(successful_ids))
        return missing_entities == 0

    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for unsub in self._sun_timer_unsubs.values():
            unsub()
        self._sun_timer_unsubs.clear()
        for unsub in self._cover_pause_timer_unsubs.values():
            unsub()
        self._cover_pause_timer_unsubs.clear()
        for unsub in self._room_pause_timer_unsubs.values():
            unsub()
        self._room_pause_timer_unsubs.clear()
        for unsub in self._night_timer_unsubs.values():
            unsub()
        self._night_timer_unsubs.clear()

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    async def _async_state_changed(self, event) -> None:
        entity_id = event.data.get("entity_id")
        if not self.advanced_mode:
            if entity_id in self._easy_reactive_entities():
                await self.async_evaluate_all(f"easy_input_state:{entity_id}")
            return
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        now = dt_util.now()

        cover_match = self._find_cover_by_entity(entity_id)
        if cover_match:
            room, cover = cover_match
            decision = self._classify_cover_state_change(entity_id, old_state, new_state, now)
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
                # Safety always overrides a local manual pause. If a user moves
                # a cover while a safety blocker is active, immediately restore
                # the configured safe position instead of waiting for the next
                # 20-minute evaluation.
                if self._room_safety_active(room):
                    await self.async_evaluate_all(
                        f"safety_manual_cover:{entity_id}"
                    )
            return

        lock_groups = self._find_cover_groups_by_lock(entity_id)
        if lock_groups:
            old_value = getattr(old_state, "state", None)
            new_value = getattr(new_state, "state", None)
            owned_change = self._owned_lock_changes.get(entity_id)
            if owned_change:
                expected_state, owned_at = owned_change
                if (
                    new_value == expected_state
                    and (now - owned_at).total_seconds() < 10
                ):
                    self._owned_lock_changes.pop(entity_id, None)
                    return
                # KNX can repeat its old state before acknowledging our write.
                # An identical off -> off refresh must never cancel the pause.
                if old_value == new_value:
                    return
                self._owned_lock_changes.pop(entity_id, None)
            elif old_value == new_value:
                return
            if new_value == STATE_ON:
                for room, covers in lock_groups:
                    await self._activate_cover_pause(
                        room,
                        covers[0],
                        "manual_lock_entity",
                        set_lock=False,
                    )
            elif new_value == STATE_OFF:
                changed = False
                for room, covers in lock_groups:
                    if any(
                        bool(
                            (pause := self.cover_pauses.get(self._cover_id(cover)))
                            and pause.active
                        )
                        for cover in covers
                    ):
                        changed = True
                    await self._clear_cover_pause(
                        room, covers[0], unlock=False, evaluate=False
                    )
                if changed:
                    await self.async_evaluate_all(
                        f"manual_group_released:{entity_id}"
                    )
            return

        if self._is_critical_entity(entity_id):
            await self.async_evaluate_all(f"critical_state:{entity_id}")
            return

        sector = self._find_sector_by_lux(entity_id)
        if sector:
            room = self._find_room_for_sector(sector["id"])
            room_sun_before = (
                self._room_heat_sun_present(room) if room is not None else False
            )
            runtime = self.sun_runtime[sector["id"]]
            before = runtime.is_on
            await self._update_sun_presence(sector, now)
            room_sun_after = (
                self._room_heat_sun_present(room) if room is not None else False
            )
            if (
                room is not None
                and bool(room.get("heat_requires_sun", True))
                and not room_sun_before
                and room_sun_after
            ):
                await self.async_evaluate_all(
                    f"heat_sun_presence:{room['id']}:{sector['id']}"
                )
                return
            if before != runtime.is_on:
                self._diag(
                    "sun_presence_transition_deferred_to_interval",
                    sector_id=sector["id"],
                    state="on" if runtime.is_on else "off",
                )
            self._notify()
            return

        # Normal sun, temperature and cover feedback are consolidated by the
        # configured periodic evaluation (20 minutes by default).
        self._diag("state_change_deferred", full=True, entity_id=entity_id)

    async def _async_interval(self, now) -> None:
        await self.async_evaluate_all("interval")

    def _iter_covers(self):
        for room in self.config.get(CONF_ROOMS, []):
            for sector in room.get("sectors", []):
                for layer in sector.get("layers", []):
                    for cover in layer.get("covers", []):
                        yield room, sector, layer, cover

    def _find_cover_context(self, entity_id: str):
        return next(
            (
                (room, sector, layer, cover)
                for room, sector, layer, cover in self._iter_covers()
                if cover.get("entity") == entity_id
            ),
            None,
        )

    @staticmethod
    def _layer_tolerances(layer: dict[str, Any]) -> tuple[float, float]:
        profile = str(layer.get("profile", DEVICE_VENETIAN))
        defaults = PROFILE_DEFAULTS.get(
            profile, PROFILE_DEFAULTS[DEVICE_VENETIAN]
        )
        return (
            float(
                layer.get(
                    "position_tolerance",
                    defaults.get(
                        "position_tolerance", DEFAULT_POSITION_TOLERANCE
                    ),
                )
            ),
            float(
                layer.get(
                    "tilt_tolerance",
                    defaults.get("tilt_tolerance", DEFAULT_TILT_TOLERANCE),
                )
            ),
        )

    def _find_cover_by_entity(self, entity_id: str):
        return next(((room, cover) for room, _sector, _layer, cover in self._iter_covers() if cover.get("entity") == entity_id), None)

    def _cover_tolerances(self, entity_id: str) -> tuple[float, float]:
        context = self._find_cover_context(entity_id)
        if context is None:
            return DEFAULT_POSITION_TOLERANCE, DEFAULT_TILT_TOLERANCE
        return self._layer_tolerances(context[2])

    async def _async_enforce_cover_maximum(
        self, entity_id: str, state=None
    ) -> bool:
        """Correct one opt-in hard opening violation without command spam."""
        if not self.advanced_mode:
            return False
        context = self._find_cover_context(entity_id)
        if context is None:
            return False
        room, _sector, layer, cover = context
        profile = str(layer.get("profile", DEVICE_VENETIAN))
        if (
            not profile_supports_position(profile)
            or not bool(cover.get("enforce_max_open_position", False))
            or self._room_safety_active(room)
        ):
            return False
        state = state or self.hass.states.get(entity_id)
        current = self._state_attribute_number(state, "current_position")
        if current is None:
            return False
        logical_current = (
            100.0 - float(current)
            if bool(cover.get("invert_position", False))
            else float(current)
        )
        maximum = clamp_percent(
            float(cover.get("max_open_position", 100.0))
        )
        position_tolerance, _tilt_tolerance = self._layer_tolerances(layer)
        if logical_current <= maximum + position_tolerance:
            return False
        supported_features = int(
            state.attributes.get("supported_features", 0) if state else 0
        )
        if not supported_features & int(CoverEntityFeature.SET_POSITION):
            return False
        command_position = (
            100.0 - maximum
            if bool(cover.get("invert_position", False))
            else maximum
        )
        now = dt_util.now()
        memory = self.command_memory.setdefault(entity_id, CommandMemory())
        if (
            memory.position == command_position
            and memory.position_at is not None
            and (now - memory.position_at).total_seconds()
            < DEFAULT_COMMAND_COOLDOWN
        ):
            return True
        self._begin_own_command_session(
            entity_id, "position", command_position, now
        )
        await self.hass.services.async_call(
            "cover",
            "set_cover_position",
            {
                "entity_id": entity_id,
                "position": round(command_position),
            },
            blocking=False,
        )
        memory.position = command_position
        memory.position_at = now
        memory.last_activity_at = now
        self._diag(
            "maximum_opening_enforced",
            force=True,
            room_id=room.get("id"),
            cover=cover.get("name", entity_id),
            entity_id=entity_id,
            detected=round(logical_current),
            maximum=round(maximum),
        )
        return True

    async def _async_enforce_all_maximum_openings(self) -> None:
        for _room, _sector, _layer, cover in self._iter_covers():
            if bool(cover.get("enforce_max_open_position", False)):
                await self._async_enforce_cover_maximum(
                    str(cover.get("entity") or "")
                )

    def _find_cover_by_lock(self, entity_id: str):
        return next(((room, cover) for room, _sector, _layer, cover in self._iter_covers() if cover.get("lock") == entity_id), None)

    def _find_cover_groups_by_lock(
        self, entity_id: str
    ) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
        """Return every room-local group using exactly this Manual entity."""
        entity_id = str(entity_id or "").strip()
        if not entity_id:
            return []
        groups: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        for room in self.config.get(CONF_ROOMS, []):
            covers = [
                cover
                for candidate_room, _sector, _layer, cover in self._iter_covers()
                if str(candidate_room.get("id")) == str(room.get("id"))
                and str(cover.get("lock") or "").strip() == entity_id
            ]
            if covers:
                groups.append((room, covers))
        return groups

    def _manual_group_members(
        self, room: dict[str, Any], cover: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Resolve one exact Manual entity to all covers in the same room."""
        lock = str(cover.get("lock") or "").strip()
        if not lock:
            return [cover]
        room_id = str(room.get("id"))
        for candidate_room, covers in self._find_cover_groups_by_lock(lock):
            if str(candidate_room.get("id")) == room_id:
                return covers
        return [cover]

    def manual_override_groups(self, room_id: str) -> list[dict[str, Any]]:
        """Expose normalized room-local Manual groups for diagnostics and UI."""
        grouped: dict[str, list[dict[str, Any]]] = {}
        for room, _sector, _layer, cover in self._iter_covers():
            if str(room.get("id")) != str(room_id):
                continue
            lock = str(cover.get("lock") or "").strip()
            if lock:
                grouped.setdefault(lock, []).append(cover)
        return [
            {
                "entity_id": entity_id,
                "covers": [str(cover.get("entity") or "") for cover in covers],
                "cover_ids": [self._cover_id(cover) for cover in covers],
                "size": len(covers),
            }
            for entity_id, covers in sorted(grouped.items())
        ]

    def _find_sector_by_lux(self, entity_id: str):
        for room in self.config.get(CONF_ROOMS, []):
            for sector in room.get("sectors", []):
                if sector.get("lux_sensor") == entity_id:
                    return sector
        return None

    def _find_sectors_by_source(self, entity_id: str) -> list[dict[str, Any]]:
        """Return every sector using a confirmation source.

        A single facade sensor is commonly shared by multiple sectors.  The
        state listener therefore must never stop after the first match.
        """
        return [
            sector
            for room in self.config.get(CONF_ROOMS, [])
            for sector in room.get("sectors", [])
            if entity_id
            and entity_id
            in {
                sector.get(CONF_SUN_PRESENCE_ENTITY, ""),
                sector.get("lux_sensor", ""),
            }
        ]

    def _easy_reactive_entities(self) -> set[str]:
        result = {self.config.get(CONF_SUN_ENTITY, "sun.sun")}
        for room in self.config.get(CONF_ROOMS, []):
            if room.get("outdoor_temperature"):
                result.add(room["outdoor_temperature"])
            for sector in room.get("sectors", []):
                for key in (CONF_SUN_PRESENCE_ENTITY, "lux_sensor"):
                    if sector.get(key):
                        result.add(sector[key])
        return {entity_id for entity_id in result if entity_id}

    def _find_room_for_sector(self, sector_id: str):
        return next(
            (
                room
                for room in self.config.get(CONF_ROOMS, [])
                if any(
                    str(sector.get("id")) == str(sector_id)
                    for sector in room.get("sectors", [])
                )
            ),
            None,
        )

    def _room_heat_sun_present(self, room: dict[str, Any]) -> bool:
        """Return whether any enabled sector has valid active Sun Presence."""
        for sector in room.get("sectors", []):
            if not bool(self.sector_value(sector["id"], "enabled", True)):
                continue
            confirmed, source, _entity, state = (
                self._advanced_sector_confirmation(sector)
            )
            if source in {"lux", "binary"} and confirmed and state is True:
                return True
        return False

    def _room_safety_active(self, room: dict[str, Any]) -> bool:
        return any(
            _is_on(self.hass, entity_id)
            for entity_id in room.get("safety_blockers", [])
        )

    def _is_critical_entity(self, entity_id: str) -> bool:
        if any(
            bool(self.config.get(CONF_ADVANCED_MODE, False))
            and room.get("night_enabled", False)
            and room.get("night_source", "entity") == "entity"
            and room.get("night_entity") == entity_id
            for room in self.config.get(CONF_ROOMS, [])
        ):
            return True
        if any(
            entity_id in room.get("safety_blockers", [])
            for room in self.config.get(CONF_ROOMS, [])
        ):
            return True
        return any(
            cover.get("window") == entity_id
            for _room, _sector, _layer, cover in self._iter_covers()
        )

    @staticmethod
    def _state_attribute_number(state, key: str) -> float | None:
        if state is None:
            return None
        return parse_numeric_value(state.attributes.get(key))

    def _classify_cover_state_change(
        self, entity_id: str, old_state, new_state, now: datetime
    ):
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
        context = self._find_cover_context(entity_id)
        position_tolerance, tilt_tolerance = (
            self._layer_tolerances(context[2])
            if context is not None
            else (DEFAULT_POSITION_TOLERANCE, DEFAULT_TILT_TOLERANCE)
        )
        return classify_cover_feedback(
            old_position=self._state_attribute_number(old_state, "current_position"),
            new_position=self._state_attribute_number(new_state, "current_position"),
            old_tilt=self._state_attribute_number(old_state, "current_tilt_position"),
            new_tilt=self._state_attribute_number(new_state, "current_tilt_position"),
            old_state=getattr(old_state, "state", None),
            new_state=getattr(new_state, "state", None),
            target_position=memory.position if memory else None,
            target_tilt=memory.tilt if memory else None,
            command_age_seconds=age,
            position_tolerance=position_tolerance,
            tilt_tolerance=tilt_tolerance,
            command_timeout_seconds=180.0,
            position_change_threshold=max(
                2.0,
                position_tolerance,
            ),
            tilt_change_threshold=max(
                3.0,
                tilt_tolerance,
            ),
        )

    def _cover_id(self, cover: dict[str, Any]) -> str:
        return str(cover.get("id") or cover.get("entity"))

    async def _activate_cover_pause(
        self,
        room: dict[str, Any],
        cover: dict[str, Any],
        reason: str,
        *,
        set_lock: bool = True,
        notify: bool = True,
    ) -> None:
        now = dt_util.now()
        members = self._manual_group_members(room, cover)
        active_pause = next(
            (
                pause
                for member in members
                if (
                    (pause := self.cover_pauses.get(self._cover_id(member)))
                    and pause.active
                    and (pause.until is None or pause.until > now)
                )
            ),
            None,
        )
        shared_until = (
            active_pause.until
            if active_pause is not None
            else self._pause_until_from_sun(
                room["id"], PAUSE_NEXT_SUNRISE, now
            ) or (now + timedelta(hours=12))
        )
        lock = str(cover.get("lock") or "").strip()
        wrote_lock = bool(set_lock and lock and not _is_on(self.hass, lock))
        if wrote_lock:
            self._owned_lock_changes[lock] = (STATE_ON, now)
            await _async_set_boolean_entity(self.hass, lock, True)

        started: list[str] = []
        for member in members:
            cover_id = self._cover_id(member)
            pause = self.cover_pauses.get(cover_id) or CoverPauseRuntime(
                cover_id, member.get("entity", ""), room["id"]
            )
            already_active = bool(
                pause.active and (pause.until is None or pause.until > now)
            )
            if not already_active:
                pause.active = True
                pause.until = shared_until
                pause.reason = reason
                pause.started_at = now
                pause.lock_owned = wrote_lock
                pause.pause_mode = PAUSE_NEXT_SUNRISE
                started.append(str(member.get("entity") or cover_id))
            self.cover_pauses[cover_id] = pause
            await self._save_cover_pause(pause)
            if pause.until:
                self._schedule_cover_pause_timer(cover_id, pause.until)

        if started:
            self._diag(
                "manual_override_group_started",
                room_id=room["id"],
                manual_entity=lock or None,
                covers=started,
                until=shared_until.isoformat() if shared_until else None,
                reason=reason,
            )
        if notify:
            self._notify()

    async def _clear_cover_pause(self, room: dict[str, Any], cover: dict[str, Any], *, unlock: bool, evaluate: bool) -> None:
        members = self._manual_group_members(room, cover)
        cleared: list[str] = []
        for member in members:
            cover_id = self._cover_id(member)
            pause = self.cover_pauses.get(cover_id)
            if not pause or not pause.active:
                continue
            pause.active = False
            pause.until = None
            pause.reason = ""
            pause.lock_owned = False
            pause.pause_mode = PAUSE_AUTO
            pause.waiting_for_night = False
            timer = self._cover_pause_timer_unsubs.pop(cover_id, None)
            if timer:
                timer()
            await self._save_cover_pause(pause)
            cleared.append(str(member.get("entity") or cover_id))

        # A shared group owns several independently scheduled callbacks.  A
        # sibling callback may already be queued when the first one cancels its
        # timer.  Once another callback has cleared the group, the stale one
        # must not write the Manual entity or trigger another evaluation.
        if not cleared:
            return

        lock = str(cover.get("lock") or "").strip()
        if unlock and lock:
            self._owned_lock_changes[lock] = (STATE_OFF, dt_util.now())
            await _async_set_boolean_entity(self.hass, lock, False)
        self._diag(
            "manual_override_group_ended",
            room_id=room["id"],
            manual_entity=lock or None,
            covers=cleared,
        )
        if evaluate:
            await self.async_evaluate_all(
                f"manual_group_released:{lock or self._cover_id(cover)}"
            )
        else:
            self._notify()

    async def _save_cover_pause(self, pause: CoverPauseRuntime) -> None:
        await self.store.async_save_cover_runtime(pause.cover_id, {
            "active": pause.active, "until": _serialize_datetime(pause.until), "reason": pause.reason,
            "lock_owned": pause.lock_owned, "started_at": _serialize_datetime(pause.started_at),
            "pause_mode": pause.pause_mode,
            "waiting_for_night": pause.waiting_for_night,
        })

    def _schedule_cover_pause_timer(self, cover_id: str, due: datetime) -> None:
        old = self._cover_pause_timer_unsubs.pop(cover_id, None)
        if old:
            old()
        seconds = max(0.1, (due - dt_util.now()).total_seconds())
        async def _expire(_now):
            self._cover_pause_timer_unsubs.pop(cover_id, None)
            for room, _sector, _layer, cover in self._iter_covers():
                if self._cover_id(cover) == cover_id:
                    await self._clear_cover_pause(room, cover, unlock=True, evaluate=True)
                    return
        self._cover_pause_timer_unsubs[cover_id] = async_call_later(self.hass, seconds, _expire)

    async def _async_sync_configured_locks(self) -> None:
        """Reconcile persisted local pauses with configured lock entities."""
        if not self.advanced_mode:
            return
        now = dt_util.now()
        processed_groups: set[tuple[str, str]] = set()
        for room, _sector, _layer, cover in self._iter_covers():
            lock = str(cover.get("lock") or "").strip()
            group_key = (
                str(room.get("id")),
                lock or f"cover:{self._cover_id(cover)}",
            )
            if group_key in processed_groups:
                continue
            processed_groups.add(group_key)

            members = self._manual_group_members(room, cover)
            pauses = [
                self.cover_pauses.get(self._cover_id(member))
                for member in members
            ]
            active_pauses = [pause for pause in pauses if pause and pause.active]

            # A Manual entity is one room-local lifecycle.  Clear an expired
            # persisted group exactly once.  The OFF service is intentionally
            # asynchronous, so processing sibling covers again could otherwise
            # observe the stale ON state and recreate the pause immediately.
            if any(
                pause.until is not None and pause.until <= now
                for pause in active_pauses
            ):
                await self._clear_cover_pause(
                    room, cover, unlock=bool(lock), evaluate=False
                )
                continue

            lock_state = self.hass.states.get(lock) if lock else None
            if lock_state and lock_state.state == STATE_ON:
                if len(active_pauses) != len(members):
                    await self._activate_cover_pause(
                        room,
                        cover,
                        "manual_lock_entity",
                        set_lock=False,
                        notify=False,
                    )
            elif lock_state and lock_state.state == STATE_OFF and active_pauses:
                # The user removed the external lock while Home Assistant was
                # offline; treat that as an early manual resume. Unknown or
                # unavailable locks never clear a persisted pause.
                await self._clear_cover_pause(
                    room, cover, unlock=False, evaluate=False
                )
        self._notify()

    def cover_pause_info(self, cover: dict[str, Any]) -> dict[str, Any]:
        pause = self.cover_pauses.get(self._cover_id(cover))
        active = bool(pause and pause.active and (pause.until is None or pause.until > dt_util.now()))
        return {
            "active": active,
            "until": pause.until if active else None,
            "reason": pause.reason if active else "",
            "pause_mode": pause.pause_mode if active else PAUSE_AUTO,
        }

    def referenced_entities(self) -> set[str]:
        result = {self.config.get(CONF_SUN_ENTITY, "sun.sun")}
        if not self.advanced_mode:
            result.update(self._easy_reactive_entities())
            return {entity for entity in result if entity}
        for room in self.config.get(CONF_ROOMS, []):
            for key in (
                "indoor_temperature",
                "outdoor_temperature",
                "irradiance_sensor",
                "cloud_cover_sensor",
                "weather_permission",
                "glare_sensor",
                "occupancy_sensor",
            ):
                if room.get(key):
                    result.add(room[key])
            if (
                self.config.get(CONF_ADVANCED_MODE, False)
                and room.get("night_enabled", False)
                and room.get("night_source", "entity") == "entity"
                and room.get("night_entity")
            ):
                result.add(room["night_entity"])
            result.update(room.get("safety_blockers", []))
            for sector in room.get("sectors", []):
                for key in ("lux_sensor", CONF_SUN_PRESENCE_ENTITY):
                    if sector.get(key):
                        result.add(sector[key])
                for layer in sector.get("layers", []):
                    for cover in layer.get("covers", []):
                        result.add(cover["entity"])
                        for key in ("lock", "window"):
                            if cover.get(key):
                                result.add(cover[key])
        return {entity for entity in result if entity}

    @staticmethod
    def _room_profiles(room: dict[str, Any]) -> set[str]:
        return {
            str(layer.get("profile", DEVICE_VENETIAN))
            for sector in room.get("sectors", [])
            for layer in sector.get("layers", [])
        }

    @classmethod
    def _venetian_only(cls, room: dict[str, Any]) -> bool:
        profiles = cls._room_profiles(room)
        return not profiles or profiles == {DEVICE_VENETIAN}

    def _mark_room_sectors(
        self, room: dict[str, Any], *, status: str, reason: str, mode: str, active: bool
    ) -> None:
        for sector in room.get("sectors", []):
            runtime = self.sun_runtime.get(sector["id"])
            if runtime is None:
                continue
            runtime.status = status
            runtime.status_reason = reason
            runtime.mode = mode
            runtime.shading_active = active
            # Easy Mode uses this field as its complete shading decision.
            # Advanced Mode assigns it from the real per-sector sun result
            # later in the evaluation.  Keeping that value here prevents a
            # room-wide Safety or Heat mode from falsely lighting every sun
            # sector in the card.
            if not self.advanced_mode:
                runtime.effective_active = active

    @property
    def diagnostic_level(self) -> str:
        default = str(
            self.config.get(
                CONF_DIAGNOSTIC_LEVEL,
                DIAGNOSTIC_OFF,
            )
        )
        value = str(
            self.store.get_override(
                "house", "house", CONF_DIAGNOSTIC_LEVEL, default
            )
        )
        return value if value in {DIAGNOSTIC_OFF, DIAGNOSTIC_EVENTS, DIAGNOSTIC_FULL} else DIAGNOSTIC_OFF

    @property
    def advanced_mode(self) -> bool:
        return bool(self.config.get(CONF_ADVANCED_MODE, False))

    async def async_set_diagnostic_level(self, level: str) -> None:
        if level not in {DIAGNOSTIC_OFF, DIAGNOSTIC_EVENTS, DIAGNOSTIC_FULL}:
            level = DIAGNOSTIC_OFF
        await self.store.async_set_override(
            "house", "house", CONF_DIAGNOSTIC_LEVEL, level
        )
        self._diag("diagnostic_level", level=level, force=True)
        self._notify()

    def _diag(self, event: str, *, full: bool = False, force: bool = False, **data: Any) -> None:
        level = self.diagnostic_level
        if not force and (level == DIAGNOSTIC_OFF or (full and level != DIAGNOSTIC_FULL)):
            return
        now = dt_util.now()
        signature = f"{event}|{data.get('room_id')}|{data.get('cover')}|{data.get('sector_id')}|{data.get('mode')}|{data.get('reasons')}|{data.get('state')}"
        last = self._last_diag_signature.get(signature)
        if not force and last is not None and (now - last).total_seconds() < 20:
            return
        self._last_diag_signature[signature] = now
        record = {
            "timestamp": now.isoformat(),
            "event": event,
            "trigger": self._current_trigger,
            **data,
        }
        self.diagnostic_journal.append(record)
        if full:
            _LOGGER.debug("Smart Shading diagnostic: %s", record)
        else:
            _LOGGER.info("Smart Shading event: %s", record)

    def recent_diagnostics(self, room_id: str | None = None, limit: int = 40) -> list[dict[str, Any]]:
        records = list(self.diagnostic_journal)
        if room_id:
            records = [item for item in records if item.get("room_id") in {None, room_id}]
        return records[-max(1, min(limit, 1000)):]


    async def async_export_diagnostics(self, room_id: str | None = None) -> str:
        """Export configuration, live inputs and the diagnostic journal."""
        import json
        from pathlib import Path

        now = dt_util.now()
        room_token = room_id or "house"
        filename = (
            f"smart_shading_{room_token}_{now.strftime('%Y%m%d_%H%M%S')}.json"
        )
        target_dir = Path(self.hass.config.path("www")) / "smart_shading_logs"
        await self.hass.async_add_executor_job(
            lambda: target_dir.mkdir(parents=True, exist_ok=True)
        )
        path = target_dir / filename

        selected_rooms = {
            key: runtime
            for key, runtime in self.rooms.items()
            if room_id is None or key == room_id
        }
        selected_sector_ids = {
            sector["id"]
            for room in self.config.get(CONF_ROOMS, [])
            if room_id is None or room.get("id") == room_id
            for sector in room.get("sectors", [])
        }
        selected_cover_ids = {
            self._cover_id(cover)
            for room, _sector, _layer, cover in self._iter_covers()
            if room_id is None or room.get("id") == room_id
        }
        selected_cover_entities = {
            str(cover.get("entity") or "")
            for room, _sector, _layer, cover in self._iter_covers()
            if (room_id is None or room.get("id") == room_id)
            and cover.get("entity")
        }

        input_states = {}
        for entity_id in sorted(self.referenced_entities()):
            state = self.hass.states.get(entity_id)
            input_states[entity_id] = {
                "state": state.state if state else None,
                "unit": state.attributes.get("unit_of_measurement") if state else None,
                "device_class": state.attributes.get("device_class") if state else None,
                "current_position": state.attributes.get("current_position") if state else None,
                "current_tilt_position": state.attributes.get("current_tilt_position") if state else None,
            }

        shared_manual_entities: dict[str, list[str]] = {}
        for room, _sector, _layer, cover in self._iter_covers():
            if room_id is not None and room.get("id") != room_id:
                continue
            manual_entity = str(cover.get("lock") or "")
            if manual_entity:
                shared_manual_entities.setdefault(manual_entity, []).append(
                    str(cover.get("entity") or "")
                )
        shared_manual_entities = {
            entity_id: covers
            for entity_id, covers in shared_manual_entities.items()
            if len(covers) > 1
        }
        registry = er.async_get(self.hass)

        payload = {
            "integration_version": VERSION,
            "schema_version": 3,
            "entry_id": self.entry.entry_id,
            "room_id": room_id,
            "exported_at": now.isoformat(),
            "shared_manual_override_groups": shared_manual_entities,
            "evaluation_interval_seconds": self.config.get(
                CONF_EVALUATION_INTERVAL, DEFAULT_EVALUATION_INTERVAL
            ),
            "configuration": self.config,
            "input_states": input_states,
            "rooms": {
                key: {
                    "name": runtime.name,
                    "mode": runtime.mode,
                    "reason": runtime.reason,
                    "active_sectors": runtime.active_sectors,
                    "targets": runtime.targets,
                    "last_evaluation": _serialize_datetime(runtime.last_evaluation),
                    "last_command": _serialize_datetime(runtime.last_command),
                    "sent_commands": runtime.sent_commands,
                    "suppressed_commands": runtime.suppressed_commands,
                    "pause_mode": runtime.pause_mode,
                    "pause_until": _serialize_datetime(runtime.pause_until),
                    "manual_master_active": not runtime.enabled,
                    "manual_override_entity": registry.async_get_entity_id(
                        "switch", DOMAIN, f"{self.entry.entry_id}_{key}_enable"
                    ),
                    "external_movement_detection_configured": bool(
                        self.room_config(key).get(
                            CONF_EXTERNAL_MOVEMENT_DETECTION, False
                        )
                    ),
                    "external_movement_detection_effective": bool(
                        self.advanced_mode
                        and self.room_config(key).get(
                            CONF_EXTERNAL_MOVEMENT_DETECTION, False
                        )
                    ),
                    "schedule_active": runtime.schedule_active,
                    "schedule_reason": runtime.schedule_reason,
                    "night_active": runtime.night_active,
                    "night_blocked": runtime.night_blocked,
                    "night_reason": runtime.night_reason,
                    "night_source_state": runtime.night_source_state,
                    "night_next_transition": _serialize_datetime(
                        runtime.night_next_transition
                    ),
                    "night_morning_hold_until": _serialize_datetime(
                        runtime.night_morning_hold_until
                    ),
                    "night_morning_handover_pending": (
                        runtime.night_morning_handover_pending
                    ),
                    "easy_confirmation_state": runtime.easy_confirmation_state,
                    "easy_source_summary": runtime.easy_source_summary,
                    "outdoor_temperature_condition": {
                        "enabled": runtime.outdoor_temperature_condition_enabled,
                        "source_entity": runtime.outdoor_temperature_source,
                        "value": runtime.outdoor_temperature_value,
                        "minimum": runtime.outdoor_temperature_minimum,
                        "passed": runtime.outdoor_temperature_passed,
                    },
                }
                for key, runtime in selected_rooms.items()
            },
            "sun_presence": {
                key: {
                    "is_on": runtime.is_on,
                    "current_lux": runtime.current_lux,
                    "settings": self._sun_settings(key),
                    "pending_target": runtime.pending_target,
                    "pending_since": _serialize_datetime(runtime.pending_since),
                    "pending_until": _serialize_datetime(runtime.pending_until),
                    "last_transition": _serialize_datetime(runtime.last_transition),
                    "reason": runtime.reason,
                    "status": runtime.status,
                    "geometry_active": runtime.geometry_active,
                    "confirmation_source": runtime.confirmation_source,
                    "confirmation_entity": runtime.confirmation_entity,
                    "confirmation_state": runtime.confirmation_state,
                    "effective_active": runtime.effective_active,
                }
                for key, runtime in self.sun_runtime.items()
                if key in selected_sector_ids
            },
            "cover_pauses": {
                key: {
                    "entity_id": pause.entity_id,
                    "room_id": pause.room_id,
                    "active": pause.active,
                    "until": _serialize_datetime(pause.until),
                    "reason": pause.reason,
                    "lock_owned": pause.lock_owned,
                    "pause_mode": pause.pause_mode,
                    "waiting_for_night": pause.waiting_for_night,
                }
                for key, pause in self.cover_pauses.items()
                if key in selected_cover_ids
            },
            "cover_motion_detection": {
                entity_id: {
                    "phase": observation.phase,
                    "baseline_position": observation.baseline_position,
                    "baseline_tilt": observation.baseline_tilt,
                    "last_position": observation.last_position,
                    "last_tilt": observation.last_tilt,
                    "last_state_informational_only": observation.last_state,
                    "candidate_axis": observation.candidate_axis,
                    "candidate_direction": observation.candidate_direction,
                    "candidate_started_at": _serialize_datetime(
                        observation.candidate_started_at
                    ),
                    "candidate_last_changed_at": _serialize_datetime(
                        observation.candidate_last_changed_at
                    ),
                    "candidate_start_position": observation.candidate_start_position,
                    "candidate_start_tilt": observation.candidate_start_tilt,
                    "candidate_latest_position": observation.candidate_latest_position,
                    "candidate_latest_tilt": observation.candidate_latest_tilt,
                    "candidate_changed_updates": observation.candidate_updates,
                    "candidate_stable_updates": observation.candidate_stable_updates,
                    "stability_timer_pending": entity_id
                    in getattr(self, "_external_candidate_timer_unsubs", {}),
                    "last_decision_reason": observation.last_decision_reason,
                }
                for entity_id, observation in getattr(
                    self, "cover_motion", {}
                ).items()
                if entity_id in selected_cover_entities
            },
            "window_automation_contexts": {
                entity_id: {
                    "window_entity_id": context.window_entity_id,
                    "phase": context.phase,
                    "started_at": _serialize_datetime(context.started_at),
                    "expires_at": _serialize_datetime(context.expires_at),
                    "last_feedback_at": _serialize_datetime(
                        context.last_feedback_at
                    ),
                }
                for entity_id, context in getattr(
                    self, "window_automation_contexts", {}
                ).items()
                if entity_id in selected_cover_entities
            },
            "events": self.recent_diagnostics(room_id, 500),
        }

        def _write() -> None:
            path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )

        await self.hass.async_add_executor_job(_write)
        return f"/local/smart_shading_logs/{filename}"

    def room_config(self, room_id: str) -> dict[str, Any]:
        return next(
            room
            for room in self.config.get(CONF_ROOMS, [])
            if room["id"] == room_id
        )

    def sector_config(self, sector_id: str) -> dict[str, Any]:
        for room in self.config.get(CONF_ROOMS, []):
            for sector in room.get("sectors", []):
                if sector["id"] == sector_id:
                    return sector
        raise KeyError(sector_id)

    def layer_config(self, layer_id: str) -> dict[str, Any]:
        for room in self.config.get(CONF_ROOMS, []):
            for sector in room.get("sectors", []):
                for layer in sector.get("layers", []):
                    if layer["id"] == layer_id:
                        return layer
        raise KeyError(layer_id)

    def room_value(self, room_id: str, key: str, default: Any = None) -> Any:
        room = self.room_config(room_id)
        return self.store.get_override(
            "room", room_id, key, room.get(key, default)
        )

    def sector_value(self, sector_id: str, key: str, default: Any = None) -> Any:
        sector = self.sector_config(sector_id)
        return self.store.get_override(
            "sector", sector_id, key, sector.get(key, default)
        )

    def layer_value(self, layer_id: str, key: str, default: Any = None) -> Any:
        layer = self.layer_config(layer_id)
        return self.store.get_override(
            "layer", layer_id, key, layer.get(key, default)
        )

    async def async_set_room_value(
        self, room_id: str, key: str, value: Any
    ) -> None:
        await self.store.async_set_override("room", room_id, key, value)
        await self.async_evaluate_all(f"room_setting:{key}")

    async def async_set_sector_value(
        self, sector_id: str, key: str, value: Any, *, custom: bool = True
    ) -> None:
        values = {key: value}
        if custom and key in {
            "sun_on_lux",
            "sun_off_lux",
            "sun_on_delay",
            "sun_off_delay",
        }:
            values["sun_preset"] = PRESET_CUSTOM
        await self.store.async_set_many("sector", sector_id, values)
        await self.async_evaluate_all(f"sector_setting:{key}")

    async def async_set_sun_preset(self, sector_id: str, preset: str) -> None:
        values: dict[str, Any] = {"sun_preset": preset}
        if preset in SUN_PRESETS:
            values.update(SUN_PRESETS[preset])
        await self.store.async_set_many("sector", sector_id, values)
        await self.async_evaluate_all("sun_preset")

    async def async_set_layer_value(
        self, layer_id: str, key: str, value: Any
    ) -> None:
        await self.store.async_set_override("layer", layer_id, key, value)
        await self.async_evaluate_all(f"layer_setting:{key}")

    async def async_set_room_enabled(self, room_id: str, enabled: bool) -> None:
        runtime = self.rooms[room_id]
        runtime.enabled = enabled
        if not enabled:
            runtime.mode = MODE_DISABLED
            runtime.reason = "Manual master override active"
            runtime.active_sectors = []
            runtime.targets = []
            self._mark_room_sectors(
                self.room_config(room_id),
                status="disabled",
                reason=runtime.reason,
                mode=MODE_DISABLED,
                active=False,
            )
            await self._save_room_runtime(runtime)
            self._notify()
            return
        await self._save_room_runtime(runtime)
        await self.async_evaluate_all("manual_master_released")

    def _pause_until_from_sun(self, room_id: str, mode: str, now: datetime) -> datetime | None:
        room = self.room_config(room_id)
        sun = self.hass.states.get(self.config.get(CONF_SUN_ENTITY, "sun.sun"))
        attribute = "next_rising" if mode == PAUSE_NEXT_SUNRISE else "next_setting"
        value = sun.attributes.get(attribute) if sun else None
        candidate = dt_util.parse_datetime(value) if value else None
        if candidate is None:
            return None
        candidate = dt_util.as_local(candidate)
        if candidate <= now:
            # A stale sun attribute should never shorten the requested pause.
            candidate += timedelta(days=1)
        return candidate + timedelta(minutes=float(self.room_value(room_id, "pause_sun_offset_minutes", room.get("pause_sun_offset_minutes", 0))))

    def _configured_pause_duration(
        self, room_id: str, room: dict[str, Any] | None = None
    ) -> float:
        """Return the one effective, bounded timed-pause duration."""
        room = room or self.room_config(room_id)
        try:
            value = float(
                self.room_value(
                    room_id,
                    "pause_duration_hours",
                    room.get("pause_duration_hours", 2.0),
                )
            )
        except (TypeError, ValueError):
            value = 2.0
        return max(
            PAUSE_DURATION_MIN_HOURS,
            min(PAUSE_DURATION_MAX_HOURS, value),
        )

    def _night_pause_release_is_valid(
        self, room: dict[str, Any], now: datetime
    ) -> bool:
        """Return whether Night can still release a persisted pause."""
        if not self.advanced_mode or not room.get("night_enabled", False):
            return False
        if str(room.get("night_source", "entity")) not in {"entity", "sun"}:
            return False
        _active, blocked, _reason, _state, _next = self._night_status(room, now)
        return not blocked

    async def _async_reconcile_night_end_pauses(self) -> None:
        """Give orphaned Night-end pauses a persistent sunrise release."""
        now = dt_util.now()
        for room in self.config.get(CONF_ROOMS, []):
            room_id = str(room["id"])
            if self._night_pause_release_is_valid(room, now):
                continue

            due: datetime | None = None

            def sunrise_due() -> datetime:
                nonlocal due
                if due is None:
                    due = self._pause_until_from_sun(
                        room_id, PAUSE_NEXT_SUNRISE, now
                    ) or (now + timedelta(hours=12))
                return due

            room_fell_back = False
            runtime = self.rooms.get(room_id)
            if runtime is not None and runtime.pause_mode == PAUSE_NEXT_NIGHT_END:
                runtime.pause_mode = PAUSE_NEXT_SUNRISE
                runtime.pause_until = sunrise_due()
                runtime.pause_waiting_for_night = False
                self._schedule_room_pause_timer(room_id, runtime.pause_until)
                await self._save_room_runtime(runtime)
                room_fell_back = True

            cover_fallbacks = 0
            for pause in self.cover_pauses.values():
                if (
                    str(pause.room_id) != room_id
                    or not pause.active
                    or pause.pause_mode != PAUSE_NEXT_NIGHT_END
                ):
                    continue
                pause.pause_mode = PAUSE_NEXT_SUNRISE
                pause.until = sunrise_due()
                pause.waiting_for_night = False
                self._schedule_cover_pause_timer(pause.cover_id, pause.until)
                await self._save_cover_pause(pause)
                cover_fallbacks += 1

            if room_fell_back or cover_fallbacks:
                self._diag(
                    "night_pause_reload_fell_back_to_sunrise",
                    room_id=room_id,
                    room_pause=room_fell_back,
                    cover_pauses=cover_fallbacks,
                    until=sunrise_due().isoformat(),
                )

    def _cancel_room_pause_timer(self, room_id: str) -> None:
        unsub = self._room_pause_timer_unsubs.pop(room_id, None)
        if unsub:
            unsub()

    def _schedule_room_pause_timer(self, room_id: str, due: datetime) -> None:
        self._cancel_room_pause_timer(room_id)
        seconds = max(0.1, (due - dt_util.now()).total_seconds())

        async def _expire(_now) -> None:
            self._room_pause_timer_unsubs.pop(room_id, None)
            runtime = self.rooms.get(room_id)
            if runtime is None or runtime.pause_mode == PAUSE_MANUAL:
                return
            runtime.pause_mode = PAUSE_AUTO
            runtime.pause_until = None
            await self._save_room_runtime(runtime)
            self._diag("room_pause_ended", room_id=room_id, reason="timer_expired")
            await self._async_room_pause_state_changed(room_id, False)
            await self.async_evaluate_all(f"room_pause_ended:{room_id}")

        self._room_pause_timer_unsubs[room_id] = async_call_later(
            self.hass, seconds, _expire
        )

    def _schedule_night_timer(
        self, room_id: str, due: datetime | None
    ) -> None:
        previous = self._night_timer_unsubs.pop(room_id, None)
        if previous:
            previous()
        if due is None:
            return
        seconds = (due - dt_util.now()).total_seconds()
        if seconds <= 0:
            return

        async def _transition(_now) -> None:
            self._night_timer_unsubs.pop(room_id, None)
            await self.async_evaluate_all(f"night_transition:{room_id}")

        self._night_timer_unsubs[room_id] = async_call_later(
            self.hass, max(0.1, seconds), _transition
        )

    async def async_set_pause_mode(self, room_id: str, mode: str) -> None:
        runtime = self.rooms[room_id]
        now = dt_util.now()
        room = self.room_config(room_id)
        if (
            mode == PAUSE_NEXT_NIGHT_END
            and not self._night_pause_release_is_valid(room, now)
        ):
            self._diag(
                "night_pause_fell_back_to_sunrise",
                room_id=room_id,
            )
            mode = PAUSE_NEXT_SUNRISE
        runtime.pause_mode = mode
        self._cancel_room_pause_timer(room_id)
        if mode in {PAUSE_NEXT_SUNRISE, PAUSE_NEXT_SUNSET}:
            runtime.pause_until = self._pause_until_from_sun(room_id, mode, now)
            if runtime.pause_until is None:
                runtime.pause_until = now + timedelta(hours=12)
            self._schedule_room_pause_timer(room_id, runtime.pause_until)
        elif mode == PAUSE_TIMED:
            duration = self._configured_pause_duration(room_id, room)
            runtime.pause_hours = duration
            runtime.pause_until = now + timedelta(hours=duration)
            self._schedule_room_pause_timer(room_id, runtime.pause_until)
        elif mode == PAUSE_NEXT_NIGHT_END:
            runtime.pause_until = None
            runtime.pause_waiting_for_night = not runtime.night_active
        elif mode in {PAUSE_AUTO, PAUSE_MANUAL}:
            runtime.pause_until = None
            runtime.pause_waiting_for_night = False
        if mode != PAUSE_AUTO:
            runtime.mode = MODE_PAUSED
            runtime.reason = "Automatic shading is paused"
            runtime.active_sectors = []
            runtime.targets = []
            self._mark_room_sectors(
                room,
                status="paused",
                reason=runtime.reason,
                mode=MODE_PAUSED,
                active=False,
            )
            await self._save_room_runtime(runtime)
            await self._async_room_pause_state_changed(room_id, True)
            self._notify()
        else:
            await self._save_room_runtime(runtime)
            await self._async_room_pause_state_changed(room_id, False)
            await self.async_evaluate_all("pause_released")

    async def _async_room_pause_state_changed(
        self, room_id: str, paused: bool, release_mode: str | None = None
    ) -> None:
        """Allow runtime controllers to mirror room pauses to manual entities."""

    async def async_pause_default(self, room_id: str) -> None:
        room = self.room_config(room_id)
        mode = str(room.get("default_pause_mode", PAUSE_NEXT_SUNRISE))
        await self.async_set_pause_mode(room_id, mode)

    async def async_set_pause_hours(self, room_id: str, hours: float) -> None:
        runtime = self.rooms[room_id]
        hours = max(
            PAUSE_DURATION_MIN_HOURS,
            min(PAUSE_DURATION_MAX_HOURS, float(hours)),
        )
        runtime.pause_hours = hours
        await self.store.async_set_override(
            "room", room_id, "pause_duration_hours", hours
        )
        if runtime.pause_mode == PAUSE_TIMED:
            runtime.pause_until = dt_util.now() + timedelta(hours=hours)
            self._schedule_room_pause_timer(room_id, runtime.pause_until)
        await self._save_room_runtime(runtime)
        self._notify()

    async def async_resume_room(self, room_id: str) -> None:
        self._cancel_room_pause_timer(room_id)
        runtime = self.rooms[room_id]
        runtime.pause_mode = PAUSE_AUTO
        runtime.pause_until = None
        runtime.pause_waiting_for_night = False
        await self._save_room_runtime(runtime)
        await self._async_room_pause_state_changed(room_id, False)
        await self.async_evaluate_all("resume")

    async def async_reset_finished(self, room_id: str) -> None:
        runtime = self.rooms[room_id]
        runtime.finished_today = False
        await self._save_room_runtime(runtime)
        await self.async_evaluate_all("reset_finished")

    async def async_reset_sun_presence(self, sector_id: str) -> None:
        runtime = self.sun_runtime[sector_id]
        runtime.is_on = False
        runtime.pending_target = None
        runtime.pending_since = None
        runtime.pending_until = None
        runtime.last_transition = dt_util.now()
        runtime.reason = "Reset by user"
        self._cancel_sun_timer(sector_id)
        await self._save_sun_runtime(runtime)
        await self.async_evaluate_all("reset_sun_presence")

    async def async_evaluate_all(self, trigger: str) -> None:
        async with self._evaluate_lock:
            self._current_trigger = trigger
            now = dt_util.now()
            self._diag("evaluation_started", full=True, at=now.isoformat())
            await self._daily_reset(now)
            await self._update_all_sun_presence(now)
            await self._async_enforce_all_maximum_openings()
            for room in self.config.get(CONF_ROOMS, []):
                try:
                    await self._evaluate_room(room, now)
                except Exception:
                    _LOGGER.exception(
                        "Evaluation failed for Smart Shading room %s",
                        room.get("name"),
                    )
            self._notify()

    async def _daily_reset(self, now: datetime) -> None:
        key = now.date().isoformat()
        if self._day_key == key:
            return
        self._day_key = key
        for runtime in self.rooms.values():
            runtime.finished_today = False
            if (
                runtime.pause_mode not in {PAUSE_AUTO, PAUSE_MANUAL}
                and runtime.pause_until
                and runtime.pause_until <= now
            ):
                runtime.pause_mode = PAUSE_AUTO
                runtime.pause_until = None
            await self._save_room_runtime(runtime)
        await self.store.async_set_day_key(key)

    async def _update_all_sun_presence(self, now: datetime) -> None:
        for room in self.config.get(CONF_ROOMS, []):
            for sector in room.get("sectors", []):
                if sector.get("lux_sensor"):
                    await self._update_sun_presence(sector, now)

    def _sun_settings(self, sector_id: str) -> dict[str, float]:
        """Return effective Sun Presence settings. Presets are authoritative."""
        preset = str(self.sector_value(sector_id, "sun_preset", PRESET_MEDIUM))
        if preset in SUN_PRESETS:
            return {key: float(value) for key, value in SUN_PRESETS[preset].items()}
        return {
            "sun_on_lux": float(self.sector_value(sector_id, "sun_on_lux", 18000)),
            "sun_off_lux": float(self.sector_value(sector_id, "sun_off_lux", 9000)),
            "sun_on_delay": float(self.sector_value(sector_id, "sun_on_delay", 3)),
            "sun_off_delay": float(self.sector_value(sector_id, "sun_off_delay", 12)),
        }

    async def _update_sun_presence(
        self, sector: dict[str, Any], now: datetime
    ) -> None:
        sector_id = sector["id"]
        runtime = self.sun_runtime[sector_id]
        lux_entity = sector.get("lux_sensor", "")
        lux_state = self.hass.states.get(lux_entity) if lux_entity else None
        lux = _state_number(self.hass, lux_entity)
        runtime.current_lux = lux
        settings = self._sun_settings(sector_id)
        configured_on_lux = settings["sun_on_lux"]
        configured_off_lux = settings["sun_off_lux"]
        effective_on_lux = max(configured_on_lux, configured_off_lux)
        effective_off_lux = min(configured_on_lux, configured_off_lux)
        step = sun_presence_step(
            now=now,
            lux=lux,
            is_on=runtime.is_on,
            pending_target=runtime.pending_target,
            pending_since=runtime.pending_since,
            on_lux=effective_on_lux,
            off_lux=effective_off_lux,
            on_delay_minutes=float(
                settings["sun_on_delay"]
            ),
            off_delay_minutes=float(
                settings["sun_off_delay"]
            ),
        )
        runtime.is_on = step.is_on
        runtime.pending_target = step.pending_target
        runtime.pending_since = step.pending_since
        runtime.pending_until = step.pending_until
        runtime.reason = step.reason
        if step.transitioned:
            runtime.last_transition = now
            self._diag(
                "sun_presence_changed",
                sector_id=sector_id,
                sector=sector.get("name", ""),
                state="on" if runtime.is_on else "off",
                lux=lux,
                on_lux=effective_on_lux,
                off_lux=effective_off_lux,
                reason=runtime.reason,
                raw_state=getattr(lux_state, "state", None),
                unit=(lux_state.attributes.get("unit_of_measurement") if lux_state else None),
            )
        elif runtime.pending_target is not None:
            self._diag(
                "sun_presence_delay",
                full=True,
                sector_id=sector_id,
                sector=sector.get("name", ""),
                target="on" if runtime.pending_target else "off",
                lux=lux,
                pending_until=runtime.pending_until.isoformat() if runtime.pending_until else None,
            )
        await self._save_sun_runtime(runtime)

        if runtime.pending_until:
            self._schedule_sun_timer(sector_id, runtime.pending_until)
        else:
            self._cancel_sun_timer(sector_id)

    def _schedule_sun_timer(self, sector_id: str, due: datetime) -> None:
        self._cancel_sun_timer(sector_id)
        seconds = max(0.0, (due - dt_util.now()).total_seconds()) + 0.1

        async def timer_callback(_now) -> None:
            self._sun_timer_unsubs.pop(sector_id, None)
            try:
                sector = self.sector_config(sector_id)
            except KeyError:
                return
            await self._update_sun_presence(sector, dt_util.now())
            if self.advanced_mode:
                # Preserve the existing Advanced Mode interval behavior.
                self._notify()
            else:
                # Completing a delayed Lux transition changes the effective
                # Easy decision. Reevaluate now so covers move with the UI.
                await self.async_evaluate_all(f"sun_presence_timer:{sector_id}")

        self._sun_timer_unsubs[sector_id] = async_call_later(
            self.hass, seconds, timer_callback
        )

    def _cancel_sun_timer(self, sector_id: str) -> None:
        unsub = self._sun_timer_unsubs.pop(sector_id, None)
        if unsub:
            unsub()

    def _advanced_sector_confirmation(
        self, sector: dict[str, Any]
    ) -> tuple[bool, str, str | None, bool | None]:
        """Resolve exactly the sun source selected for this sector."""
        source = sun_source_for_sector(sector, advanced=True)
        if source == "external":
            entity_id = str(
                sector.get(CONF_SUN_PRESENCE_ENTITY, "") or ""
            )
            state = self.hass.states.get(entity_id) if entity_id else None
            value = str(getattr(state, "state", "") or "").lower()
            if value == STATE_ON:
                return True, "binary", entity_id, True
            if value == STATE_OFF:
                return False, "binary", entity_id, False
            return False, "binary", entity_id or None, None

        if source == "lux":
            entity_id = str(sector.get("lux_sensor", "") or "")
            runtime = self.sun_runtime[sector["id"]]
            active = bool(runtime.is_on) if runtime.current_lux is not None else False
            return active, "lux", entity_id or None, (
                active if runtime.current_lux is not None else None
            )
        return True, "geometry", None, None

    def _easy_sector_confirmation(
        self, sector: dict[str, Any]
    ) -> tuple[bool | None, str, str | None]:
        """Resolve exactly the Easy Mode source selected for this sector."""
        source = sun_source_for_sector(sector, advanced=False)
        if source == "external":
            binary_entity = str(
                sector.get(CONF_SUN_PRESENCE_ENTITY, "") or ""
            )
            state = self.hass.states.get(binary_entity)
            value = str(getattr(state, "state", "") or "").lower()
            if value == STATE_ON:
                return True, "binary", binary_entity
            if value == STATE_OFF:
                return False, "binary", binary_entity
            return False, "binary", binary_entity or None

        if source == "lux":
            lux_entity = str(sector.get("lux_sensor", "") or "")
            runtime = self.sun_runtime[sector["id"]]
            if lux_entity and runtime.current_lux is not None:
                return runtime.is_on, "lux", lux_entity
            return False, "lux", lux_entity or None
        return None, "geometry", None

    def _outdoor_temperature_condition(
        self, room: dict[str, Any]
    ) -> tuple[bool, str | None, float | None, float | None]:
        """Require the configured outdoor sensor to reach its minimum."""
        source_entity = str(room.get("outdoor_temperature", "") or "").strip()
        if not source_entity:
            return True, None, None, None

        threshold = parse_numeric_value(
            self.room_value(
                room["id"], "outdoor_minimum", room.get("outdoor_minimum", 18.0)
            )
        )
        if threshold is None:
            threshold = 18.0
        value = _temperature_state_celsius(self.hass, source_entity)
        if value is None:
            return False, source_entity, None, threshold
        return value >= threshold, source_entity, value, threshold

    def _weather_pass(self, room: dict[str, Any]) -> tuple[bool, list[str]]:
        tests: list[tuple[str, bool]] = []
        irradiance = room.get("irradiance_sensor", "")
        if irradiance:
            irradiance_value = _state_number(self.hass, irradiance)
            tests.append(
                (
                    "irradiance",
                    irradiance_value is not None
                    and irradiance_value
                    >= float(
                        self.room_value(
                            room["id"], "irradiance_minimum", 150.0
                        )
                    ),
                )
            )
        cloud = room.get("cloud_cover_sensor", "")
        if cloud:
            cloud_value = _state_number(self.hass, cloud)
            tests.append(
                (
                    "cloud cover",
                    cloud_value is not None
                    and cloud_value
                    <= float(
                        self.room_value(
                            room["id"], "cloud_cover_maximum", 85.0
                        )
                    ),
                )
            )
        permission = room.get("weather_permission", "")
        if permission:
            tests.append(("weather permission", _is_on(self.hass, permission)))
        if not tests:
            return True, []
        logic = room.get("weather_logic", "all")
        passed = (
            any(value for _, value in tests)
            if logic == "any"
            else all(value for _, value in tests)
        )
        return passed, [name for name, value in tests if not value]

    def _pause_active(self, runtime: RoomRuntime, now: datetime) -> bool:
        if runtime.pause_mode in {PAUSE_MANUAL, PAUSE_NEXT_NIGHT_END}:
            return True
        if runtime.pause_mode in {PAUSE_NEXT_SUNRISE, PAUSE_NEXT_SUNSET, PAUSE_TIMED}:
            if runtime.pause_until and runtime.pause_until > now:
                return True
            runtime.pause_mode = PAUSE_AUTO
            runtime.pause_until = None
        return False

    @staticmethod
    def _time_inside(now: datetime, start_value: str, end_value: str) -> bool:
        def parse(value: str, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
            try:
                parts = [int(part) for part in str(value).split(":")]
                return (parts + [0, 0, 0])[:3]
            except (TypeError, ValueError):
                return fallback

        sh, sm, ss = parse(start_value, (0, 0, 0))
        eh, em, es = parse(end_value, (23, 59, 59))
        current = now.hour * 3600 + now.minute * 60 + now.second
        start = sh * 3600 + sm * 60 + ss
        end = eh * 3600 + em * 60 + es
        if start <= end:
            return start <= current <= end
        return current >= start or current <= end

    @staticmethod
    def _schedule_active_at(room: dict[str, Any], when: datetime) -> bool:
        if not bool(room.get("schedule_enabled", False)):
            return True
        months = {int(value) for value in room.get("active_months", range(1, 13))}
        weekdays = {int(value) for value in room.get("active_weekdays", range(7))}
        if when.month not in months or when.weekday() not in weekdays:
            return False
        window = room.get("day_window", "sector_sun")
        if window in {DAY_WINDOW_ALL_DAY, "sector_sun"}:
            return True
        if window == DAY_WINDOW_FIXED:
            return SmartShadingEngine._time_inside(
                when,
                room.get("start_time", "00:00:00"),
                room.get("end_time", "23:59:59"),
            )
        return True

    @staticmethod
    def _clock_parts(value: str, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
        try:
            parts = [int(part) for part in str(value).split(":")]
            parts = (parts + [0, 0, 0])[:3]
            hour, minute, second = parts
            if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
                raise ValueError
            return hour, minute, second
        except (TypeError, ValueError):
            return fallback

    def _next_schedule_change(
        self, room: dict[str, Any], now: datetime, current_active: bool
    ) -> datetime | None:
        """Find the next schedule boundary without creating another automation."""
        candidates: set[datetime] = set()
        fixed = room.get("day_window", "sector_sun") == DAY_WINDOW_FIXED
        start_parts = self._clock_parts(room.get("start_time", "00:00:00"), (0, 0, 0))
        end_parts = self._clock_parts(room.get("end_time", "23:59:59"), (23, 59, 59))

        # One full year plus margin covers seasonal and weekday profiles.
        for offset in range(0, 380):
            day = now + timedelta(days=offset)
            midnight = day.replace(hour=0, minute=0, second=0, microsecond=0)
            candidates.add(midnight)
            if fixed:
                candidates.add(midnight.replace(
                    hour=start_parts[0], minute=start_parts[1], second=start_parts[2]
                ))
                # The configured end time is inclusive in _time_inside, so the
                # state changes one second afterwards.
                end = midnight.replace(
                    hour=end_parts[0], minute=end_parts[1], second=end_parts[2]
                ) + timedelta(seconds=1)
                candidates.add(end)

        for candidate in sorted(value for value in candidates if value > now):
            if self._schedule_active_at(room, candidate) != current_active:
                return candidate
        return None

    def _schedule_status(
        self, room: dict[str, Any], now: datetime
    ) -> tuple[bool, str, datetime | None]:
        if not bool(room.get("schedule_enabled", False)):
            return True, "Schedule not enabled", None
        months = {int(value) for value in room.get("active_months", range(1, 13))}
        weekdays = {int(value) for value in room.get("active_weekdays", range(7))}
        active = self._schedule_active_at(room, now)
        if now.month not in months:
            reason = "Month outside shading season"
        elif now.weekday() not in weekdays:
            reason = "Weekday outside shading schedule"
        elif room.get("day_window", "sector_sun") == DAY_WINDOW_FIXED:
            reason = "Inside fixed shading time" if active else "Outside fixed shading time"
        else:
            reason = "Schedule permits normal shading"
        return active, reason, self._next_schedule_change(room, now, active)

    def _night_status(
        self, room: dict[str, Any], now: datetime
    ) -> tuple[bool, bool, str, str | None, datetime | None]:
        """Return active, blocked, reason, source state and next transition."""
        if not self.config.get(CONF_ADVANCED_MODE, False):
            return False, False, "Night function is not available in this setup", None, None
        if not room.get("night_enabled", False):
            return False, False, "Night Mode disabled", None, None

        source = str(room.get("night_source", "entity"))
        if source == "entity":
            entity_id = str(room.get("night_entity") or "")
            state = self.hass.states.get(entity_id) if entity_id else None
            source_state = state.state if state else None
            if state is None or source_state in {
                "unknown", "unavailable", "none", "",
            }:
                return (
                    False,
                    True,
                    "Night source is unknown or unavailable; positions held",
                    source_state,
                    None,
                )
            next_value = state.attributes.get("next_event")
            next_transition = _parse_datetime(next_value)
            if next_transition is not None:
                next_transition = dt_util.as_local(next_transition)
            return (
                source_state == STATE_ON,
                False,
                "Night source is on" if source_state == STATE_ON else "Night source is off",
                source_state,
                next_transition,
            )

        sun = self.hass.states.get(self.config.get(CONF_SUN_ENTITY, "sun.sun"))
        if sun is None or sun.state in {"unknown", "unavailable", "none", ""}:
            return False, True, "Sun source unavailable; positions held", None, None
        rising = _parse_datetime(sun.attributes.get("next_rising"))
        setting = _parse_datetime(sun.attributes.get("next_setting"))
        if rising is None or setting is None:
            return False, True, "Sun transitions unavailable; positions held", sun.state, None
        rising = dt_util.as_local(rising)
        setting = dt_util.as_local(setting)
        start_offset = timedelta(
            minutes=float(room.get("night_start_offset_minutes", 0))
        )
        end_offset = timedelta(
            minutes=float(room.get("night_end_offset_minutes", 0))
        )
        events: list[tuple[datetime, bool]] = []
        for delta_days in (-1, 0, 1):
            events.append((setting + timedelta(days=delta_days) + start_offset, True))
            events.append((rising + timedelta(days=delta_days) + end_offset, False))
        events.sort(key=lambda item: item[0])
        previous = [item for item in events if item[0] <= now]
        future = [item for item in events if item[0] > now]
        active = previous[-1][1] if previous else sun.state == "below_horizon"
        next_transition = future[0][0] if future else None
        return (
            active,
            False,
            "Inside configured sun Night window" if active else "Outside configured sun Night window",
            sun.state,
            next_transition,
        )

    async def _async_arm_night_end_pauses(self, room_id: str) -> None:
        runtime = self.rooms[room_id]
        if (
            runtime.pause_mode == PAUSE_NEXT_NIGHT_END
            and runtime.pause_waiting_for_night
        ):
            runtime.pause_waiting_for_night = False
            await self._save_room_runtime(runtime)
        for pause in self.cover_pauses.values():
            if (
                str(pause.room_id) == str(room_id)
                and pause.active
                and pause.pause_mode == PAUSE_NEXT_NIGHT_END
                and pause.waiting_for_night
            ):
                pause.waiting_for_night = False
                await self._save_cover_pause(pause)

    async def _async_release_night_end_pauses(self, room_id: str) -> None:
        runtime = self.rooms[room_id]
        room_pause_released = bool(
            runtime.pause_mode == PAUSE_NEXT_NIGHT_END
            and not runtime.pause_waiting_for_night
        )
        cover_pause_released = any(
            str(pause.room_id) == str(room_id)
            and pause.active
            and pause.pause_mode == PAUSE_NEXT_NIGHT_END
            and not pause.waiting_for_night
            for pause in self.cover_pauses.values()
        )
        if not room_pause_released and not cover_pause_released:
            return
        await self._async_room_pause_state_changed(
            room_id, False, release_mode=PAUSE_NEXT_NIGHT_END
        )
        if room_pause_released:
            runtime.pause_mode = PAUSE_AUTO
            runtime.pause_until = None
            runtime.pause_waiting_for_night = False
            await self._save_room_runtime(runtime)
        self._diag(
            "night_end_pauses_released",
            room_id=room_id,
            room_pause=room_pause_released,
            cover_pause=cover_pause_released,
        )

    async def _async_update_night_state(
        self, room: dict[str, Any], now: datetime
    ) -> None:
        runtime = self.rooms[room["id"]]
        active, blocked, reason, source_state, next_transition = self._night_status(
            room, now
        )
        runtime.night_blocked = blocked
        runtime.night_reason = reason
        runtime.night_source_state = source_state
        runtime.night_next_transition = next_transition
        if blocked:
            self._schedule_night_timer(room["id"], None)
            return

        previous = runtime.night_active
        runtime.night_active = active
        if not runtime.night_initialized:
            runtime.night_initialized = True
            if active:
                await self._async_arm_night_end_pauses(room["id"])
            else:
                await self._async_release_night_end_pauses(room["id"])
        elif previous != active:
            if active:
                runtime.night_morning_hold_until = None
                runtime.night_morning_handover_pending = False
                await self._async_arm_night_end_pauses(room["id"])
            else:
                minutes = max(
                    0,
                    min(120, int(room.get("night_morning_transition_minutes", 0))),
                )
                runtime.night_morning_hold_until = now + timedelta(minutes=minutes)
                runtime.night_morning_handover_pending = True
                await self._async_release_night_end_pauses(room["id"])
            self._diag(
                "night_state_changed",
                room_id=room["id"],
                active=active,
                reason=reason,
            )

        timer_due = next_transition
        hold_until = runtime.night_morning_hold_until
        if hold_until and hold_until > now and (
            timer_due is None or hold_until < timer_due
        ):
            timer_due = hold_until
        self._schedule_night_timer(room["id"], timer_due)

    async def _evaluate_room(
        self, room: dict[str, Any], now: datetime
    ) -> None:
        runtime = self.rooms[room["id"]]
        runtime.last_evaluation = now
        runtime.active_sectors = []
        runtime.targets = []
        for configured_sector in room.get("sectors", []):
            sector_runtime = self.sun_runtime.get(configured_sector["id"])
            if sector_runtime:
                sector_runtime.geometry_active = False
                sector_runtime.shading_active = False
                sector_runtime.effective_active = False
                sector_runtime.mode = MODE_IDLE
                sector_runtime.status = "not_evaluated"
                sector_runtime.status_reason = "Evaluation started"
        if not self.advanced_mode:
            await self._evaluate_easy_room(room, runtime, now)
            return
        schedule_active, schedule_reason, next_change = self._schedule_status(room, now)
        runtime.schedule_active = schedule_active
        runtime.schedule_reason = schedule_reason
        runtime.next_schedule_change = next_change
        await self._async_update_night_state(room, now)

        # Safety has the highest priority. It remains active even when the
        # customer pauses or disables normal room automation.
        blockers = [
            entity
            for entity in room.get("safety_blockers", [])
            if _is_on(self.hass, entity)
        ]
        if blockers:
            runtime.mode = MODE_SAFETY
            runtime.reason = f"Safety active: {self._entity_display_name(blockers[0], 'Safety sensor')}"
            self._mark_room_sectors(room, status="safety", reason=runtime.reason, mode=MODE_SAFETY, active=True)
            if room.get("safety_behavior", "move_safe") == "move_safe":
                await self._apply_room_mode(room, runtime, MODE_SAFETY, 0.0)
            await self._save_room_runtime(runtime)
            return

        if not runtime.enabled:
            runtime.mode = MODE_DISABLED
            runtime.reason = "Room automation disabled"
            self._mark_room_sectors(room, status="disabled", reason=runtime.reason, mode=MODE_DISABLED, active=False)
            await self._save_room_runtime(runtime)
            return

        pause_active = self._pause_active(runtime, now)
        if pause_active and not room.get("heat_during_pause", False):
            runtime.mode = MODE_PAUSED
            runtime.reason = "Automatic shading is paused"
            self._mark_room_sectors(room, status="paused", reason=runtime.reason, mode=MODE_PAUSED, active=False)
            await self._save_room_runtime(runtime)
            return

        sun_entity = self.config.get(CONF_SUN_ENTITY, "sun.sun")
        sun_state = self.hass.states.get(sun_entity)
        sun_up = bool(sun_state and sun_state.state == "above_horizon")
        azimuth_value = parse_numeric_value(
            sun_state.attributes.get("azimuth") if sun_state else None
        )
        elevation_value = parse_numeric_value(
            sun_state.attributes.get("elevation") if sun_state else None
        )
        azimuth = azimuth_value if azimuth_value is not None else -999.0
        elevation = elevation_value if elevation_value is not None else -999.0

        if pause_active and (runtime.night_active or runtime.night_blocked):
            runtime.mode = MODE_PAUSED
            runtime.reason = "Automatic shading is paused"
            self._mark_room_sectors(
                room,
                status="paused",
                reason=runtime.reason,
                mode=MODE_PAUSED,
                active=False,
            )
            await self._save_room_runtime(runtime)
            return

        if runtime.night_blocked:
            runtime.mode = MODE_IDLE
            runtime.reason = runtime.night_reason
            self._mark_room_sectors(
                room,
                status="night_blocked",
                reason=runtime.reason,
                mode=MODE_IDLE,
                active=False,
            )
            await self._save_room_runtime(runtime)
            return

        if runtime.night_active:
            if runtime.heat_active:
                runtime.heat_active = False
                runtime.finished_today = True
            runtime.mode = MODE_NIGHT
            runtime.reason = runtime.night_reason
            self._mark_room_sectors(
                room,
                status="night",
                reason=runtime.reason,
                mode=MODE_NIGHT,
                active=True,
            )
            await self._apply_room_mode(room, runtime, MODE_NIGHT, elevation)
            await self._save_room_runtime(runtime)
            return

        indoor_entity = room.get("indoor_temperature", "")
        indoor = _temperature_state_celsius(self.hass, indoor_entity)
        indoor_valid = indoor is not None
        outdoor_entity = room.get("outdoor_temperature", "")
        outdoor = _temperature_state_celsius(self.hass, outdoor_entity)
        outdoor_valid = outdoor is not None
        weather_pass, weather_failed = self._weather_pass(room)
        outdoor_ok = not outdoor_entity or (
            outdoor_valid
            and outdoor
            >= float(self.room_value(room["id"], "outdoor_minimum", 18.0))
        )
        heat_requires_sun = bool(room.get("heat_requires_sun", True))
        room_sun_present = self._room_heat_sun_present(room)
        heat_sun_pass = not heat_requires_sun or room_sun_present
        heat_schedule_pass = schedule_active or bool(
            room.get("heat_outside_schedule", True)
        )
        heat_weather_pass = bool(room.get("heat_ignores_weather", True)) or weather_pass
        self._diag(
            "room_inputs",
            full=True,
            room_id=room["id"],
            room=runtime.name,
            indoor_temperature=indoor if indoor_valid else None,
            outdoor_temperature=outdoor if outdoor_valid else None,
            sun_up=sun_up,
            sun_azimuth=azimuth,
            sun_elevation=elevation,
            schedule_active=schedule_active,
            pause_active=pause_active,
            weather_pass=weather_pass,
            weather_failed=list(weather_failed),
            heat_requires_sun=heat_requires_sun,
            heat_sun_present=room_sun_present,
            heat_sun_pass=heat_sun_pass,
            heat_schedule_pass=heat_schedule_pass,
            heat_weather_pass=heat_weather_pass,
            heat_outdoor_pass=outdoor_ok,
        )

        heat_start = float(
            self.room_value(room["id"], "heat_temperature", 27.0)
        )
        if not runtime.heat_active and not runtime.finished_today and (
            indoor_valid
            and indoor >= heat_start
            and heat_sun_pass
            and heat_schedule_pass
            and heat_weather_pass
            and outdoor_ok
        ):
            # Heat protection is latched for the day. Falling temperature or
            # Sun Presence ending must not reopen covers and start another
            # heat cycle later. Only the configured evening release clears it.
            runtime.heat_active = True

        if runtime.heat_active and self._evening_release_reached(room, now):
            runtime.heat_active = False
            runtime.finished_today = True
            evening_window = max(
                0,
                min(120, int(room.get("night_evening_transition_minutes", 0))),
            )
            next_night = runtime.night_next_transition
            hold_for_night = bool(
                evening_window
                and next_night
                and now < next_night <= now + timedelta(minutes=evening_window)
            )
            if hold_for_night:
                runtime.mode = MODE_IDLE
                runtime.reason = "Evening release held for imminent Night Mode"
                self._mark_room_sectors(
                    room,
                    status="night_transition_hold",
                    reason=runtime.reason,
                    mode=MODE_IDLE,
                    active=False,
                )
                await self._save_room_runtime(runtime)
                return
            runtime.mode = MODE_OPEN
            runtime.reason = "Heat protection released for evening"
            await self._apply_room_mode(room, runtime, MODE_OPEN, elevation)
            self._mark_room_sectors(
                room,
                status="outside_sun_sector",
                reason=runtime.reason,
                mode=MODE_OPEN,
                active=False,
            )
            await self._save_room_runtime(runtime)
            return

        evening_window = max(
            0,
            min(120, int(room.get("night_evening_transition_minutes", 0))),
        )
        next_night = runtime.night_next_transition
        if (
            evening_window
            and next_night
            and self._evening_release_reached(room, now)
            and now < next_night <= now + timedelta(minutes=evening_window)
        ):
            runtime.mode = MODE_IDLE
            runtime.reason = "Evening release held for imminent Night Mode"
            self._mark_room_sectors(
                room,
                status="night_transition_hold",
                reason=runtime.reason,
                mode=MODE_IDLE,
                active=False,
            )
            await self._save_room_runtime(runtime)
            return

        active_sectors: list[dict[str, Any]] = []
        for sector in room.get("sectors", []):
            sector_runtime = self.sun_runtime[sector["id"]]
            if not bool(self.sector_value(sector["id"], "enabled", True)):
                sector_runtime.status = "disabled"
                sector_runtime.status_reason = "Sector disabled"
                sector_runtime.mode = MODE_DISABLED
                continue
            geometry = (
                sun_up
                and azimuth_inside(
                    azimuth,
                    float(
                        self.sector_value(
                            sector["id"],
                            "azimuth_start",
                            sector.get("azimuth_start", 0),
                        )
                    ),
                    float(
                        self.sector_value(
                            sector["id"],
                            "azimuth_end",
                            sector.get("azimuth_end", 359),
                        )
                    ),
                )
                and elevation
                >= float(
                    self.sector_value(
                        sector["id"],
                        "elevation_min",
                        sector.get("elevation_min", 0),
                    )
                )
            )
            sector_runtime.geometry_active = geometry
            (
                sun_pass,
                confirmation_source,
                confirmation_entity,
                confirmation_state,
            ) = self._advanced_sector_confirmation(sector)
            sector_runtime.confirmation_source = confirmation_source
            sector_runtime.confirmation_entity = confirmation_entity
            sector_runtime.confirmation_state = confirmation_state
            sector_runtime.effective_active = bool(geometry and sun_pass)
            if not sun_up:
                sector_runtime.status = "sun_below_horizon"
                sector_runtime.status_reason = "Sun below horizon"
            elif not geometry:
                sector_runtime.status = "outside_sun_sector"
                sector_runtime.status_reason = "Sun outside this sector"
            elif confirmation_source != "geometry" and not sun_pass:
                sector_runtime.status = "waiting_for_lux"
                sector_runtime.status_reason = (
                    "External sun confirmation is off"
                    if confirmation_source == "binary"
                    else sector_runtime.reason
                )
            else:
                sector_runtime.status = "sun_detected"
                sector_runtime.status_reason = "Sun detected in sector"
            self._diag(
                "sector_inputs",
                full=True,
                room_id=room["id"],
                sector_id=sector["id"],
                sector=sector.get("name", ""),
                enabled=bool(self.sector_value(sector["id"], "enabled", True)),
                geometry_active=geometry,
                lux=sector_runtime.current_lux,
                sun_presence=sector_runtime.is_on,
                sun_pass=sun_pass,
                status=sector_runtime.status,
            )
            if geometry and sun_pass:
                active_sectors.append(sector)
                runtime.active_sectors.append(sector["name"])

        if runtime.heat_active:
            runtime.night_morning_handover_pending = False
            runtime.night_morning_hold_until = None
            runtime.mode = MODE_HEAT
            runtime.reason = "Heat threshold / hysteresis active"
            self._mark_room_sectors(room, status="heat", reason=runtime.reason, mode=MODE_HEAT, active=True)
            await self._apply_room_mode(room, runtime, MODE_HEAT, elevation)
            await self._save_room_runtime(runtime)
            return

        if pause_active:
            runtime.mode = MODE_PAUSED
            runtime.reason = "Automatic shading is paused; heat protection is not active"
            self._mark_room_sectors(
                room,
                status="paused",
                reason=runtime.reason,
                mode=MODE_PAUSED,
                active=False,
            )
            await self._save_room_runtime(runtime)
            return

        if not schedule_active:
            runtime.night_morning_handover_pending = False
            runtime.night_morning_hold_until = None
            behavior = room.get("outside_schedule_behavior", OUTSIDE_OPEN)
            if behavior == OUTSIDE_OPEN:
                runtime.mode = MODE_OPEN
                runtime.reason = f"{schedule_reason}; covers moved to neutral/open position"
                await self._apply_room_mode(room, runtime, MODE_OPEN, elevation)
            else:
                runtime.mode = MODE_IDLE
                runtime.reason = f"{schedule_reason}; cover positions held"
            self._mark_room_sectors(
                room, status="schedule_blocked", reason=runtime.reason, mode=runtime.mode, active=False
            )
            await self._save_room_runtime(runtime)
            return

        occupied = not room.get("occupancy_sensor") or _is_on(
            self.hass, room.get("occupancy_sensor", "")
        )
        glare = bool(room.get("glare_sensor")) and _is_on(
            self.hass, room.get("glare_sensor", "")
        )
        comfort_temperature = float(
            self.room_value(room["id"], "comfort_temperature", 23.5)
        )
        solar_temperature = float(
            self.room_value(room["id"], "solar_temperature", 25.5)
        )
        normal_shading_temperature = float(
            self.room_value(
                room["id"], "normal_shading_temperature", comfort_temperature
            )
        )
        reopen_temperature = float(
            self.room_value(room["id"], "reopen_temperature", 22.0)
        )
        comfort_allowed = occupied or not room.get(
            "comfort_requires_occupancy", False
        )
        venetian_only = self._venetian_only(room)
        if venetian_only:
            if not indoor_entity:
                runtime.shading_active = True
            elif indoor_valid:
                if runtime.shading_active and indoor < reopen_temperature:
                    runtime.shading_active = False
                elif not runtime.shading_active and indoor >= normal_shading_temperature:
                    runtime.shading_active = True

        highest_mode = MODE_OPEN
        reasons: list[str] = []
        morning_transition_waiting = False
        for sector in room.get("sectors", []):
            if sector in active_sectors:
                if venetian_only:
                    if weather_pass and outdoor_ok and comfort_allowed and (glare or runtime.shading_active):
                        mode = MODE_SOLAR
                        reason = "Normal adaptive solar shading"
                    else:
                        mode = MODE_IDLE
                        waiting = weather_failed or [
                            "normal shading temperature / occupancy / outdoor condition"
                        ]
                        reason = f"Waiting: {', '.join(waiting)}"
                elif (
                    indoor_valid
                    and indoor >= solar_temperature
                    and weather_pass
                    and outdoor_ok
                ):
                    mode = MODE_SOLAR
                    reason = "Solar heat reduction"
                elif (
                    comfort_allowed
                    and weather_pass
                    and (
                        glare
                        or not indoor_entity
                        or (indoor_valid and indoor >= comfort_temperature)
                    )
                ):
                    mode = MODE_COMFORT
                    reason = "Glare / comfort protection"
                else:
                    mode = MODE_IDLE
                    waiting = weather_failed or [
                        "temperature / occupancy / outdoor condition"
                    ]
                    reason = f"Waiting: {', '.join(waiting)}"
            else:
                mode = MODE_OPEN
                reason = "Sun outside this sector"

            morning_handover = bool(
                runtime.night_morning_handover_pending
                and self.sun_runtime[sector["id"]].geometry_active
                and mode not in {MODE_COMFORT, MODE_SOLAR, MODE_HEAT}
            )
            morning_hold = bool(
                morning_handover
                and runtime.night_morning_hold_until
                and runtime.night_morning_hold_until > now
            )
            if morning_handover:
                if morning_hold:
                    mode = MODE_IDLE
                    morning_transition_waiting = True
                    reason = "Morning transition holds Night target while shading conditions settle"
                else:
                    mode = MODE_OPEN
                    reason = "Morning transition window ended; cover opened"

            if mode != MODE_IDLE:
                await self._apply_sector_mode(
                    room, sector, runtime, mode, elevation, reason
                )
            sector_runtime = self.sun_runtime[sector["id"]]
            sector_runtime.mode = mode
            sector_runtime.shading_active = mode in {MODE_COMFORT, MODE_SOLAR, MODE_HEAT, MODE_SAFETY}
            if mode in {MODE_COMFORT, MODE_SOLAR}:
                sector_runtime.status = "shading_active"
            elif mode == MODE_IDLE and sector_runtime.geometry_active:
                sector_runtime.status = (
                    "night_transition_hold" if morning_hold else "waiting_conditions"
                )
            sector_runtime.status_reason = reason
            reasons.append(f"{sector['name']}: {reason}")
            if self._mode_priority(mode) > self._mode_priority(highest_mode):
                highest_mode = mode

        if runtime.night_morning_handover_pending and not morning_transition_waiting:
            runtime.night_morning_handover_pending = False
            runtime.night_morning_hold_until = None
        runtime.mode = (
            MODE_IDLE
            if morning_transition_waiting and highest_mode == MODE_OPEN
            else highest_mode if room.get("sectors") else MODE_IDLE
        )
        runtime.reason = " · ".join(reasons) if reasons else "No sectors configured"
        await self._save_room_runtime(runtime)

    @staticmethod
    def _mode_priority(mode: str) -> int:
        return {
            MODE_IDLE: 0,
            MODE_OPEN: 1,
            MODE_COMFORT: 2,
            MODE_SOLAR: 3,
            MODE_HEAT: 4,
            MODE_NIGHT: 5,
            MODE_SAFETY: 6,
        }.get(mode, 0)

    def _evening_release_reached(
        self, room: dict[str, Any], now: datetime
    ) -> bool:
        fixed = room.get(
            "evening_release_time",
            self.config.get("evening_release_time", "18:00:00"),
        )
        try:
            hour, minute, second = [int(part) for part in fixed.split(":")]
        except (AttributeError, ValueError):
            hour, minute, second = 18, 0, 0
        fixed_dt = now.replace(
            hour=hour, minute=minute, second=second, microsecond=0
        )
        if now >= fixed_dt:
            return True
        state = self.hass.states.get(
            self.config.get(CONF_SUN_ENTITY, "sun.sun")
        )
        next_setting = state.attributes.get("next_setting") if state else None
        parsed = dt_util.parse_datetime(next_setting) if next_setting else None
        if parsed is None:
            return False
        release = dt_util.as_local(parsed) + timedelta(
            minutes=int(
                room.get(
                    "sunset_offset_minutes",
                    self.config.get("sunset_offset_minutes", -15),
                )
            )
        )
        return now >= release

    async def _evaluate_easy_room(
        self, room: dict[str, Any], runtime: RoomRuntime, now: datetime
    ) -> None:
        """Evaluate the compact geometry-first Easy Mode controller.

        Geometry is always mandatory. Each sector then uses exactly its
        selected geometry, Lux, or external on/off source. Selecting an
        outdoor-temperature sensor automatically adds its minimum condition.
        """
        runtime.schedule_active = True
        runtime.schedule_reason = "This setup does not use an activity schedule"
        runtime.next_schedule_change = None
        runtime.pause_mode = PAUSE_AUTO
        runtime.pause_until = None
        runtime.heat_active = False
        runtime.finished_today = False
        runtime.shading_active = False
        runtime.night_active = False
        runtime.night_blocked = False
        runtime.night_reason = "Night function is not configured for this setup"
        runtime.easy_confirmation_state = "inactive"
        runtime.easy_source_summary = "Sun geometry"

        temperature_pass, temperature_source, temperature_value, temperature_minimum = (
            self._outdoor_temperature_condition(room)
        )
        runtime.outdoor_temperature_condition_enabled = bool(
            str(room.get("outdoor_temperature") or "").strip()
        )
        runtime.outdoor_temperature_source = temperature_source
        runtime.outdoor_temperature_value = temperature_value
        runtime.outdoor_temperature_minimum = temperature_minimum
        runtime.outdoor_temperature_passed = (
            temperature_pass
            if runtime.outdoor_temperature_condition_enabled
            else None
        )

        if not runtime.enabled:
            runtime.mode = MODE_DISABLED
            runtime.reason = "Manual Override is active"
            self._mark_room_sectors(
                room, status="disabled", reason=runtime.reason,
                mode=MODE_DISABLED, active=False,
            )
            await self._save_room_runtime(runtime)
            return

        sun_entity = self.config.get(CONF_SUN_ENTITY, "sun.sun")
        sun_state = self.hass.states.get(sun_entity)
        azimuth = parse_numeric_value(
            sun_state.attributes.get("azimuth") if sun_state else None
        )
        elevation = parse_numeric_value(
            sun_state.attributes.get("elevation") if sun_state else None
        )
        if (
            sun_state is None
            or sun_state.state in {"unknown", "unavailable"}
            or azimuth is None
            or elevation is None
        ):
            runtime.mode = MODE_IDLE
            runtime.reason = "Sun position is unavailable; cover positions held"
            self._mark_room_sectors(
                room, status="not_evaluated", reason=runtime.reason,
                mode=MODE_IDLE, active=False,
            )
            await self._save_room_runtime(runtime)
            return

        sun_up = sun_state.state == "above_horizon"
        active_count = 0
        geometry_count = 0
        confirmations: list[bool | None] = []
        source_labels: set[str] = set()
        source_label_map = {
            "binary": "Binary sensor",
            "lux": "Lux sensor",
            "geometry": "Sun geometry",
        }
        for sector in room.get("sectors", []):
            sector_runtime = self.sun_runtime[sector["id"]]
            if not bool(self.sector_value(sector["id"], "enabled", True)):
                sector_runtime.geometry_active = False
                sector_runtime.shading_active = False
                sector_runtime.effective_active = False
                sector_runtime.confirmation_source = "geometry"
                sector_runtime.confirmation_entity = None
                sector_runtime.confirmation_state = None
                sector_runtime.mode = MODE_DISABLED
                sector_runtime.status = "disabled"
                sector_runtime.status_reason = "Sector disabled"
                continue

            start = float(sector.get("azimuth_start", 0))
            end = float(sector.get("azimuth_end", 359))
            minimum = float(sector.get("elevation_min", 0))
            geometry = bool(
                sun_up
                and azimuth_inside(azimuth, start, end)
                and elevation >= minimum
            )
            confirmation, source, source_entity = self._easy_sector_confirmation(
                sector
            )
            confirmed = confirmation is not False
            active = bool(geometry and confirmed and temperature_pass)

            sector_runtime.geometry_active = geometry
            sector_runtime.shading_active = active
            sector_runtime.effective_active = active
            sector_runtime.confirmation_source = source
            sector_runtime.confirmation_entity = source_entity
            sector_runtime.confirmation_state = confirmation
            sector_runtime.mode = MODE_SOLAR if active else MODE_OPEN
            source_labels.add(source_label_map[source])
            if geometry:
                geometry_count += 1
                confirmations.append(confirmation)

            if not sun_up:
                sector_runtime.status = "sun_below_horizon"
                sector_runtime.status_reason = "Sun is below the horizon"
            elif not geometry:
                sector_runtime.status = "outside_sun_sector"
                sector_runtime.status_reason = "Sun is outside this facade sector"
            elif confirmation is False:
                sector_runtime.status = "sun_not_confirmed"
                sector_runtime.status_reason = (
                    f"{source_label_map[source]} does not confirm direct sun"
                )
            elif not temperature_pass:
                sector_runtime.status = "temperature_blocked"
                sector_runtime.status_reason = (
                    "Outdoor temperature sensor is unavailable"
                    if temperature_value is None
                    else "Outdoor temperature is below the configured minimum"
                )
            else:
                sector_runtime.status = "sun_detected"
                sector_runtime.status_reason = (
                    "Sun is confirmed inside this facade sector"
                    if confirmation is True
                    else "Sun geometry is active; optional confirmation is unavailable"
                )

            self._diag(
                "easy_sector_inputs",
                full=True,
                room_id=room["id"],
                sector_id=sector["id"],
                geometry_active=geometry,
                confirmation_source=source,
                confirmation_entity=source_entity,
                confirmation_state=confirmation,
                outdoor_temperature_condition_passed=temperature_pass,
                effective_active=active,
            )
            if active:
                active_count += 1
                runtime.active_sectors.append(sector.get("name", ""))
            await self._apply_sector_mode(
                room, sector, runtime,
                MODE_SOLAR if active else MODE_OPEN,
                elevation,
                sector_runtime.status_reason,
            )

        if not geometry_count:
            runtime.easy_confirmation_state = "inactive"
        elif confirmations and all(value is None for value in confirmations):
            runtime.easy_confirmation_state = "geometry_fallback"
        elif confirmations and all(value is True for value in confirmations):
            runtime.easy_confirmation_state = "confirmed"
        elif confirmations and all(value is False for value in confirmations):
            runtime.easy_confirmation_state = "blocked"
        else:
            runtime.easy_confirmation_state = "mixed"
        runtime.easy_source_summary = (
            next(iter(source_labels))
            if len(source_labels) == 1
            else "Mixed" if source_labels else "Sun geometry"
        )
        runtime.mode = MODE_SOLAR if active_count else MODE_OPEN
        runtime.shading_active = bool(active_count)
        if active_count:
            runtime.reason = "Sun is active in a configured facade sector"
        elif geometry_count and not temperature_pass:
            runtime.reason = "Outdoor temperature condition blocks shading"
        elif geometry_count:
            runtime.reason = "Optional sun confirmation blocks shading"
        else:
            runtime.reason = "Sun is outside all configured facade sectors"
        await self._save_room_runtime(runtime)

    async def _apply_room_mode(
        self,
        room: dict[str, Any],
        runtime: RoomRuntime,
        mode: str,
        elevation: float,
    ) -> None:
        for sector in room.get("sectors", []):
            await self._apply_sector_mode(
                room, sector, runtime, mode, elevation, runtime.reason
            )

    async def _apply_sector_mode(
        self,
        room: dict[str, Any],
        sector: dict[str, Any],
        runtime: RoomRuntime,
        mode: str,
        elevation: float,
        reason: str,
    ) -> None:
        for layer in sector.get("layers", []):
            position, tilt = self._targets(layer, mode, elevation)
            for cover in layer.get("covers", []):
                await self._apply_cover(
                    room,
                    sector,
                    layer,
                    cover,
                    runtime,
                    mode,
                    position,
                    tilt,
                    reason,
                )

    def _targets(
        self, layer: dict[str, Any], mode: str, elevation: float
    ) -> tuple[float, float | None]:
        """Return targets using profile-specific physical behavior.

        Cover height uses Home Assistant semantics (0 closed, 100 open). Slat
        tilt uses the KNX convention (0 fully open, 100 fully closed).
        """
        profile = layer.get("profile", DEVICE_VENETIAN)
        defaults = PROFILE_DEFAULTS.get(profile, PROFILE_DEFAULTS[DEVICE_VENETIAN])
        layer_id = layer["id"]

        def value(key: str, default: float) -> float:
            return clamp_percent(
                float(self.layer_value(layer_id, key, layer.get(key, default)))
            )

        def adaptive(fallback: float) -> float:
            points = []
            for index, point in enumerate(
                layer.get("tilt_curve", defaults.get("tilt_curve", [])), start=1
            ):
                points.append(
                    {
                        "elevation": self.layer_value(
                            layer_id, f"tilt_elevation_{index}", point.get("elevation", 0)
                        ),
                        "tilt": self.layer_value(
                            layer_id, f"tilt_value_{index}", point.get("tilt", fallback)
                        ),
                    }
                )
            return adaptive_tilt(elevation, fallback, points)

        # Exterior venetian blinds have no partial-height comfort stage.
        if profile == DEVICE_VENETIAN:
            if mode in {MODE_COMFORT, MODE_SOLAR}:
                return 0.0, adaptive(float(defaults["solar_tilt"]))
            if mode == MODE_HEAT:
                return 0.0, value("heat_tilt", float(defaults["heat_tilt"]))
            if mode == MODE_NIGHT:
                return value("night_position", 0.0), value(
                    "night_tilt", float(defaults["night_tilt"])
                )
            if mode == MODE_SAFETY:
                return value("safety_position", 100.0), value(
                    "safety_tilt", float(defaults["safety_tilt"])
                )
            return value("open_position", 100.0), value(
                "open_tilt", float(defaults["open_tilt"])
            )

        # Vertical blinds cover the opening first, then adjust slats.
        if profile == DEVICE_VERTICAL:
            if mode == MODE_COMFORT:
                return 0.0, value("comfort_tilt", float(defaults["comfort_tilt"]))
            if mode == MODE_SOLAR:
                return 0.0, adaptive(float(defaults["solar_tilt"]))
            if mode == MODE_HEAT:
                return 0.0, value("heat_tilt", float(defaults["heat_tilt"]))
            if mode == MODE_NIGHT:
                return value("night_position", 0.0), value(
                    "night_tilt", float(defaults["night_tilt"])
                )
            if mode == MODE_SAFETY:
                return value("safety_position", 100.0), value(
                    "safety_tilt", float(defaults["safety_tilt"])
                )
            return value("open_position", 100.0), value(
                "open_tilt", float(defaults["open_tilt"])
            )

        key = f"{mode}_position"
        default_position = float(defaults.get(key, defaults.get("open_position", 100.0)))
        return value(key, default_position), None

    async def _apply_cover(
        self,
        room: dict[str, Any],
        sector: dict[str, Any],
        layer: dict[str, Any],
        cover: dict[str, Any],
        runtime: RoomRuntime,
        mode: str,
        target_position: float,
        target_tilt: float | None,
        reason: str,
    ) -> None:
        entity_id = cover["entity"]
        profile = layer.get("profile", DEVICE_VENETIAN)
        target_position = clamp_percent(target_position)
        if mode != MODE_SAFETY and profile != DEVICE_BINARY:
            max_open = clamp_percent(float(cover.get("max_open_position", 100.0)))
            target_position = min(target_position, max_open)

        state = self.hass.states.get(entity_id)
        current_position = (
            state.attributes.get("current_position") if state else None
        )
        if profile == DEVICE_BINARY and state is not None and current_position is None:
            if state.state == "open":
                current_position = 100.0
            elif state.state == "closed":
                current_position = 0.0
        current_tilt = (
            state.attributes.get("current_tilt_position") if state else None
        )
        displayed_position = (
            100.0 - target_position
            if cover.get("invert_position", False)
            else target_position
        )
        displayed_tilt = target_tilt
        if target_tilt is not None and cover.get("invert_tilt", False):
            displayed_tilt = 100.0 - target_tilt
        suppressions: list[str] = []

        pause_info = self.cover_pause_info(cover) if self.advanced_mode else {
            "active": False, "until": None, "reason": "", "pause_mode": PAUSE_AUTO,
        }
        lock = cover.get("lock", "")
        if self.advanced_mode and pause_info["active"] and mode != MODE_SAFETY:
            suppressions.append("cover_paused_until_morning")
        elif self.advanced_mode and lock and _is_on(self.hass, lock) and mode != MODE_SAFETY:
            suppressions.append("automation_lock")

        window = cover.get("window", "")
        window_safe_state = cover.get("window_safe_state", "on")
        window_unsafe = bool(window) and not self.hass.states.is_state(
            window, window_safe_state
        )
        if self.advanced_mode and window_unsafe and mode != MODE_SAFETY:
            policy = cover.get("window_policy", WINDOW_POLICY_BLOCK_CLOSING)
            if policy == WINDOW_POLICY_BLOCK_ALL:
                suppressions.append("unsafe_window")
            elif policy == WINDOW_POLICY_BLOCK_CLOSING:
                # Compare in Home Assistant command/feedback space.  The
                # logical integration target may be inverted per cover.
                if current_position is None or displayed_position < float(
                    current_position
                ):
                    suppressions.append("unsafe_window_closing_blocked")

        target_record = {
            "entity_id": entity_id,
            "name": cover.get("name") or self._entity_display_name(entity_id, "Cover"),
            "short": cover.get("short", ""),
            "mode": mode,
            "position": target_position,
            "command_position": displayed_position,
            "tilt": target_tilt,
            "command_tilt": displayed_tilt,
            "tilt_inverted": bool(cover.get("invert_tilt", False)),
            "tilt_mapping": (
                "inverted" if cover.get("invert_tilt", False) else "knx_default"
            ),
            "sector": sector["name"],
            "sector_id": sector["id"],
            "layer": layer["name"],
            "layer_id": layer["id"],
            "profile": profile,
            "reason": reason,
            "suppressed": suppressions,
            "cover_pause_active": pause_info["active"],
            "cover_pause_until": pause_info["until"],
            "cover_pause_reason": pause_info["reason"],
        }

        position_tolerance, tilt_tolerance = self._layer_tolerances(layer)
        position_needed = (
            current_position is None
            or abs(float(current_position) - displayed_position) > position_tolerance
        )
        tilt_needed = (
            displayed_tilt is not None
            and (
                current_tilt is None
                or abs(float(current_tilt) - displayed_tilt) > tilt_tolerance
            )
        )
        movement_needed = position_needed or tilt_needed

        if suppressions:
            if movement_needed:
                runtime.suppressed_commands += 1
                self._diag(
                    "cover_command_suppressed",
                    room_id=runtime.room_id,
                    cover=target_record["name"] or "Cover",
                    mode=mode,
                    reasons=list(suppressions),
                )
            else:
                target_record["suppressed"] = [
                    reason
                    for reason, needed in (
                        ("position_already_correct", not position_needed),
                        ("tilt_already_correct", displayed_tilt is not None and not tilt_needed),
                    )
                    if needed
                ]
            runtime.targets.append(target_record)
            return

        memory = self.command_memory.setdefault(entity_id, CommandMemory())
        now = dt_util.now()
        cooldown = DEFAULT_COMMAND_COOLDOWN
        supported_features = int(
            state.attributes.get("supported_features", 0) if state else 0
        )
        can_set_position = bool(
            supported_features & int(CoverEntityFeature.SET_POSITION)
        )
        can_set_tilt = bool(
            supported_features & int(CoverEntityFeature.SET_TILT_POSITION)
        )
        sent = 0

        position_correct = (
            current_position is not None
            and abs(float(current_position) - displayed_position)
            <= position_tolerance
        )
        position_cooldown = (
            memory.position == displayed_position
            and memory.position_at is not None
            and (now - memory.position_at).total_seconds() < cooldown
        )
        if position_correct:
            suppressions.append("position_already_correct")
        elif position_cooldown:
            suppressions.append("position_command_cooldown")
        elif (
            current_position is None
            and profile != DEVICE_BINARY
            and not can_set_position
        ):
            suppressions.append("position_feedback_unknown")
        else:
            self._begin_own_command_session(
                entity_id, "position", displayed_position, now
            )
            if profile == DEVICE_BINARY:
                service = "open_cover" if displayed_position >= 50.0 else "close_cover"
                await self.hass.services.async_call(
                    "cover", service, {"entity_id": entity_id}, blocking=False
                )
            else:
                await self.hass.services.async_call(
                    "cover",
                    "set_cover_position",
                    {
                        "entity_id": entity_id,
                        "position": round(displayed_position),
                    },
                    blocking=False,
                )
            memory.position = displayed_position
            memory.position_at = now
            memory.last_activity_at = now
            sent += 1

        if displayed_tilt is not None and profile != DEVICE_BINARY:
            tilt_correct = (
                current_tilt is not None
                and abs(float(current_tilt) - displayed_tilt)
                <= tilt_tolerance
            )
            tilt_cooldown = (
                memory.tilt == displayed_tilt
                and memory.tilt_at is not None
                and (now - memory.tilt_at).total_seconds() < cooldown
            )
            if tilt_correct:
                suppressions.append("tilt_already_correct")
            elif tilt_cooldown:
                suppressions.append("tilt_command_cooldown")
            elif current_tilt is None and not can_set_tilt:
                suppressions.append("tilt_feedback_unknown")
            else:
                self._begin_own_command_session(
                    entity_id, "tilt", displayed_tilt, now
                )
                await self.hass.services.async_call(
                    "cover",
                    "set_cover_tilt_position",
                    {
                        "entity_id": entity_id,
                        "tilt_position": round(displayed_tilt),
                    },
                    blocking=False,
                )
                memory.tilt = displayed_tilt
                memory.tilt_at = now
                memory.last_activity_at = now
                sent += 1

        runtime.sent_commands += sent
        meaningful_suppressions = [reason for reason in suppressions if reason not in {"position_already_correct", "tilt_already_correct", "position_command_cooldown", "tilt_command_cooldown"}]
        runtime.suppressed_commands += len(meaningful_suppressions)
        if sent:
            runtime.last_command = now
            self._diag(
                "cover_command_sent",
                room_id=runtime.room_id,
                cover=target_record["name"],
                mode=mode,
                position=round(displayed_position),
                tilt=None if displayed_tilt is None else round(displayed_tilt),
                commands=sent,
            )
        elif suppressions:
            routine_reasons = {
                "position_already_correct",
                "tilt_already_correct",
                "position_command_cooldown",
                "tilt_command_cooldown",
            }
            self._diag(
                "cover_command_suppressed",
                full=all(reason in routine_reasons for reason in suppressions),
                room_id=runtime.room_id,
                cover=target_record["name"],
                mode=mode,
                reasons=list(suppressions),
            )
        target_record["suppressed"] = suppressions
        target_record["commands_sent"] = sent
        runtime.targets.append(target_record)

    async def _save_room_runtime(self, runtime: RoomRuntime) -> None:
        previous = self._last_logged_mode.get(runtime.room_id)
        if previous != runtime.mode:
            self._diag(
                "room_mode_changed",
                room_id=runtime.room_id,
                room=runtime.name,
                previous=previous,
                mode=runtime.mode,
                reason=runtime.reason,
            )
            self._last_logged_mode[runtime.room_id] = runtime.mode
        self._diag(
            "room_evaluated",
            full=True,
            room_id=runtime.room_id,
            room=runtime.name,
            mode=runtime.mode,
            reason=runtime.reason,
            active_sectors=list(runtime.active_sectors),
            targets=len(runtime.targets),
        )
        await self.store.async_save_room_runtime(
            runtime.room_id,
            {
                "enabled": runtime.enabled,
                "pause_mode": runtime.pause_mode,
                "pause_until": _serialize_datetime(runtime.pause_until),
                "pause_waiting_for_night": runtime.pause_waiting_for_night,
                "heat_active": runtime.heat_active,
                "shading_active": runtime.shading_active,
                "finished_today": runtime.finished_today,
                "sent_commands": runtime.sent_commands,
                "suppressed_commands": runtime.suppressed_commands,
            },
        )

    async def _save_sun_runtime(self, runtime: SectorSunRuntime) -> None:
        await self.store.async_save_sun_runtime(
            runtime.sector_id,
            {
                "is_on": runtime.is_on,
                "pending_target": runtime.pending_target,
                "pending_since": _serialize_datetime(runtime.pending_since),
                "pending_until": _serialize_datetime(runtime.pending_until),
                "last_transition": _serialize_datetime(runtime.last_transition),
                "reason": runtime.reason,
                "status": runtime.status,
                "status_reason": runtime.status_reason,
                "geometry_active": runtime.geometry_active,
                "shading_active": runtime.shading_active,
                "mode": runtime.mode,
            },
        )
