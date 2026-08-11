from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
import logging
import math
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
    CONF_ADVANCED_FEATURES,
    CONF_DIAGNOSTIC_LEVEL,
    CONF_EVALUATION_INTERVAL,
    CONF_EXTERNAL_MOVEMENT_DETECTION,
    CONF_ROOMS,
    CONF_SUN_PRESENCE_ENTITY,
    DAY_WINDOW_ALL_DAY,
    DAY_WINDOW_FIXED,
    DEFAULT_COMMAND_COOLDOWN,
    DEFAULT_EVALUATION_DEBOUNCE_SECONDS,
    DEFAULT_EVALUATION_INTERVAL,
    DEFAULT_MAX_OPEN_HEARTBEAT_SECONDS,
    DEFAULT_MAX_OPEN_TOLERANCE,
    DEFAULT_POSITION_TOLERANCE,
    DEFAULT_SOURCE_STALE_SECONDS,
    DEFAULT_SUN_ENTITY,
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
    FEATURE_DASHBOARD_BADGES,
    FEATURE_TEST_TOOLS,
    FEATURE_GLARE_PROTECTION,
    FEATURE_MAXIMUM_OPENING,
    MODE_COMFORT,
    MODE_DISABLED,
    MODE_FINISHED,
    MODE_GLARE,
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
    SHARED_FEATURES,
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
from .execution import (
    CommandContext,
    CommandPlanner,
    CommandRequest,
    CommandResult,
    CommandTarget,
    FeedbackQuality,
)
from .decision import (
    CommandResult as DecisionCommandResult,
    CommandResultStatus,
    DecisionContext,
    DecisionPipeline,
    InputKind,
    InputSnapshot,
    InputValue,
    ProtectedZone,
    QualityState,
    SunGeometry,
    Target as DecisionTarget,
    PreviewPoint,
    normalize_input,
    preview_day,
    simulate as simulate_decision,
)
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
        self.command_planner = CommandPlanner(lambda: dt_util.now())
        # The pure pipeline is intentionally long-lived: simulation, preview
        # and live evaluations all resolve through the same deterministic
        # candidate ordering.  HA service calls stay in the command planner
        # adapter below.
        self.decision_pipeline = DecisionPipeline()
        self._decision_target_traces: dict[str, list[dict[str, Any]]] = {}
        self._decision_room_facts: dict[str, dict[str, bool]] = {}
        self._command_step_timer_unsub: Callable[[], None] | None = None
        self._verification_timer_unsub: Callable[[], None] | None = None
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
        self._geometry_timer_unsubs: dict[str, Callable[[], None]] = {}
        # Normal runtime evaluation is event-driven.  A tiny debounce folds a
        # burst of related state updates into one deterministic input snapshot;
        # the configured 20-minute interval remains only a recovery watchdog.
        self._evaluation_debounce_unsub: Callable[[], None] | None = None
        self._pending_evaluation_triggers: set[str] = set()
        self._schedule_timer_unsubs: dict[str, Callable[[], None]] = {}
        self._heat_release_timer_unsubs: dict[str, Callable[[], None]] = {}
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
        try:
            self.command_planner.restore_ledger(
                self.store.data.get("command_ledger", {})
            )
            self.command_planner.restore_pending_steps(
                self.store.queued_commands()
            )
        except (TypeError, ValueError):
            # A corrupt or pre-schema ledger must never prevent Home
            # Assistant startup.  Preserve the raw record for diagnostics and
            # begin new ownership lifecycles safely.
            _LOGGER.exception("Could not restore Smart Shading command ledger")
            self.command_planner = CommandPlanner(lambda: dt_util.now())
        self._day_key = self.store.day_key()
        self._rebuild_runtime()
        self._restore_command_ownership_sessions()
        await self._async_reconcile_night_end_pauses()
        now = dt_util.now()
        for room in self.config.get(CONF_ROOMS, []):
            runtime = self.rooms.get(str(room.get("id") or ""))
            if runtime is not None:
                self._schedule_heat_release_timer(room, runtime, now)
                self._schedule_geometry_boundary_timer(room, now)

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
            runtime.heat_phase = str(
                saved.get(
                    "heat_phase",
                    "active" if runtime.heat_active else "inactive",
                )
            )
            runtime.shading_active = bool(saved.get("shading_active", False))
            runtime.finished_today = bool(saved.get("finished_today", False))
            runtime.sent_commands = int(saved.get("sent_commands", 0))
            runtime.suppressed_commands = int(
                saved.get("suppressed_commands", 0)
            )
            runtime.decision_trace = self.store.decision_trace(room_id)
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

    def _restore_command_ownership_sessions(self) -> None:
        """Treat feedback for a persisted own target as own feedback after restart."""
        now = dt_util.now()
        self.own_command_sessions.clear()
        for entry in self.command_planner.ledger.values():
            if (
                not entry.owned_by_smart_shading
                or entry.result
                not in {
                    CommandResult.PLANNED,
                    CommandResult.QUEUED,
                    CommandResult.SENT,
                }
            ):
                continue
            context = self._find_cover_by_id(entry.cover_id)
            if context is None:
                continue
            entity_id = str(context[3].get("entity") or "")
            if not entity_id:
                continue
            expiry = entry.expected_deadline or (
                now + timedelta(seconds=OWN_COMMAND_SESSION_TIMEOUT_SECONDS)
            )
            session = OwnCommandSession(
                entity_id=entity_id,
                started_at=entry.created_at,
                updated_at=entry.updated_at,
                expires_at=max(expiry, now + timedelta(seconds=5)),
                position_target=entry.target.position,
                tilt_target=entry.target.tilt,
                position_commanded=entry.target.position is not None,
                tilt_commanded=entry.target.tilt is not None,
            )
            self.own_command_sessions[entity_id] = session

    async def async_start(self) -> None:
        self.async_stop()
        self.reload_config()
        self._rebuild_runtime()
        self._restore_command_ownership_sessions()
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
        if self.advanced_mode and any(
            bool(cover.get("enforce_max_open_position", False))
            for _room, _sector, _layer, cover in self._iter_covers()
        ):
            self._unsubs.append(
                async_track_time_interval(
                    self.hass,
                    self._async_maximum_opening_interval,
                    timedelta(seconds=DEFAULT_MAX_OPEN_HEARTBEAT_SECONDS),
                )
            )
        await self._async_sync_configured_locks()
        for room_id, runtime in self.rooms.items():
            if self.advanced_mode and runtime.pause_mode != PAUSE_AUTO:
                await self._async_room_pause_state_changed(room_id, True)
        await self.async_evaluate_all("startup")
        await self._persist_command_planner()
        self._schedule_command_executor_timers()
        notifications_ready = await self.async_sync_card_notifications()
        if not notifications_ready:
            self._schedule_card_notification_retry(1)

    async def _async_sync_sun_requirement_notification(self) -> None:
        entity_id = DEFAULT_SUN_ENTITY
        state = self.hass.states.get(entity_id)
        notification_id = f"smart_shading_sun_{self.entry.entry_id}"
        invalid = state is None or state.state in {"unknown", "unavailable"}
        if invalid:
            german = (getattr(self.hass.config, "language", "en") or "en").lower().startswith("de")
            title = (
                "Smart Shading – Sonnenintegration fehlt"
                if german
                else "Smart Shading – Sun integration unavailable"
            )
            message = (
                "Die Home-Assistant-Sonnenentität `sun.sun` wurde nicht "
                "gefunden oder ist nicht verfügbar. Aktivieren oder "
                "initialisieren Sie unter Einstellungen → Geräte & Dienste "
                "die native Integration „Sonne“ („Sun“). Sektorbasierte "
                "Beschattung bleibt bis dahin inaktiv."
                if german else
                "The Home Assistant sun entity `sun.sun` was not found or is "
                "unavailable. Enable or initialize the native Sun integration "
                "under Settings → Devices & services. Sector-based shading "
                "remains inactive until then."
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
            (
                f"smart_shading_card_badges_{self.entry.entry_id}_{room['id']}"
                if self.room_feature_enabled(
                    room["id"], FEATURE_DASHBOARD_BADGES
                )
                else f"smart_shading_card_{self.entry.entry_id}_{room['id']}"
            )
            for room in self.config.get(CONF_ROOMS, [])
        }
        successful_ids = previous_ids & configured_ids
        missing_entities = 0
        german = (getattr(self.hass.config, "language", "en") or "en").lower().startswith("de")

        for room in self.config.get(CONF_ROOMS, []):
            room_id = room["id"]
            badges_enabled = self.room_feature_enabled(
                room_id, FEATURE_DASHBOARD_BADGES
            )
            notification_id = (
                f"smart_shading_card_badges_{self.entry.entry_id}_{room_id}"
                if badges_enabled
                else f"smart_shading_card_{self.entry.entry_id}_{room_id}"
            )
            if notification_id in previous_ids:
                continue
            unique_id = f"{self.entry.entry_id}_{room_id}_status"
            entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
            if entity_id is None:
                missing_entities += 1
                _LOGGER.debug("Room status entity not yet registered for %s", room.get("name"))
                continue

            house_entity_id = None
            if badges_enabled:
                house_entity_id = registry.async_get_entity_id(
                    "sensor", DOMAIN, f"{self.entry.entry_id}_house_status"
                )
                if house_entity_id is None:
                    missing_entities += 1
                    _LOGGER.debug("House status entity not yet registered")
                    continue

            card_yaml = (
                "type: custom:smart-shading-card\n"
                f"entity: {entity_id}\n"
            )
            room_badge_yaml = (
                "type: custom:smart-shading-badge\n"
                f"entity: {entity_id}\n"
            )
            house_badge_yaml = (
                "type: custom:smart-shading-badge\n"
                f"entity: {house_entity_id}\n"
                if house_entity_id
                else ""
            )
            badge_message_de = (
                "\n\n**Gewählte Dashboard-Badges:** Öffnen Sie im Dashboard-Editor "
                "`Badge hinzufügen → Smart Shading status` und wählen Sie Haus- "
                "oder Raumstatus. Alternativ können Sie den YAML-Code verwenden.\n\n"
                "Haus-Badge:\n\n```yaml\n"
                f"{house_badge_yaml}```\n\nRaum-Badge:\n\n```yaml\n"
                f"{room_badge_yaml}```"
                if badges_enabled
                else ""
            )
            badge_message_en = (
                "\n\n**Selected dashboard badges:** In the dashboard editor, open "
                "`Add badge → Smart Shading status` and select the house or room "
                "status. You can alternatively use the YAML below.\n\n"
                "House badge:\n\n```yaml\n"
                f"{house_badge_yaml}```\n\nRoom badge:\n\n```yaml\n"
                f"{room_badge_yaml}```"
                if badges_enabled
                else ""
            )
            if german:
                title = f"Smart Shading – Dashboard-Karte für {room['name']}"
                message = (
                    "Der Raum wurde erstellt. Der folgende Code fügt seine "
                    "Smart-Shading-Karte zum Dashboard hinzu.\n\n"
                    "```yaml\n"
                    f"{card_yaml}"
                    "```"
                    f"{badge_message_de}\n\n"
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
                    "```"
                    f"{badge_message_en}\n\n"
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
        for unsub in self._geometry_timer_unsubs.values():
            unsub()
        self._geometry_timer_unsubs.clear()
        for unsub in self._cover_pause_timer_unsubs.values():
            unsub()
        self._cover_pause_timer_unsubs.clear()
        for unsub in self._room_pause_timer_unsubs.values():
            unsub()
        self._room_pause_timer_unsubs.clear()
        for unsub in self._night_timer_unsubs.values():
            unsub()
        self._night_timer_unsubs.clear()
        if self._evaluation_debounce_unsub:
            self._evaluation_debounce_unsub()
            self._evaluation_debounce_unsub = None
        self._pending_evaluation_triggers.clear()
        for unsub in self._schedule_timer_unsubs.values():
            unsub()
        self._schedule_timer_unsubs.clear()
        for unsub in self._heat_release_timer_unsubs.values():
            unsub()
        self._heat_release_timer_unsubs.clear()
        if self._command_step_timer_unsub:
            self._command_step_timer_unsub()
            self._command_step_timer_unsub = None
        if self._verification_timer_unsub:
            self._verification_timer_unsub()
            self._verification_timer_unsub = None

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    async def _queue_evaluation(
        self, trigger: str, *, immediate: bool = False
    ) -> None:
        """Queue one event-driven evaluation and coalesce a state burst.

        Home Assistant commonly emits a source state, its derived helper state
        and a cover feedback event in the same turn.  Running the decision
        pipeline for each individual update made the old periodic controller
        both late and noisy.  This small queue establishes one input snapshot
        for the complete burst while retaining an explicit immediate path for
        Safety and other higher-priority changes.
        """
        self._pending_evaluation_triggers.add(str(trigger))
        if immediate:
            if self._evaluation_debounce_unsub:
                self._evaluation_debounce_unsub()
                self._evaluation_debounce_unsub = None
            await self._flush_queued_evaluation()
            return
        if self._evaluation_debounce_unsub is not None:
            return
        try:
            delay = float(
                self.config.get(
                    "evaluation_debounce_seconds",
                    DEFAULT_EVALUATION_DEBOUNCE_SECONDS,
                )
            )
        except (TypeError, ValueError):
            delay = DEFAULT_EVALUATION_DEBOUNCE_SECONDS

        async def _evaluate(_now) -> None:
            self._evaluation_debounce_unsub = None
            await self._flush_queued_evaluation()

        self._evaluation_debounce_unsub = async_call_later(
            self.hass, max(0.05, min(delay, 5.0)), _evaluate
        )

    async def _flush_queued_evaluation(self) -> None:
        triggers = sorted(self._pending_evaluation_triggers)
        self._pending_evaluation_triggers.clear()
        if not triggers:
            return
        # Preserve useful diagnostic provenance without producing an
        # unbounded trigger string on noisy setups.
        summary = ",".join(triggers[:8])
        if len(triggers) > 8:
            summary = f"{summary},+{len(triggers) - 8}"
        await self.async_evaluate_all(f"event:{summary}")

    def _schedule_schedule_timer(
        self, room_id: str, due: datetime | None
    ) -> None:
        """Schedule an exact room schedule boundary instead of waiting for the watchdog."""
        previous = self._schedule_timer_unsubs.pop(room_id, None)
        if previous:
            previous()
        if due is None:
            return
        seconds = (due - dt_util.now()).total_seconds()
        if seconds <= 0:
            return

        async def _transition(_now) -> None:
            self._schedule_timer_unsubs.pop(room_id, None)
            await self._queue_evaluation(
                f"schedule_transition:{room_id}", immediate=True
            )

        self._schedule_timer_unsubs[room_id] = async_call_later(
            self.hass, max(0.1, seconds), _transition
        )

    def _heat_release_due(
        self, room: dict[str, Any], now: datetime
    ) -> datetime:
        """Return the earliest exact Heat release boundary.

        Heat is a daytime function. Its one daily cycle therefore ends at the
        first of the general shading-schedule boundary, the configured
        sunset-relative release, or the absolute latest release time.
        """
        if not self._schedule_active_at(room, now):
            return now
        fixed = room.get(
            "evening_release_time",
            self.config.get("evening_release_time", "18:00:00"),
        )
        try:
            hour, minute, second = [int(part) for part in str(fixed).split(":")]
            fixed_due = now.replace(
                hour=hour, minute=minute, second=second, microsecond=0
            )
        except (TypeError, ValueError):
            fixed_due = now.replace(hour=18, minute=0, second=0, microsecond=0)
        candidates = [fixed_due]
        _sunrise, sunset = self._virtual_solar_events(now)
        if sunset is None:
            sun = self.hass.states.get(DEFAULT_SUN_ENTITY)
            next_setting = sun.attributes.get("next_setting") if sun else None
            parsed = (
                dt_util.parse_datetime(next_setting)
                if next_setting
                else None
            )
            if parsed is not None and dt_util.as_local(parsed).date() == now.date():
                sunset = dt_util.as_local(parsed)
        if sunset is not None:
            candidates.append(
                sunset
                + timedelta(
                    minutes=int(
                        room.get(
                            "sunset_offset_minutes",
                            self.config.get("sunset_offset_minutes", -15),
                        )
                    )
                )
            )
        schedule_due = self._next_schedule_change(room, now, True)
        if schedule_due is not None:
            candidates.append(schedule_due)
        due = min(candidates)
        return now if due <= now else due

    def _schedule_heat_release_timer(
        self,
        room: dict[str, Any],
        runtime: RoomRuntime,
        now: datetime,
    ) -> None:
        """Arm an exact Heat release wake-up, including after a restart."""
        room_id = runtime.room_id
        previous = self._heat_release_timer_unsubs.pop(room_id, None)
        if previous:
            previous()
        if not runtime.heat_active:
            return
        due = self._heat_release_due(room, now)

        async def _release(_now) -> None:
            self._heat_release_timer_unsubs.pop(room_id, None)
            await self.async_evaluate_all(f"heat_release:{room_id}")

        self._heat_release_timer_unsubs[room_id] = async_call_later(
            self.hass,
            max(0.1, (due - now).total_seconds()),
            _release,
        )

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
            await self._record_command_feedback(entity_id, new_state)
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
                # A hard opening limit intentionally overrides a physical or
                # KNX request above the configured maximum. Correct it from
                # the fresh feedback before normal automation is paused.
                await self._async_enforce_cover_maximum(
                    entity_id, new_state
                )
                await self._activate_cover_pause(
                    room, cover, "external_or_physical_control"
                )
                # A local pause changes the winning trace even without Safety;
                # reevaluate immediately so Card/diagnostics never show a
                # stale Solar target until the recovery watchdog runs.  Safety
                # keeps its explicit trigger because it may immediately move
                # the cover back to its configured safe position.
                trigger = (
                    f"safety_manual_cover:{entity_id}"
                    if self._room_safety_active(room)
                    else f"external_manual_cover:{entity_id}"
                )
                await self.async_evaluate_all(trigger)
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
                # The pause has already cancelled queued physical work.  Run
                # the decision pipeline as well so room mode, winner trace,
                # Card and diagnostics all reflect the external lock now,
                # without waiting for the watchdog.
                await self.async_evaluate_all(
                    f"manual_group_activated:{entity_id}"
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
            await self._queue_evaluation(
                f"lux_state:{sector['id']}"
                if before == runtime.is_on
                else f"sun_presence_transition:{sector['id']}"
            )
            return

        # Sun geometry, temperature, weather, occupancy and window changes
        # now evaluate from one short debounce window.  The interval callback
        # remains a watchdog only and must not be the normal movement path.
        await self._queue_evaluation(f"input_state:{entity_id}")

    async def _async_interval(self, now) -> None:
        await self.async_evaluate_all("watchdog")

    async def _async_maximum_opening_interval(self, now) -> None:
        """Cheap fallback check for opt-in hard limits."""
        await self._async_enforce_all_maximum_openings()

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

    def _maximum_opening_enabled(
        self,
        room: dict[str, Any],
        layer: dict[str, Any],
        cover: dict[str, Any],
    ) -> bool:
        """Return whether one cover has the selected hard-limit feature."""
        return bool(
            self.advanced_mode
            and self.room_feature_enabled(
                str(room.get("id") or ""), FEATURE_MAXIMUM_OPENING
            )
            and profile_supports_position(
                str(layer.get("profile", DEVICE_VENETIAN))
            )
            and cover.get("enforce_max_open_position", False)
        )

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
        if (
            not self._maximum_opening_enabled(room, layer, cover)
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
        if logical_current <= maximum + DEFAULT_MAX_OPEN_TOLERANCE:
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
        for room, _sector, layer, cover in self._iter_covers():
            if self._maximum_opening_enabled(room, layer, cover):
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
        result = {DEFAULT_SUN_ENTITY}
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
        """Return whether any enabled façade currently has direct sun.

        Heat protection defaults to geometry confirmation.  The former
        implementation only accepted Lux/binary sources, which made the
        default configuration impossible to arm even in full direct sun.
        Compute the live geometry here rather than reading the sector runtime:
        this method runs before the regular sector loop refreshes that runtime.
        """
        sun_state = self.hass.states.get(
            DEFAULT_SUN_ENTITY
        )
        sun_up = bool(sun_state and sun_state.state == "above_horizon")
        azimuth = parse_numeric_value(
            sun_state.attributes.get("azimuth") if sun_state else None
        )
        elevation = parse_numeric_value(
            sun_state.attributes.get("elevation") if sun_state else None
        )
        if not sun_up or azimuth is None or elevation is None:
            return False
        for sector in room.get("sectors", []):
            if not bool(self.sector_value(sector["id"], "enabled", True)):
                continue
            try:
                geometry = bool(
                    azimuth_inside(
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
            except (TypeError, ValueError):
                geometry = False
            if not geometry:
                continue
            confirmed, source, _entity, state = (
                self._advanced_sector_confirmation(sector)
            )
            if source == "geometry":
                return True
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

    def _find_cover_by_id(self, cover_id: str):
        """Return the complete configuration context for a stable cover ID."""
        return next(
            (
                (room, sector, layer, cover)
                for room, sector, layer, cover in self._iter_covers()
                if self._cover_id(cover) == str(cover_id)
            ),
            None,
        )

    @staticmethod
    def _command_priority(mode: str) -> int:
        """One immutable priority mapping shared by planner and trace adapter."""
        return {
            MODE_SAFETY: 1_000,
            MODE_PAUSED: 900,
            MODE_DISABLED: 900,
            MODE_NIGHT: 800,
            MODE_HEAT: 700,
            MODE_GLARE: 600,
            MODE_SOLAR: 500,
            MODE_COMFORT: 400,
            MODE_OPEN: 100,
            MODE_IDLE: 0,
        }.get(mode, 0)

    @staticmethod
    def _feedback_quality(value: Any, *, verification: bool) -> FeedbackQuality:
        """Map customer-facing feedback labels onto the pure executor model."""
        if not verification:
            return FeedbackQuality.NONE
        aliases = {
            "trusted": FeedbackQuality.TRUSTED,
            "trusted_position": FeedbackQuality.TRUSTED,
            "intermediate": FeedbackQuality.UNRELIABLE,
            "unreliable": FeedbackQuality.UNRELIABLE,
            "unreliable_or_intermediate": FeedbackQuality.UNRELIABLE,
            "end_positions": FeedbackQuality.END_POSITIONS,
            "end_positions_only": FeedbackQuality.END_POSITIONS,
            "none": FeedbackQuality.NONE,
            "no_usable_position_feedback": FeedbackQuality.NONE,
        }
        return aliases.get(str(value or "trusted").lower(), FeedbackQuality.TRUSTED)

    async def _persist_command_planner(self) -> None:
        """Persist ownership plus delayed executor work after every lifecycle change."""
        persisted = self.store.data.setdefault("command_ledger", {})
        current_ids = set(persisted)
        desired = self.command_planner.export_ledger()
        for cover_id, entry in desired.items():
            await self.store.async_save_command_ledger(cover_id, entry)
        for cover_id in current_ids - set(desired):
            await self.store.async_delete_command_ledger(cover_id)
        await self.store.async_save_queued_commands(
            self.command_planner.export_pending_steps()
        )

    def _stored_command_ledger(self) -> dict[str, Any]:
        """Read only valid per-cover ledger records from runtime storage."""
        entries = self.store.data.get("command_ledger", {})
        if not isinstance(entries, dict):
            return {}
        return {
            str(cover_id): value
            for cover_id, value in entries.items()
            if isinstance(value, dict) and cover_id != "__all__"
        }

    def _schedule_command_executor_timers(self) -> None:
        """Rebuild the next sequence and verification timers from persisted state."""
        if self._command_step_timer_unsub:
            self._command_step_timer_unsub()
            self._command_step_timer_unsub = None
        if self._verification_timer_unsub:
            self._verification_timer_unsub()
            self._verification_timer_unsub = None

        now = dt_util.now()
        steps = self.command_planner.pending_steps
        if steps:
            due = steps[0].execute_at

            async def _run_steps(_now) -> None:
                self._command_step_timer_unsub = None
                await self._dispatch_due_command_steps()

            self._command_step_timer_unsub = async_call_later(
                self.hass,
                max(0.05, (due - now).total_seconds()),
                _run_steps,
            )

        deadlines = sorted(
            entry.expected_deadline
            for entry in self.command_planner.ledger.values()
            if entry.expected_deadline is not None
            and entry.result is CommandResult.SENT
        )
        if deadlines:
            due = deadlines[0]

            async def _verify(_now) -> None:
                self._verification_timer_unsub = None
                await self._verify_due_command_lifecycles()

            self._verification_timer_unsub = async_call_later(
                self.hass,
                max(0.05, (due - now).total_seconds()),
                _verify,
            )

    async def _cancel_pending_normal_lifecycles(
        self,
        room_id: str,
        reason_code: str,
        *,
        sector_id: str | None = None,
        layer_id: str | None = None,
        include_non_safety: bool = False,
    ) -> tuple[str, ...]:
        """Cancel obsolete normal automation work for one affected scope.

        A disabled or paused room must not later execute a previously queued
        Solar, Comfort, or Open command.  Source and input-quality holds are
        narrower: they affect only the sector (or layer) whose snapshot is
        invalid.  Keeping that boundary here is important because one room
        can have a valid facade and an unavailable facade in the same
        evaluation pass.

        Source and quality holds cancel only normal automation.  A full-room
        disabled/pause hold passes ``include_non_safety=True`` and also stops
        Heat or Night work; Safety always survives.  A step which has already
        been dispatched cannot be physically recalled, but marking its
        lifecycle cancelled prevents any queued follow-up axis or target-
        verification retry from executing.
        """
        if self.command_planner is None:
            return ()

        normal_rules = {MODE_GLARE, MODE_SOLAR, MODE_COMFORT, MODE_OPEN}
        active_results = {
            CommandResult.PLANNED,
            CommandResult.QUEUED,
            CommandResult.SENT,
        }
        now = dt_util.now()
        cancelled_cover_ids: list[str] = []

        # Work from a snapshot: ``cancel_cover`` mutates the ledger and queue.
        for entry in tuple(self.command_planner.ledger.values()):
            context = entry.context
            if str(context.room_id) != str(room_id):
                continue
            if sector_id is not None and str(context.sector_id or "") != str(sector_id):
                continue
            if layer_id is not None and str(context.group_id or "") != str(layer_id):
                continue
            if entry.result not in active_results:
                continue
            if include_non_safety:
                if entry.rule == MODE_SAFETY:
                    continue
            elif entry.rule not in normal_rules:
                continue

            outcome = self.command_planner.cancel_cover(
                entry.cover_id,
                reason_code,
                now=now,
            )
            if outcome is None or outcome.ledger is None:
                continue
            cancelled_cover_ids.append(entry.cover_id)
            self._mirror_command_lifecycle(
                outcome.ledger,
                status=outcome.status,
                reason_code=reason_code,
            )
            self._diag(
                "cover_command_cancelled",
                full=True,
                room_id=room_id,
                sector_id=context.sector_id,
                cover=entry.cover_id,
                reason=reason_code,
                cancelled_steps=[step.step_id for step in outcome.cancelled_steps],
            )

        if not cancelled_cover_ids:
            return ()

        # The queue and ledger are a single durable lifecycle boundary.  Save
        # both before rebuilding callbacks, so a restart cannot revive a
        # command which was invalidated by a hold.
        await self._persist_command_planner()
        self._schedule_command_executor_timers()
        return tuple(cancelled_cover_ids)

    def _mirror_command_lifecycle(
        self,
        entry: Any,
        *,
        status: CommandResult | str | None = None,
        reason_code: str | None = None,
        last_command_axis: str | None = None,
    ) -> RoomRuntime | None:
        """Copy one planner lifecycle outcome into its live decision records.

        The command planner deliberately owns the durable physical lifecycle,
        while ``RoomRuntime.targets`` and the nested Advanced trace are the
        customer-facing projection.  Keeping this bridge in one place avoids
        a sent/verified/failed ledger disagreeing with diagnostics after an
        evaluation has already completed.
        """
        if entry is None:
            return None
        room_id = str(getattr(getattr(entry, "context", None), "room_id", "") or "")
        runtime = self.rooms.get(room_id)
        if runtime is None:
            return None
        cover_id = str(getattr(entry, "cover_id", "") or "")
        lifecycle_id = str(getattr(entry, "lifecycle_id", "") or "")
        result = status or getattr(entry, "result", None)
        result_value = result.value if isinstance(result, CommandResult) else str(result or "")
        resolved_reason = str(
            reason_code
            or getattr(entry, "failure_reason", None)
            or getattr(entry, "reason_code", None)
            or "command_lifecycle_updated"
        )
        common = {
            "command_result": result_value,
            "command_reason_code": resolved_reason,
            "lifecycle_id": lifecycle_id or None,
            "ownership": bool(getattr(entry, "owned_by_smart_shading", False)),
            "target_reached": getattr(entry, "target_reached", None),
        }
        if last_command_axis:
            common["last_command_axis"] = last_command_axis

        for target in runtime.targets:
            if str(target.get("cover_id") or "") != cover_id:
                continue
            target_lifecycle = str(target.get("lifecycle_id") or "")
            # Do not let a late result from a superseded lifecycle overwrite
            # the target selected by a newer evaluation.
            if target_lifecycle and lifecycle_id and target_lifecycle != lifecycle_id:
                continue
            target.update(common)

        # ``_decision_target_traces`` is the source for a fresh save, while
        # ``runtime.decision_trace`` may be restored from disk or already
        # exposed to a listener.  Update both (deduplicating shared lists) so
        # the nested per-cover result never remains stuck at ``planned``.
        trace_lists: list[list[dict[str, Any]]] = []
        source_traces = self._decision_target_traces.get(runtime.room_id)
        if isinstance(source_traces, list):
            trace_lists.append(source_traces)
        persisted_traces = runtime.decision_trace.get("target_decisions")
        if isinstance(persisted_traces, list) and persisted_traces is not source_traces:
            trace_lists.append(persisted_traces)
        seen_records: set[int] = set()
        for records in trace_lists:
            for record in records:
                if not isinstance(record, dict) or id(record) in seen_records:
                    continue
                seen_records.add(id(record))
                covers = record.get("covers")
                if not isinstance(covers, list):
                    continue
                for cover_record in covers:
                    if not isinstance(cover_record, dict):
                        continue
                    if str(cover_record.get("cover_id") or "") != cover_id:
                        continue
                    command = cover_record.get("command")
                    if not isinstance(command, dict):
                        continue
                    trace = command.get("trace")
                    if not isinstance(trace, dict):
                        continue
                    command_result = trace.get("command_result")
                    if not isinstance(command_result, dict):
                        command_result = {}
                    details = dict(command_result.get("details") or {})
                    details.update(
                        {
                            "cover_id": cover_id,
                            "lifecycle_id": lifecycle_id or None,
                        }
                    )
                    command_result.update(
                        {
                            "status": result_value,
                            "reason_code": resolved_reason,
                            "details": details,
                        }
                    )
                    trace["command_result"] = command_result
        return runtime

    async def _dispatch_due_command_steps(self) -> bool:
        """Send due pure-planner steps through the one HA service adapter."""
        now = dt_util.now()
        steps = self.command_planner.take_due(now=now)
        changed_runtimes: set[str] = set()
        for step in steps:
            # ``take_due`` returns a deterministic batch.  A failed first
            # axis can invalidate a later axis from that same batch, so check
            # the live lifecycle again before every physical service call.
            active_entry = self.command_planner.ledger_entry(step.cover_id)
            if (
                active_entry is None
                or active_entry.lifecycle_id != step.lifecycle_id
                or active_entry.result
                in {
                    CommandResult.FAILED,
                    CommandResult.CANCELLED,
                    CommandResult.TARGET_REACHED,
                    CommandResult.TARGET_NOT_REACHED,
                }
            ):
                continue
            context = self._find_cover_by_id(step.cover_id)
            if context is None:
                failure = self.command_planner.mark_failed(
                    step.cover_id, "cover_removed_before_execution", now=now
                )
                if failure and failure.ledger:
                    runtime = self._mirror_command_lifecycle(
                        failure.ledger,
                        status=failure.status,
                        reason_code=failure.reason_code,
                    )
                    if runtime is not None:
                        changed_runtimes.add(runtime.room_id)
                continue
            room, _sector, layer, cover = context
            entity_id = str(cover.get("entity") or "")
            if not entity_id:
                failure = self.command_planner.mark_failed(
                    step.cover_id, "cover_entity_missing", now=now
                )
                if failure and failure.ledger:
                    runtime = self._mirror_command_lifecycle(
                        failure.ledger,
                        status=failure.status,
                        reason_code=failure.reason_code,
                    )
                    if runtime is not None:
                        changed_runtimes.add(runtime.room_id)
                continue
            profile = str(layer.get("profile", DEVICE_VENETIAN))
            try:
                self._begin_own_command_session(
                    entity_id, step.axis, step.target, now
                )
                if step.axis == "position":
                    if profile == DEVICE_BINARY:
                        service = (
                            "open_cover" if step.target >= 50.0 else "close_cover"
                        )
                        data = {"entity_id": entity_id}
                    else:
                        service = "set_cover_position"
                        data = {
                            "entity_id": entity_id,
                            "position": round(step.target),
                        }
                    memory = self.command_memory.setdefault(
                        entity_id, CommandMemory()
                    )
                    memory.position = step.target
                    memory.position_at = now
                    memory.last_activity_at = now
                else:
                    service = "set_cover_tilt_position"
                    data = {
                        "entity_id": entity_id,
                        "tilt_position": round(step.target),
                    }
                    memory = self.command_memory.setdefault(
                        entity_id, CommandMemory()
                    )
                    memory.tilt = step.target
                    memory.tilt_at = now
                    memory.last_activity_at = now
                await self.hass.services.async_call(
                    "cover", service, data, blocking=False
                )
            except Exception:
                failure = self.command_planner.mark_failed(
                    step.cover_id, "cover_service_failed", now=now
                )
                if failure and failure.ledger:
                    runtime = self._mirror_command_lifecycle(
                        failure.ledger,
                        status=failure.status,
                        reason_code=failure.reason_code,
                    )
                    if runtime is not None:
                        changed_runtimes.add(runtime.room_id)
                _LOGGER.exception(
                    "Smart Shading command step failed for %s", entity_id
                )
                continue

            entry = self.command_planner.ledger_entry(step.cover_id)
            runtime = self._mirror_command_lifecycle(
                entry,
                status=CommandResult.SENT,
                reason_code="command_dispatched",
                last_command_axis=step.axis,
            )
            if runtime is not None:
                runtime.sent_commands += 1
                runtime.last_command = now
                changed_runtimes.add(runtime.room_id)
            self._diag(
                "cover_command_sent",
                room_id=room.get("id"),
                cover=cover.get("name") or entity_id,
                mode=step.rule,
                axis=step.axis,
                target=round(step.target),
                lifecycle_id=step.lifecycle_id,
            )

        await self._persist_command_planner()
        for room_id in changed_runtimes:
            runtime = self.rooms.get(room_id)
            if runtime is not None:
                await self._save_room_runtime(runtime)
        self._schedule_command_executor_timers()
        if steps:
            self._notify()
        return bool(steps)

    async def _verify_due_command_lifecycles(self) -> None:
        """Run finite target verification and surface every final outcome."""
        outcomes = self.command_planner.verify_due(now=dt_util.now())
        changed_runtimes: set[str] = set()
        for outcome in outcomes:
            entry = outcome.ledger
            room_id = entry.context.room_id if entry else None
            self._diag(
                "cover_target_verification",
                room_id=room_id,
                cover=outcome.cover_id,
                result=outcome.status.value,
                reason=outcome.reason_code,
                retry_count=entry.retry_count if entry else None,
                force=outcome.status in {
                    CommandResult.TARGET_NOT_REACHED,
                    CommandResult.FAILED,
                },
            )
            if entry:
                runtime = self._mirror_command_lifecycle(
                    entry,
                    status=outcome.status,
                    reason_code=outcome.reason_code,
                )
                if runtime is not None:
                    changed_runtimes.add(runtime.room_id)
        if outcomes:
            dispatched = await self._dispatch_due_command_steps()
        else:
            await self._persist_command_planner()
            self._schedule_command_executor_timers()
            dispatched = False
        # Verification can finish a target without producing a new due step.
        # Persist and rebuild the final trace explicitly in that path.
        for room_id in changed_runtimes:
            runtime = self.rooms.get(room_id)
            if runtime is not None:
                await self._save_room_runtime(runtime)
        if outcomes and not dispatched:
            self._notify()

    async def _record_command_feedback(self, entity_id: str, state) -> None:
        """Feed numeric cover feedback into the persisted command lifecycle."""
        context = self._find_cover_context(entity_id)
        if context is None:
            return
        _room, _sector, _layer, cover = context
        cover_id = self._cover_id(cover)
        before_result = self.command_planner.ledger_entry(cover_id)
        previous_result = before_result.result if before_result is not None else None
        entry = self.command_planner.record_feedback(
            cover_id,
            position=self._state_attribute_number(state, "current_position"),
            tilt=self._state_attribute_number(state, "current_tilt_position"),
            now=dt_util.now(),
        )
        if entry is None:
            return
        if entry.result is CommandResult.TARGET_REACHED:
            self._diag(
                "cover_target_reached",
                room_id=entry.context.room_id,
                cover=cover_id,
                lifecycle_id=entry.lifecycle_id,
            )
        lifecycle_changed = entry.result is not previous_result
        runtime = None
        if lifecycle_changed:
            runtime = self._mirror_command_lifecycle(
                entry,
                status=entry.result,
                reason_code=(
                    "target_confirmed_by_trusted_feedback"
                    if entry.result is CommandResult.TARGET_REACHED
                    else entry.failure_reason or entry.reason_code
                ),
            )
        await self._persist_command_planner()
        self._schedule_command_executor_timers()
        if runtime is not None:
            await self._save_room_runtime(runtime)
            self._notify()

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
        changed_runtimes: set[str] = set()
        for member in members:
            released = self.command_planner.release_ownership(
                self._cover_id(member), reason, now=now
            )
            if released is not None:
                if released.ledger is not None:
                    runtime = self._mirror_command_lifecycle(
                        released.ledger,
                        status=released.status,
                        reason_code=released.reason_code,
                    )
                    if runtime is not None:
                        changed_runtimes.add(runtime.room_id)
                self._diag(
                    "command_ownership_released",
                    full=True,
                    room_id=room.get("id"),
                    cover=self._cover_id(member),
                    reason=reason,
                )
        await self._persist_command_planner()
        for room_id in changed_runtimes:
            runtime = self.rooms.get(room_id)
            if runtime is not None:
                await self._save_room_runtime(runtime)
        self._schedule_command_executor_timers()
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
        result = {DEFAULT_SUN_ENTITY}
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
                    "decision_trace": runtime.decision_trace,
                    "simulation_active": runtime.simulation_active,
                    "simulation_trace": runtime.simulation_trace,
                    "day_preview": runtime.day_preview,
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
            "command_ledger": {
                cover_id: entry
                for cover_id, entry in self.command_planner.export_ledger().items()
                if cover_id in selected_cover_ids
            },
            "queued_commands": [
                step
                for step in self.command_planner.export_pending_steps()
                if str(step.get("cover_id") or "") in selected_cover_ids
            ],
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

    def room_feature_enabled(self, room_id: str, feature: str) -> bool:
        """Return whether a customer explicitly enabled one optional feature.

        Easy accepts only the shared feature subset; automation and protection
        features remain Advanced-only. The base automation is independent of
        this list so an update cannot add controls without consent.
        """
        if not self.advanced_mode and feature not in SHARED_FEATURES:
            return False
        room = self.room_config(room_id)
        features = room.get(CONF_ADVANCED_FEATURES)
        # Runtime fixtures and entries loaded before schema 17 may not yet
        # have the selection list. Preserve an already persisted calculated
        # or fixed protected zone until migration writes that list; test tools
        # still remain opt-in because no legacy room inferred that feature.
        if features is None:
            if feature == FEATURE_GLARE_PROTECTION:
                return any(
                    sector.get("protected_zones")
                    for sector in room.get("sectors", [])
                    if isinstance(sector, dict)
                )
            if feature == FEATURE_MAXIMUM_OPENING:
                return any(
                    bool(cover.get("enforce_max_open_position", False))
                    for sector in room.get("sectors", [])
                    if isinstance(sector, dict)
                    for layer in sector.get("layers", [])
                    if isinstance(layer, dict)
                    for cover in layer.get("covers", [])
                    if isinstance(cover, dict)
                )
            return False
        return str(feature) in {
            str(value) for value in features if isinstance(value, str)
        }

    def room_test_tools_enabled(self, room_id: str) -> bool:
        """Return whether non-actuating test tools may be exposed for a room."""
        return self.room_feature_enabled(room_id, FEATURE_TEST_TOOLS)

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
            await self._cancel_pending_normal_lifecycles(
                room_id,
                "room_automation_disabled",
                include_non_safety=True,
            )
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
        sun = self.hass.states.get(DEFAULT_SUN_ENTITY)
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
            await self._cancel_pending_normal_lifecycles(
                room_id,
                "room_automation_paused",
                include_non_safety=True,
            )
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
            if runtime.heat_phase in {"released_today", "release_pending"}:
                runtime.heat_phase = "inactive"
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
            "sun_on_lux": float(self.sector_value(sector_id, "sun_on_lux", 35000)),
            "sun_off_lux": float(self.sector_value(sector_id, "sun_off_lux", 30000)),
            "sun_on_delay": float(self.sector_value(sector_id, "sun_on_delay", 10)),
            "sun_off_delay": float(self.sector_value(sector_id, "sun_off_delay", 30)),
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
                # Lux delay completion is an exact event boundary in both
                # setup variants.  It must not wait for the recovery watchdog.
                await self._queue_evaluation(
                    f"sun_presence_timer:{sector_id}", immediate=True
                )
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

    def _geometry_decision_signature(
        self, room: dict[str, Any], when: datetime
    ) -> tuple[tuple[Any, ...], ...] | None:
        """Return only geometry facts that can change a physical target.

        The live Sun entity updates frequently but not necessarily precisely at
        every facade entry, elevation threshold or slat-curve step.  Astral
        gives us a deterministic look-ahead without treating a periodic poll
        as normal movement logic.  Raw azimuth/elevation are intentionally
        excluded from this signature; only a sector entry/exit or discrete
        mapped Solar target change can schedule an evaluation.
        """
        values, _source = self._virtual_solar_geometry(when)
        if values is None:
            return None
        try:
            elevation = float(values["sun_elevation"])
        except (KeyError, TypeError, ValueError):
            return None
        signature: list[tuple[Any, ...]] = []
        for sector in room.get("sectors", []):
            sector_id = str(sector.get("id") or "")
            if not sector_id or not bool(self.sector_value(sector_id, "enabled", True)):
                continue
            active = self._preview_sector_geometry_from_values(sector, values)
            signature.append(("sector", sector_id, active))
            if not active:
                continue
            for layer in sector.get("layers", []):
                layer_id = str(layer.get("id") or "")
                if not layer_id:
                    continue
                try:
                    position, tilt = self._targets(layer, MODE_SOLAR, elevation)
                except (KeyError, TypeError, ValueError):
                    # Invalid legacy targets should remain visible in the
                    # normal evaluation, but must not stop other room timers.
                    continue
                signature.append(
                    (
                        "solar_target",
                        sector_id,
                        layer_id,
                        round(float(position), 3),
                        round(float(tilt), 3) if tilt is not None else None,
                    )
                )
        return tuple(signature)

    def _next_geometry_boundary(
        self, room: dict[str, Any], now: datetime
    ) -> datetime | None:
        """Find the first sector/tilt boundary in the next 26 hours."""
        start = now
        current = self._geometry_decision_signature(room, start)
        if current is None:
            return None
        # Five-minute bracketing is a calculation-only look-ahead.  Once a
        # changed signature is found, bisection schedules the actual callback
        # to second precision; it is not a recurring movement timer.
        for offset_minutes in range(5, 26 * 60 + 5, 5):
            end = now + timedelta(minutes=offset_minutes)
            following = self._geometry_decision_signature(room, end)
            if following is None:
                return None
            if following != current:
                boundary = self._preview_refine_boundary(
                    start,
                    end,
                    lambda at, expected=current: self._geometry_decision_signature(
                        room, at
                    )
                    != expected,
                )
                return boundary or end
            start, current = end, following
        return None

    def _cancel_geometry_boundary_timer(self, room_id: str) -> None:
        unsub = self._geometry_timer_unsubs.pop(room_id, None)
        if unsub:
            unsub()

    def _schedule_geometry_boundary_timer(
        self, room: dict[str, Any], now: datetime
    ) -> None:
        """Schedule one exact next facade/tilt transition, if calculable."""
        room_id = str(room.get("id") or "")
        if not room_id:
            return
        self._cancel_geometry_boundary_timer(room_id)
        due = self._next_geometry_boundary(room, now)
        if due is None:
            return
        seconds = max(0.1, (due - dt_util.now()).total_seconds() + 0.1)

        async def timer_callback(_when) -> None:
            self._geometry_timer_unsubs.pop(room_id, None)
            trigger = f"geometry_boundary:{room_id}"
            if self.advanced_mode:
                await self._queue_evaluation(trigger, immediate=True)
            else:
                await self.async_evaluate_all(trigger)

        self._geometry_timer_unsubs[room_id] = async_call_later(
            self.hass, seconds, timer_callback
        )
        self._diag(
            "geometry_boundary_scheduled",
            full=True,
            room_id=room_id,
            due=due.isoformat(),
            seconds=seconds,
        )

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
            return None, "binary", binary_entity or None

        if source == "lux":
            lux_entity = str(sector.get("lux_sensor", "") or "")
            runtime = self.sun_runtime[sector["id"]]
            if lux_entity and runtime.current_lux is not None:
                return runtime.is_on, "lux", lux_entity
            return None, "lux", lux_entity or None
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

        sun = self.hass.states.get(DEFAULT_SUN_ENTITY)
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

    @staticmethod
    def _decision_observed_at(state) -> datetime | None:
        """Return HA state freshness when it is available to the adapter."""
        if state is None:
            return None
        for attribute in ("last_updated", "last_changed"):
            value = getattr(state, attribute, None)
            parsed = _parse_datetime(value)
            if parsed is not None:
                return parsed
        return None

    def _decision_max_age(self, room: dict[str, Any]) -> timedelta | None:
        """Read an opt-in freshness limit for dynamic live measurements.

        ``0``/empty disables aging.  Stable booleans (occupancy, permission,
        safety, night and external confirmation) intentionally do not receive
        this limit even when it is configured: an unchanged valid contact is
        not evidence that its state is stale.
        """
        raw = room.get(
            "source_stale_seconds",
            self.config.get("source_stale_seconds", DEFAULT_SOURCE_STALE_SECONDS),
        )
        try:
            seconds = float(raw)
        except (TypeError, ValueError):
            return None
        return timedelta(seconds=seconds) if seconds > 0 else None

    def _decision_live_input(
        self,
        key: str,
        entity_id: str | None,
        *,
        expected: InputKind,
        now: datetime,
        max_age: timedelta | None,
        attribute: str | None = None,
        quality: QualityState | None = None,
        details: dict[str, Any] | None = None,
    ):
        """Normalize one HA state without leaking HA types into decision.py."""
        entity = str(entity_id or "").strip()
        state = self.hass.states.get(entity) if entity else None
        raw_value = (
            state.attributes.get(attribute) if state is not None and attribute else
            state.state if state is not None else None
        )
        unit = (
            state.attributes.get("unit_of_measurement")
            if state is not None
            else None
        )
        payload = {"source": "home_assistant_state"}
        if attribute:
            payload["attribute"] = attribute
        if details:
            payload.update(details)
        normalized = normalize_input(
            key,
            raw_value=raw_value,
            entity_id=entity or None,
            expected=expected,
            unit=unit,
            observed_at=self._decision_observed_at(state),
            evaluated_at=now,
            max_age=max_age,
            quality=quality,
            configured=bool(entity),
            details=payload,
        )
        # Home Assistant exposes a temperature's source unit on the state,
        # while the configured Smart Shading thresholds are always Celsius.
        # Preserve the source raw value and unit in the trace, but make the
        # normalized snapshot value safe for the pure/virtual evaluator too.
        # Without this boundary conversion a live Fahrenheit room and its
        # simulation could select different Heat/Solar candidates.
        if key not in {"indoor_temperature", "outdoor_temperature"}:
            return normalized
        celsius = _temperature_celsius(raw_value, unit)
        if celsius is None or normalized.value is None:
            return normalized
        normalized_details = dict(normalized.details)
        normalized_details.update(
            {
                "source_unit": unit,
                "normalized_unit": "°C",
                "unit_conversion": "temperature_to_celsius",
            }
        )
        return InputValue(
            key=normalized.key,
            entity_id=normalized.entity_id,
            raw_value=normalized.raw_value,
            value=celsius,
            quality=normalized.quality,
            unit="°C",
            observed_at=normalized.observed_at,
            reason_code=normalized.reason_code,
            details=normalized_details,
        )

    @staticmethod
    def _decision_virtual_input(
        key: str,
        value: Any,
        *,
        expected: InputKind,
        now: datetime,
        quality: QualityState | None = None,
        details: dict[str, Any] | None = None,
    ):
        """Normalize a derived engine fact while retaining its provenance."""
        payload = {"source": "engine_derived"}
        if details:
            payload.update(details)
        return normalize_input(
            key,
            raw_value=value,
            expected=expected,
            observed_at=now,
            evaluated_at=now,
            quality=quality,
            configured=True,
            details=payload,
        )

    def _advanced_input_snapshot(
        self,
        room: dict[str, Any],
        now: datetime,
    ) -> InputSnapshot:
        """Create one auditable Advanced-mode snapshot from current HA state."""
        max_age = self._decision_max_age(room)
        inputs: dict[str, Any] = {}
        sun_entity = DEFAULT_SUN_ENTITY
        inputs["sun_state"] = self._decision_live_input(
            "sun_state",
            sun_entity,
            expected=InputKind.TEXT,
            now=now,
            max_age=max_age,
        )
        inputs["sun_azimuth"] = self._decision_live_input(
            "sun_azimuth",
            sun_entity,
            expected=InputKind.NUMBER,
            now=now,
            max_age=max_age,
            attribute="azimuth",
        )
        inputs["sun_elevation"] = self._decision_live_input(
            "sun_elevation",
            sun_entity,
            expected=InputKind.NUMBER,
            now=now,
            max_age=max_age,
            attribute="elevation",
        )

        for name, entity_id in (
            ("indoor_temperature", room.get("indoor_temperature")),
            ("outdoor_temperature", room.get("outdoor_temperature")),
            ("irradiance", room.get("irradiance_sensor")),
            ("cloud_cover", room.get("cloud_cover_sensor")),
        ):
            if entity_id:
                inputs[name] = self._decision_live_input(
                    name,
                    str(entity_id),
                    expected=InputKind.NUMBER,
                    now=now,
                    max_age=max_age,
                )
        for name, entity_id in (
            ("weather_permission", room.get("weather_permission")),
            ("occupancy", room.get("occupancy_sensor")),
            ("glare", room.get("glare_sensor")),
        ):
            if entity_id:
                inputs[name] = self._decision_live_input(
                    name,
                    str(entity_id),
                    expected=InputKind.BOOLEAN,
                    now=now,
                    max_age=None,
                )
        if room.get("night_enabled") and room.get("night_source", "entity") == "entity":
            entity_id = str(room.get("night_entity") or "")
            if entity_id:
                inputs["night_source"] = self._decision_live_input(
                    "night_source",
                    entity_id,
                    expected=InputKind.BOOLEAN,
                    now=now,
                    max_age=None,
                )
        for index, entity_id in enumerate(room.get("safety_blockers", [])):
            entity = str(entity_id or "")
            if entity:
                key = f"safety:{index}:{entity}"
                inputs[key] = self._decision_live_input(
                    key,
                    entity,
                    expected=InputKind.BOOLEAN,
                    now=now,
                    max_age=None,
                )

        runtime = self.rooms.get(str(room.get("id") or ""))
        inputs["schedule_active"] = self._decision_virtual_input(
            "schedule_active",
            runtime.schedule_active if runtime is not None else None,
            expected=InputKind.BOOLEAN,
            now=now,
        )
        inputs["room_pause_active"] = self._decision_virtual_input(
            "room_pause_active",
            self._pause_active(runtime, now) if runtime is not None else None,
            expected=InputKind.BOOLEAN,
            now=now,
        )

        for sector in room.get("sectors", []):
            sector_id = str(sector.get("id") or "")
            if not sector_id:
                continue
            sector_runtime = self.sun_runtime.get(sector_id)
            source = sun_source_for_sector(sector, advanced=True)
            key = f"sector:{sector_id}:sun_confirmation"
            if source == "external":
                inputs[key] = self._decision_live_input(
                    key,
                    str(sector.get(CONF_SUN_PRESENCE_ENTITY) or ""),
                    expected=InputKind.BOOLEAN,
                    now=now,
                    max_age=None,
                    details={"sun_source": source},
                )
            elif source == "lux":
                pending = (
                    QualityState.PENDING
                    if sector_runtime is not None
                    and sector_runtime.pending_target is not None
                    else None
                )
                inputs[key] = self._decision_live_input(
                    key,
                    str(sector.get("lux_sensor") or ""),
                    expected=InputKind.NUMBER,
                    now=now,
                    max_age=max_age,
                    quality=pending,
                    details={"sun_source": source},
                )
            else:
                inputs[key] = self._decision_virtual_input(
                    key,
                    (
                        sector_runtime.geometry_active
                        if sector_runtime is not None
                        else None
                    ),
                    expected=InputKind.BOOLEAN,
                    now=now,
                    details={"sun_source": source},
                )
            inputs[f"sector:{sector_id}:enabled"] = self._decision_virtual_input(
                f"sector:{sector_id}:enabled",
                bool(self.sector_value(sector_id, "enabled", True)),
                expected=InputKind.BOOLEAN,
                now=now,
            )

        return InputSnapshot(
            evaluated_at=now,
            inputs=inputs,
            details={
                "room_id": str(room.get("id") or ""),
                "trigger": self._current_trigger,
                "advanced_mode": True,
            },
        )

    @staticmethod
    def _sector_facade_azimuth(sector: dict[str, Any]) -> float | None:
        """Return an outward facade normal, including wrap-around sectors."""
        explicit = parse_numeric_value(sector.get("facade_azimuth"))
        if explicit is not None:
            return explicit % 360.0
        start = parse_numeric_value(sector.get("azimuth_start"))
        end = parse_numeric_value(sector.get("azimuth_end"))
        if start is None or end is None:
            return None
        return (start + ((end - start) % 360.0) / 2.0) % 360.0

    def _advanced_protected_zones(
        self,
        sector: dict[str, Any],
        layer: dict[str, Any] | None = None,
    ) -> tuple[ProtectedZone, ...]:
        """Adapt persisted Advanced-only zone dictionaries to pure objects."""
        zones: list[ProtectedZone] = []
        profile = str(layer.get("profile", DEVICE_VENETIAN)) if layer else None
        supports_tilt = profile in {DEVICE_VENETIAN, DEVICE_VERTICAL}
        for values in sector.get("protected_zones", []):
            if not isinstance(values, dict):
                continue
            try:
                zone = ProtectedZone.from_config(
                    values, sector_id=str(sector.get("id") or "")
                )
                if layer is not None and not supports_tilt and zone.target_tilt is not None:
                    # A protected zone may narrow position for every profile,
                    # but only real slat profiles may receive a tilt command.
                    # Keep the ignored capability visible in context details.
                    zone = replace(zone, target_tilt=None)
                zones.append(zone)
            except (TypeError, ValueError):
                # A malformed legacy record must not stop ordinary solar
                # shading.  Config-flow validation prevents new records from
                # reaching here; a diagnostic input remains available in the
                # room trace through the persisted configuration export.
                _LOGGER.warning("Ignoring malformed protected zone in sector %s", sector.get("id"))
        return tuple(zones)

    @staticmethod
    def _protected_zone_ignored_tilt_ids(
        sector: dict[str, Any], layer: dict[str, Any] | None
    ) -> tuple[str, ...]:
        """Expose zone tilt targets omitted for a non-slat layer profile."""
        if layer is None or str(layer.get("profile", DEVICE_VENETIAN)) in {
            DEVICE_VENETIAN,
            DEVICE_VERTICAL,
        }:
            return ()
        return tuple(
            str(values.get("id") or values.get("zone_id") or "")
            for values in sector.get("protected_zones", [])
            if isinstance(values, dict)
            and values.get("target_tilt") is not None
            and str(values.get("id") or values.get("zone_id") or "")
        )

    def _decision_targets_for_layer(
        self,
        layer: dict[str, Any],
        elevation: float | None,
    ) -> dict[str, DecisionTarget]:
        """Map established profile targets into the pure decision contract."""
        safe_elevation = elevation if elevation is not None else 0.0
        result: dict[str, DecisionTarget] = {}
        for mode in (
            MODE_SAFETY,
            MODE_NIGHT,
            MODE_HEAT,
            MODE_SOLAR,
            MODE_COMFORT,
            MODE_OPEN,
        ):
            position, tilt = self._targets(layer, mode, safe_elevation)
            result[mode] = DecisionTarget(position=position, tilt=tilt)
        return result

    def _decision_required_inputs(
        self,
        room: dict[str, Any],
        sector: dict[str, Any] | None,
        mode: str | bool,
        *,
        glare_active: bool = False,
    ) -> tuple[str, ...]:
        """Name only inputs that can affect the requested daytime action."""
        normal_mode_active = (
            mode
            if isinstance(mode, bool)
            else mode in {MODE_SOLAR, MODE_COMFORT}
        )
        if not normal_mode_active and not glare_active:
            return ()
        keys = ["sun_state", "sun_azimuth", "sun_elevation"]
        if sector is not None:
            sector_id = str(sector.get("id") or "")
            if sector_id:
                keys.append(f"sector:{sector_id}:sun_confirmation")
        if glare_active and not normal_mode_active:
            return tuple(dict.fromkeys(keys))
        # These are only health gates when configured. Their actual threshold
        # result remains represented by the effective mode passed to the
        # pipeline, preserving established hysteresis and weather semantics.
        for key, entity in (
            ("indoor_temperature", room.get("indoor_temperature")),
            ("outdoor_temperature", room.get("outdoor_temperature")),
            ("irradiance", room.get("irradiance_sensor")),
            ("cloud_cover", room.get("cloud_cover_sensor")),
            ("weather_permission", room.get("weather_permission")),
            ("occupancy", room.get("occupancy_sensor")),
            ("glare", room.get("glare_sensor")),
        ):
            if entity:
                keys.append(key)
        return tuple(dict.fromkeys(keys))

    def _advanced_decision_context(
        self,
        room: dict[str, Any],
        runtime: RoomRuntime,
        now: datetime,
        *,
        mode: str | None = None,
        facts: dict[str, bool] | None = None,
        snapshot: InputSnapshot | None = None,
        sector: dict[str, Any] | None = None,
        layer: dict[str, Any] | None = None,
        cover_entity: str | None = None,
        local_pause_active: bool = False,
    ) -> DecisionContext:
        """Adapt the established Advanced evaluation to one pure context.

        The existing Advanced condition calculators remain the source of
        profile-specific facts and hysteresis.  Unlike the old trace adapter,
        callers may pass *all* currently true facts and let the pipeline pick
        the winning mode.  ``mode`` remains a compatibility shorthand for
        older call sites that intentionally describe one fact.
        """
        if facts is None:
            selected_mode = mode or MODE_IDLE
            resolved_facts = {
                "safety_active": selected_mode == MODE_SAFETY,
                "manual_override_active": selected_mode == MODE_DISABLED,
                "room_pause_active": selected_mode == MODE_PAUSED,
                "safety_source_hold_active": False,
                "night_active": selected_mode == MODE_NIGHT,
                "night_source_hold_active": False,
                "heat_active": selected_mode == MODE_HEAT,
                "schedule_hold_active": False,
                "glare_allowed": selected_mode == MODE_GLARE,
                "solar_active": selected_mode == MODE_SOLAR,
                "comfort_active": selected_mode == MODE_COMFORT,
                "open_active": selected_mode == MODE_OPEN,
                "idle_active": selected_mode == MODE_IDLE,
            }
        else:
            resolved_facts = {
                key: bool(value) for key, value in dict(facts).items()
            }
            selected_mode = mode
        snapshot = snapshot or self._advanced_input_snapshot(room, now)
        azimuth_value = snapshot.get("sun_azimuth").value
        elevation_value = snapshot.get("sun_elevation").value
        azimuth = float(azimuth_value) if isinstance(azimuth_value, (int, float)) else None
        elevation = float(elevation_value) if isinstance(elevation_value, (int, float)) else None
        sector_id = str(sector.get("id") or "") if sector else None
        group_id = str(layer.get("id") or "") if layer else None
        sector_runtime = self.sun_runtime.get(sector_id or "")
        targets = self._decision_targets_for_layer(layer, elevation) if layer else {}
        geometry = None
        if sector is not None:
            geometry = SunGeometry(
                elevation_degrees=elevation,
                azimuth_degrees=azimuth,
                facade_azimuth_degrees=self._sector_facade_azimuth(sector),
                # Keep malformed legacy geometry visible to the pure validator
                # instead of making a runtime cast abort ordinary shading.
                window_lower_height_m=sector.get("window_lower_height_m", 0.0),
                window_upper_height_m=sector.get("window_upper_height_m", 2.4),
                direct_sun=bool(
                    resolved_facts.get("solar_active")
                    or resolved_facts.get("comfort_active")
                    or (sector_runtime and sector_runtime.effective_active)
                ),
            )
        return DecisionContext(
            snapshot=snapshot,
            safety_active=bool(resolved_facts.get("safety_active")),
            manual_override_active=bool(
                resolved_facts.get("manual_override_active")
            ),
            room_pause_active=bool(resolved_facts.get("room_pause_active")),
            local_pause_active=local_pause_active,
            safety_source_hold_active=bool(
                resolved_facts.get("safety_source_hold_active")
            ),
            night_active=bool(resolved_facts.get("night_active")),
            night_source_hold_active=bool(
                resolved_facts.get("night_source_hold_active")
            ),
            heat_active=bool(resolved_facts.get("heat_active")),
            schedule_hold_active=bool(
                resolved_facts.get("schedule_hold_active")
            ),
            glare_allowed=bool(resolved_facts.get("glare_allowed")),
            solar_active=bool(resolved_facts.get("solar_active")),
            comfort_active=bool(resolved_facts.get("comfort_active")),
            open_active=bool(resolved_facts.get("open_active")),
            idle_active=bool(resolved_facts.get("idle_active")),
            normal_input_keys=self._decision_required_inputs(
                room,
                sector,
                bool(resolved_facts.get("solar_active"))
                or bool(resolved_facts.get("comfort_active")),
                glare_active=bool(resolved_facts.get("glare_allowed")),
            ),
            targets=targets,
            sector_id=sector_id,
            group_id=group_id,
            cover_entity=cover_entity,
            sun_geometry=geometry,
            protected_zones=(
                self._advanced_protected_zones(sector, layer)
                if (
                    sector is not None
                    and self.room_feature_enabled(str(room.get("id") or ""), FEATURE_GLARE_PROTECTION)
                )
                else ()
            ),
            details={
                "effective_runtime_mode": selected_mode,
                "decision_facts": resolved_facts,
                "runtime_reason": runtime.reason,
                "room_id": runtime.room_id,
                "sector_id": sector_id,
                "layer_id": group_id,
                "cover_entity": cover_entity,
                "protected_zone_ignored_tilt_ids": (
                    self._protected_zone_ignored_tilt_ids(sector, layer)
                    if sector is not None
                    else ()
                ),
            },
        )

    def _resolve_advanced_decision(
        self,
        room: dict[str, Any],
        runtime: RoomRuntime,
        now: datetime,
        *,
        facts: dict[str, bool],
        snapshot: InputSnapshot | None = None,
        sector: dict[str, Any] | None = None,
        layer: dict[str, Any] | None = None,
        cover_entity: str | None = None,
        local_pause_active: bool = False,
    ):
        """Resolve live Advanced facts once through the production pipeline."""
        return self.decision_pipeline.evaluate(
            self._advanced_decision_context(
                room,
                runtime,
                now,
                facts=facts,
                snapshot=snapshot,
                sector=sector,
                layer=layer,
                cover_entity=cover_entity,
                local_pause_active=local_pause_active,
            )
        )

    @staticmethod
    def _advanced_decision_facts(**active: bool) -> dict[str, bool]:
        """Build a complete, explicit factual contract for one resolver run."""
        facts = {
            "safety_active": False,
            "manual_override_active": False,
            "room_pause_active": False,
            "safety_source_hold_active": False,
            "night_source_hold_active": False,
            "night_active": False,
            "heat_active": False,
            "schedule_hold_active": False,
            "glare_allowed": False,
            "solar_active": False,
            "comfort_active": False,
            "open_active": False,
            "idle_active": False,
        }
        facts.update({key: bool(value) for key, value in active.items()})
        return facts

    @staticmethod
    def _virtual_input_bool(snapshot: InputSnapshot, key: str) -> bool | None:
        """Read a valid Boolean from a virtual snapshot without HA access."""
        item = snapshot.get(key)
        return bool(item.value) if item.valid and isinstance(item.value, bool) else None

    @staticmethod
    def _virtual_input_number(snapshot: InputSnapshot, key: str) -> float | None:
        """Read a finite normalized number from a virtual snapshot."""
        item = snapshot.get(key)
        if not isinstance(item.value, (int, float)) or isinstance(item.value, bool):
            return None
        return float(item.value)

    def _virtual_room_pause_active(
        self, runtime: RoomRuntime, when: datetime
    ) -> bool:
        """Read pause state at a virtual instant without mutating RoomRuntime."""
        if runtime.pause_mode in {PAUSE_MANUAL, PAUSE_NEXT_NIGHT_END}:
            return True
        return bool(
            runtime.pause_mode in {PAUSE_NEXT_SUNRISE, PAUSE_NEXT_SUNSET, PAUSE_TIMED}
            and runtime.pause_until
            and runtime.pause_until > when
        )

    def _virtual_sector_geometry(
        self, snapshot: InputSnapshot, sector: dict[str, Any]
    ) -> bool:
        """Derive facade geometry from virtual sun inputs."""
        sun_state = snapshot.get("sun_state")
        azimuth = self._virtual_input_number(snapshot, "sun_azimuth")
        elevation = self._virtual_input_number(snapshot, "sun_elevation")
        if (
            not sun_state.valid
            or str(sun_state.value).lower() != "above_horizon"
            or azimuth is None
            or elevation is None
        ):
            return False
        try:
            return bool(
                azimuth_inside(
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
        except (KeyError, TypeError, ValueError):
            return False

    @staticmethod
    def _virtual_trajectory_geometry(
        trajectory: Any,
        when: datetime,
    ) -> dict[str, float | str] | None:
        """Interpolate an explicitly supplied virtual sun trajectory.

        A trajectory is deliberately a tiny data contract rather than a new
        weather source: each row may contain ``at`` (ISO datetime) or ``time``
        (``HH:MM[:SS]`` for the selected day), plus ``azimuth``/``elevation``
        or their stable ``sun_``-prefixed counterparts.  This keeps developer
        scenarios deterministic even on a test host without Astral.
        """
        rows = trajectory if isinstance(trajectory, (list, tuple)) else ()
        normalized: list[tuple[datetime, float, float]] = []
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            raw_at = raw.get("at", raw.get("evaluated_at"))
            if raw_at is None and raw.get("time") is not None:
                raw_at = f"{when.date().isoformat()}T{raw.get('time')}"
            at = _parse_datetime(raw_at)
            if at is None:
                continue
            if at.tzinfo is None and when.tzinfo is not None:
                at = at.replace(tzinfo=when.tzinfo)
            azimuth = parse_numeric_value(raw.get("sun_azimuth", raw.get("azimuth")))
            elevation = parse_numeric_value(
                raw.get("sun_elevation", raw.get("elevation"))
            )
            if azimuth is None or elevation is None:
                continue
            normalized.append((at, float(azimuth) % 360.0, float(elevation)))
        if not normalized:
            return None
        normalized.sort(key=lambda row: row[0])
        if when <= normalized[0][0]:
            _at, azimuth, elevation = normalized[0]
        elif when >= normalized[-1][0]:
            _at, azimuth, elevation = normalized[-1]
        else:
            previous, following = next(
                (left, right)
                for left, right in zip(normalized, normalized[1:])
                if left[0] <= when <= right[0]
            )
            duration = (following[0] - previous[0]).total_seconds()
            ratio = (
                (when - previous[0]).total_seconds() / duration
                if duration > 0
                else 0.0
            )
            # Interpolate through the shortest azimuth direction around north
            # instead of jumping across 0°/360° in supplied trajectories.
            azimuth_delta = (following[1] - previous[1] + 540.0) % 360.0 - 180.0
            azimuth = (previous[1] + azimuth_delta * ratio) % 360.0
            elevation = previous[2] + (following[2] - previous[2]) * ratio
        return {
            "sun_state": "above_horizon" if elevation > 0.0 else "below_horizon",
            "sun_azimuth": azimuth,
            "sun_elevation": elevation,
        }

    def _virtual_solar_geometry(
        self,
        when: datetime,
        *,
        trajectory: Any = None,
    ) -> tuple[dict[str, float | str] | None, str]:
        """Return deterministic virtual solar inputs without consulting ``sun.sun``.

        Home Assistant bundles Astral, but its import stays lazy so the pure
        engine fixture and installations with a damaged optional dependency
        continue to start.  A caller-supplied trajectory takes precedence for
        reproducible developer scenarios.  ``None`` explicitly signals that
        callers must retain the live snapshot as a clearly marked fallback;
        it never invents a fake sunny day.
        """
        supplied = self._virtual_trajectory_geometry(trajectory, when)
        if supplied is not None:
            return supplied, "trajectory"
        latitude = parse_numeric_value(getattr(self.hass.config, "latitude", None))
        longitude = parse_numeric_value(getattr(self.hass.config, "longitude", None))
        if latitude is None or longitude is None:
            return None, "unavailable_missing_location"
        if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
            return None, "unavailable_invalid_location"
        try:
            # Import only while a virtual day is requested.  The production
            # runtime remains driven by Home Assistant's live Sun entity.
            from astral import Observer
            from astral.sun import azimuth as astral_azimuth
            from astral.sun import elevation as astral_elevation
        except (ImportError, ModuleNotFoundError):
            return None, "unavailable_astral"
        try:
            observer = Observer(latitude=latitude, longitude=longitude)
            instant = when
            if instant.tzinfo is None:
                instant = instant.replace(tzinfo=dt_util.now().tzinfo)
            azimuth = float(astral_azimuth(observer, instant)) % 360.0
            elevation = float(astral_elevation(observer, instant))
            if not math.isfinite(azimuth) or not math.isfinite(elevation):
                raise ValueError("non-finite Astral solar coordinate")
        except (ArithmeticError, TypeError, ValueError):
            return None, "unavailable_astral_calculation"
        return {
            "sun_state": "above_horizon" if elevation > 0.0 else "below_horizon",
            "sun_azimuth": azimuth,
            "sun_elevation": elevation,
        }, "astral"

    def _virtual_solar_events(
        self, when: datetime) -> tuple[datetime | None, datetime | None]:
        """Return virtual sunrise/sunset for a date, when Astral is available."""
        latitude = parse_numeric_value(getattr(self.hass.config, "latitude", None))
        longitude = parse_numeric_value(getattr(self.hass.config, "longitude", None))
        if (
            latitude is None
            or longitude is None
            or not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0)
        ):
            return None, None
        try:
            from astral import Observer
            from astral.sun import sun as astral_sun
        except (ImportError, ModuleNotFoundError):
            return None, None
        try:
            observer = Observer(latitude=latitude, longitude=longitude)
            values = astral_sun(observer, date=when.date(), tzinfo=when.tzinfo)
            sunrise = _parse_datetime(values.get("sunrise"))
            sunset = _parse_datetime(values.get("sunset"))
            if sunrise and sunrise.tzinfo is None and when.tzinfo is not None:
                sunrise = sunrise.replace(tzinfo=when.tzinfo)
            if sunset and sunset.tzinfo is None and when.tzinfo is not None:
                sunset = sunset.replace(tzinfo=when.tzinfo)
            return sunrise, sunset
        except (ArithmeticError, KeyError, TypeError, ValueError):
            # Polar-day/night and an unavailable optional dependency are both
            # honest "no event" states for a preview, not reasons to fake one.
            return None, None

    def _virtual_sun_night_status(
        self,
        room: dict[str, Any],
        when: datetime,
        snapshot: InputSnapshot,
    ) -> tuple[bool, bool]:
        """Evaluate a sun-based Night window from the same virtual geometry.

        ``_night_status`` deliberately reads the live Sun integration for
        normal automation.  Reusing it for a different preview date would
        move today's rising/setting timestamps onto the requested date.  This
        small virtual counterpart instead uses Astral events when possible,
        falling back to the supplied virtual horizon state without inventing a
        transition.
        """
        sun_state = snapshot.get("sun_state")
        if not sun_state.valid:
            return False, True
        fallback_active = str(sun_state.value).lower() != "above_horizon"
        yesterday_rise, yesterday_set = self._virtual_solar_events(
            when - timedelta(days=1)
        )
        today_rise, today_set = self._virtual_solar_events(when)
        tomorrow_rise, _tomorrow_set = self._virtual_solar_events(
            when + timedelta(days=1)
        )
        if not all((yesterday_set, today_rise, today_set, tomorrow_rise)):
            return fallback_active, False
        start_offset = timedelta(
            minutes=float(room.get("night_start_offset_minutes", 0))
        )
        end_offset = timedelta(
            minutes=float(room.get("night_end_offset_minutes", 0))
        )
        events = sorted(
            (
                (yesterday_set + start_offset, True),
                (today_rise + end_offset, False),
                (today_set + start_offset, True),
                (tomorrow_rise + end_offset, False),
            ),
            key=lambda value: value[0],
        )
        previous = [event for event in events if event[0] <= when]
        return (previous[-1][1] if previous else fallback_active), False

    def _advanced_virtual_snapshot(
        self,
        room: dict[str, Any],
        runtime: RoomRuntime,
        when: datetime,
        overrides: dict[str, Any] | None = None,
        *,
        virtual_solar: bool = False,
        trajectory: Any = None,
    ) -> InputSnapshot:
        """Build one virtual snapshot whose derived facts follow ``when``.

        Simulations used to replace raw values after a live mode had already
        been selected.  Recomputing schedule, pause and geometry here gives
        the exact same factual resolver a genuinely virtual input boundary.
        """
        supplied = dict(overrides or {})
        supplied_trajectory = trajectory
        if supplied_trajectory is None:
            supplied_trajectory = supplied.pop(
                "sun_trajectory", supplied.pop("solar_trajectory", None)
            )
        solar_values: dict[str, float | str] | None = None
        solar_source = "live_snapshot"
        if virtual_solar:
            solar_values, solar_source = self._virtual_solar_geometry(
                when,
                trajectory=supplied_trajectory,
            )
        # Short developer-facing aliases fan out to the stable trace keys.
        # Explicit scoped keys always win, so multi-sector simulations remain
        # deterministic.
        if "safety" in supplied:
            for index, entity in enumerate(room.get("safety_blockers", [])):
                entity_id = str(entity or "")
                if entity_id:
                    supplied.setdefault(f"safety:{index}:{entity_id}", supplied["safety"])
        for sector in room.get("sectors", []):
            sector_id = str(sector.get("id") or "")
            if not sector_id:
                continue
            key = f"sector:{sector_id}:sun_confirmation"
            source = sun_source_for_sector(sector, advanced=True)
            if source == "lux" and "lux" in supplied:
                supplied.setdefault(key, supplied["lux"])
            elif source == "external":
                for alias in ("sun_confirmation", "sun_presence", "external_confirmation"):
                    if alias in supplied:
                        supplied.setdefault(key, supplied[alias])
                        break
        snapshot = self._advanced_input_snapshot(room, when)
        if supplied:
            snapshot = snapshot.with_overrides(supplied)
        inputs = dict(snapshot.inputs)
        if solar_values is not None:
            for key, value in solar_values.items():
                # A developer-provided coordinate is authoritative.  Astral
                # fills only the missing virtual coordinates around it.
                if key in supplied:
                    continue
                inputs[key] = self._decision_virtual_input(
                    key,
                    value,
                    expected=(InputKind.TEXT if key == "sun_state" else InputKind.NUMBER),
                    now=when,
                    details={
                        "source": f"virtual_solar_{solar_source}",
                        "virtual_solar_source": solar_source,
                    },
                )
        if "schedule_active" not in supplied:
            inputs["schedule_active"] = self._decision_virtual_input(
                "schedule_active",
                self._schedule_active_at(room, when),
                expected=InputKind.BOOLEAN,
                now=when,
                details={"source": "virtual_schedule"},
            )
        if "room_pause_active" not in supplied:
            inputs["room_pause_active"] = self._decision_virtual_input(
                "room_pause_active",
                self._virtual_room_pause_active(runtime, when),
                expected=InputKind.BOOLEAN,
                now=when,
                details={"source": "virtual_pause"},
            )
        provisional = InputSnapshot(
            evaluated_at=when,
            inputs=inputs,
            details={
                **dict(snapshot.details),
                "virtual": True,
                "virtual_solar_requested": virtual_solar,
                "virtual_solar_source": solar_source,
                "virtual_solar_available": solar_values is not None,
            },
        )
        for sector in room.get("sectors", []):
            sector_id = str(sector.get("id") or "")
            key = f"sector:{sector_id}:sun_confirmation"
            if (
                sector_id
                and sun_source_for_sector(sector, advanced=True) == "geometry"
                and key not in supplied
            ):
                inputs[key] = self._decision_virtual_input(
                    key,
                    self._virtual_sector_geometry(provisional, sector),
                    expected=InputKind.BOOLEAN,
                    now=when,
                    details={"source": "virtual_geometry"},
                )
        return InputSnapshot(
            evaluated_at=when,
            inputs=inputs,
            details={
                **dict(snapshot.details),
                "virtual": True,
                "virtual_solar_requested": virtual_solar,
                "virtual_solar_source": solar_source,
                "virtual_solar_available": solar_values is not None,
            },
        )

    @staticmethod
    def _virtual_when(overrides: dict[str, Any], fallback: datetime) -> datetime:
        """Extract an optional virtual timestamp without leaking it as input."""
        raw = overrides.pop("at", overrides.pop("evaluated_at", None))
        if raw is None and overrides.get("date") is not None:
            date_value = str(overrides.pop("date"))
            time_value = str(overrides.pop("time", "00:00:00"))
            raw = f"{date_value}T{time_value}"
        parsed = _parse_datetime(raw)
        if parsed is None:
            return fallback
        if parsed.tzinfo is None and fallback.tzinfo is not None:
            return parsed.replace(tzinfo=fallback.tzinfo)
        return parsed

    def _virtual_sector_sun_state(
        self,
        sector: dict[str, Any],
        snapshot: InputSnapshot,
    ) -> tuple[bool, bool]:
        """Return ``(direct_sun, source_unavailable)`` from virtual inputs."""
        sector_id = str(sector.get("id") or "")
        if not sector_id or not bool(self.sector_value(sector_id, "enabled", True)):
            return False, False
        geometry = self._virtual_sector_geometry(snapshot, sector)
        if not geometry:
            return False, False
        source = sun_source_for_sector(sector, advanced=True)
        key = f"sector:{sector_id}:sun_confirmation"
        source_input = snapshot.get(key)
        if source == "geometry":
            return True, False
        if source == "external":
            confirmation = self._virtual_input_bool(snapshot, key)
            return bool(confirmation), confirmation is None
        # Lux uses the established hysteresis thresholds but deliberately does
        # not mutate the live debounce runtime while a user explores values.
        lux = self._virtual_input_number(snapshot, key)
        runtime = self.sun_runtime.get(sector_id)
        if source_input.quality is QualityState.PENDING and runtime is not None:
            # Production keeps the last confirmed Lux state until its debounce
            # boundary.  A virtual replay mirrors that fact while the quality
            # gate still prevents a fresh normal command.
            return bool(runtime.is_on), False
        if lux is None:
            return False, source_input.quality is not QualityState.VALID
        settings = self._sun_settings(sector_id)
        threshold = (
            min(settings["sun_on_lux"], settings["sun_off_lux"])
            if runtime is not None and runtime.is_on
            else max(settings["sun_on_lux"], settings["sun_off_lux"])
        )
        return lux >= threshold, False

    def _advanced_virtual_facts(
        self,
        room: dict[str, Any],
        runtime: RoomRuntime,
        sector: dict[str, Any],
        snapshot: InputSnapshot,
        when: datetime,
    ) -> dict[str, bool]:
        """Derive production candidate facts from a live or virtual snapshot."""
        schedule_value = self._virtual_input_bool(snapshot, "schedule_active")
        schedule_active = (
            self._schedule_active_at(room, when)
            if schedule_value is None
            else schedule_value
        )
        pause_value = self._virtual_input_bool(snapshot, "room_pause_active")
        pause_active = (
            self._virtual_room_pause_active(runtime, when)
            if pause_value is None
            else pause_value
        )
        safety_active = any(
            self._virtual_input_bool(snapshot, f"safety:{index}:{entity}") is True
            for index, entity in enumerate(room.get("safety_blockers", []))
            if str(entity or "")
        )

        night_active = False
        night_blocked = False
        if room.get("night_enabled", False):
            if room.get("night_source", "entity") == "entity":
                _active, blocked, _reason, _state, _next = self._night_status(room, when)
                night_active, night_blocked = _active, blocked
                night_value = self._virtual_input_bool(snapshot, "night_source")
                if night_value is not None:
                    night_active, night_blocked = night_value, False
                elif snapshot.get("night_source").quality is not QualityState.NOT_CONFIGURED:
                    night_active, night_blocked = False, True
            else:
                if snapshot.details.get("virtual_solar_requested"):
                    night_active, night_blocked = self._virtual_sun_night_status(
                        room, when, snapshot
                    )
                else:
                    _active, blocked, _reason, _state, _next = self._night_status(
                        room, when
                    )
                    night_active, night_blocked = _active, blocked

        weather_tests: list[bool] = []
        if room.get("irradiance_sensor"):
            irradiance = self._virtual_input_number(snapshot, "irradiance")
            weather_tests.append(
                irradiance is not None
                and irradiance
                >= float(self.room_value(room["id"], "irradiance_minimum", 150.0))
            )
        if room.get("cloud_cover_sensor"):
            cloud = self._virtual_input_number(snapshot, "cloud_cover")
            weather_tests.append(
                cloud is not None
                and cloud
                <= float(self.room_value(room["id"], "cloud_cover_maximum", 85.0))
            )
        if room.get("weather_permission"):
            weather_tests.append(
                self._virtual_input_bool(snapshot, "weather_permission") is True
            )
        weather_pass = (
            True
            if not weather_tests
            else any(weather_tests)
            if room.get("weather_logic", "all") == "any"
            else all(weather_tests)
        )
        indoor = self._virtual_input_number(snapshot, "indoor_temperature")
        outdoor = self._virtual_input_number(snapshot, "outdoor_temperature")
        indoor_entity = str(room.get("indoor_temperature") or "")
        outdoor_entity = str(room.get("outdoor_temperature") or "")
        outdoor_ok = not outdoor_entity or (
            outdoor is not None
            and outdoor
            >= float(self.room_value(room["id"], "outdoor_minimum", 18.0))
        )
        all_sector_sun = any(
            self._virtual_sector_sun_state(item, snapshot)[0]
            for item in room.get("sectors", [])
        )
        heat_conditions = bool(
            indoor is not None
            and (not room.get("heat_requires_sun", True) or all_sector_sun)
            and schedule_active
            and (bool(room.get("heat_ignores_weather", True)) or weather_pass)
            and outdoor_ok
        )
        live_day = when.date() == dt_util.now().date()
        heat_active = bool(
            (runtime.heat_active if live_day else False)
            or (
                not (runtime.finished_today if live_day else False)
                and heat_conditions
                and indoor is not None
                and indoor
                >= float(self.room_value(room["id"], "heat_temperature", 27.0))
            )
        )
        heat_active = heat_active and not self._evening_release_reached(
            room, when
        )

        sector_sun, source_unavailable = self._virtual_sector_sun_state(
            sector, snapshot
        )
        occupied = (
            not room.get("occupancy_sensor")
            or self._virtual_input_bool(snapshot, "occupancy") is True
        )
        glare = bool(room.get("glare_sensor")) and (
            self._virtual_input_bool(snapshot, "glare") is True
        )
        comfort_allowed = occupied or not room.get("comfort_requires_occupancy", False)
        solar_active = False
        comfort_active = False
        open_active = False
        idle_active = False
        if source_unavailable:
            idle_active = True
        elif sector_sun:
            if self._venetian_only(room):
                normal_temperature = float(
                    self.room_value(room["id"], "normal_shading_temperature", 23.5)
                )
                shading_active = runtime.shading_active
                if not indoor_entity:
                    shading_active = True
                elif indoor is not None:
                    reopen = float(self.room_value(room["id"], "reopen_temperature", 22.0))
                    if shading_active and indoor < reopen:
                        shading_active = False
                    elif not shading_active and indoor >= normal_temperature:
                        shading_active = True
                solar_active = bool(
                    weather_pass and outdoor_ok and comfort_allowed and (glare or shading_active)
                )
                idle_active = not solar_active
            else:
                solar_active = bool(
                    indoor is not None
                    and indoor >= float(self.room_value(room["id"], "solar_temperature", 25.5))
                    and weather_pass
                    and outdoor_ok
                )
                comfort_active = bool(
                    not solar_active
                    and comfort_allowed
                    and weather_pass
                    and (
                        glare
                        or not indoor_entity
                        or (
                            indoor is not None
                            and indoor
                            >= float(
                                self.room_value(
                                    room["id"], "comfort_temperature", 23.5
                                )
                            )
                        )
                    )
                )
                idle_active = not (solar_active or comfort_active)
        else:
            open_active = True

        geometry = self._virtual_sector_geometry(snapshot, sector)
        morning_handover = bool(
            runtime.night_morning_handover_pending
            and geometry
            and not (solar_active or comfort_active)
        )
        if morning_handover:
            solar_active = comfort_active = False
            holding = bool(
                runtime.night_morning_hold_until
                and runtime.night_morning_hold_until > when
            )
            open_active = not holding
            idle_active = holding

        if not schedule_active and not heat_active:
            behavior = room.get("outside_schedule_behavior", OUTSIDE_OPEN)
            solar_active = comfort_active = False
            open_active = behavior == OUTSIDE_OPEN
            idle_active = behavior != OUTSIDE_OPEN
        return self._advanced_decision_facts(
            safety_active=safety_active,
            manual_override_active=not runtime.enabled,
            room_pause_active=(
                pause_active and not (bool(room.get("heat_during_pause", False)) and heat_active)
            ),
            night_source_hold_active=night_blocked,
            night_active=night_active,
            heat_active=heat_active,
            schedule_hold_active=(not schedule_active and not heat_active and not open_active),
            glare_allowed=bool(schedule_active and sector_sun and not source_unavailable),
            solar_active=solar_active,
            comfort_active=comfort_active,
            open_active=open_active,
            idle_active=idle_active,
        )

    def _advanced_room_candidate_facts(
        self,
        room: dict[str, Any],
        runtime: RoomRuntime,
        snapshot: InputSnapshot,
        when: datetime,
    ) -> dict[str, bool]:
        """Aggregate normal candidates before a high-priority early return.

        Safety/Night/Pause are allowed to stop the physical executor early,
        but they must not erase factual Solar, Comfort or Open candidates from
        the decision trace.  This is deliberately read-only: the regular
        sector loop remains responsible for changing hysteresis/runtime state
        once no higher-priority winner blocks it.
        """
        aggregate = self._advanced_decision_facts()
        has_enabled_sector = False
        for sector in room.get("sectors", []):
            sector_id = str(sector.get("id") or "")
            if not sector_id or not bool(self.sector_value(sector_id, "enabled", True)):
                continue
            has_enabled_sector = True
            facts = self._advanced_virtual_facts(
                room,
                runtime,
                sector,
                snapshot,
                when,
            )
            # These candidates are orthogonal facts.  Keeping every true one
            # lets the resolver render, for example, "Solar: rejected by
            # Safety" instead of incorrectly reporting Solar as inactive.
            for key in (
                "night_source_hold_active",
                "night_active",
                "heat_active",
                "schedule_hold_active",
                "glare_allowed",
                "solar_active",
                "comfort_active",
                "open_active",
                "idle_active",
            ):
                aggregate[key] = bool(aggregate.get(key) or facts.get(key))
        if not has_enabled_sector:
            aggregate["idle_active"] = True
        return aggregate

    @staticmethod
    def _decision_command_status(value: Any) -> CommandResultStatus:
        """Map executor vocabulary explicitly; its Enum is intentionally distinct."""
        token = value.value if isinstance(value, CommandResult) else str(value or "")
        return {
            CommandResult.PLANNED.value: CommandResultStatus.PLANNED,
            CommandResult.QUEUED.value: CommandResultStatus.QUEUED,
            CommandResult.SENT.value: CommandResultStatus.SENT,
            CommandResult.SUPPRESSED.value: CommandResultStatus.SUPPRESSED,
            CommandResult.BLOCKED.value: CommandResultStatus.BLOCKED,
            CommandResult.TARGET_REACHED.value: CommandResultStatus.TARGET_REACHED,
            CommandResult.TARGET_NOT_REACHED.value: CommandResultStatus.TARGET_NOT_REACHED,
            CommandResult.FAILED.value: CommandResultStatus.FAILED,
            CommandResult.CANCELLED.value: CommandResultStatus.CANCELLED,
        }.get(token, CommandResultStatus.NOT_PLANNED)

    def _decision_with_command_result(
        self,
        result,
        *,
        status: Any,
        reason_code: str,
        details: dict[str, Any] | None = None,
    ):
        """Attach adapter output without accidentally coercing foreign Enums."""
        return result.with_command_result(
            DecisionCommandResult(
                status=self._decision_command_status(status),
                reason_code=str(reason_code or "command_not_planned"),
                target=result.target,
                details=details or {},
            )
        )

    def _refresh_advanced_decision_trace(self, runtime: RoomRuntime) -> None:
        """Persist a complete room trace plus per-layer/cover decision traces."""
        if not self.advanced_mode:
            runtime.decision_trace = {}
            return
        try:
            room = self.room_config(runtime.room_id)
        except (KeyError, StopIteration):
            return
        now = runtime.last_evaluation or dt_util.now()
        facts = self._decision_room_facts.get(runtime.room_id)
        if facts is None:
            result = self.decision_pipeline.evaluate(
                self._advanced_decision_context(room, runtime, now, mode=runtime.mode)
            )
        else:
            result = self._resolve_advanced_decision(
                room, runtime, now, facts=facts
            )
        target_traces = list(self._decision_target_traces.get(runtime.room_id, []))
        # A command lifecycle can complete after Home Assistant restarted,
        # before the next full room evaluation rebuilt ephemeral per-layer
        # traces.  Retain the restored projection in that narrow window so a
        # confirmed target is not erased while persisting its final outcome.
        if not target_traces:
            restored_target_traces = runtime.decision_trace.get("target_decisions")
            if isinstance(restored_target_traces, list):
                target_traces = list(restored_target_traces)
        command_rows = [
            {
                "cover_id": target.get("cover_id") or target.get("entity_id"),
                "status": target.get("command_result", CommandResult.PLANNED.value),
                "reason_code": target.get("command_reason_code") or target.get("reason_code"),
                "lifecycle_id": target.get("lifecycle_id"),
            }
            for target in runtime.targets
        ]
        if len(command_rows) == 1:
            row = command_rows[0]
            result = self._decision_with_command_result(
                result,
                status=row["status"],
                reason_code=str(row["reason_code"] or "command_adapter_result"),
                details={"cover_id": row["cover_id"], "lifecycle_id": row["lifecycle_id"]},
            )
        decision_payload = result.as_dict()
        pure_trace = decision_payload["trace"]
        if runtime.mode == MODE_GLARE:
            glare_result = next(
                (
                    cover.get("command")
                    for target_trace in target_traces
                    if isinstance(target_trace, dict)
                    for cover in target_trace.get("covers", [])
                    if isinstance(cover, dict)
                    and isinstance(cover.get("command"), dict)
                    and cover["command"].get("mode") == MODE_GLARE
                ),
                None,
            )
            glare_trace = (
                glare_result.get("trace")
                if isinstance(glare_result, dict)
                and isinstance(glare_result.get("trace"), dict)
                else None
            )
            if glare_trace is not None:
                decision_payload = glare_result
                pure_trace = glare_trace
        runtime.decision_trace = {
            "schema": 1,
            "evaluated_at": now.isoformat(),
            "trigger": self._current_trigger,
            "room_id": runtime.room_id,
            "mode": runtime.mode,
            "reason": runtime.reason,
            # Keep both a stable, convenient top-level projection for the
            # card and the complete nested pure result for API consumers.
            "winner": pure_trace["winner"],
            "rejected": pure_trace["rejected"],
            "entries": pure_trace["entries"],
            "input_snapshot": pure_trace["input_snapshot"],
            "command_result": pure_trace["command_result"],
            "protected_zones": pure_trace["protected_zones"],
            "decision": decision_payload,
            "target_decisions": target_traces,
            "command_results": command_rows,
        }

    def _append_advanced_target_trace(
        self,
        runtime: RoomRuntime,
        *,
        sector: dict[str, Any],
        layer: dict[str, Any],
        result,
    ) -> dict[str, Any]:
        """Keep one complete pure trace for each physical cover decision."""
        record = {
            "sector_id": str(sector.get("id") or ""),
            "sector_name": str(sector.get("name") or ""),
            "layer_id": str(layer.get("id") or ""),
            "layer_name": str(layer.get("name") or ""),
            "decision": result.as_dict(),
            "covers": [],
        }
        self._decision_target_traces.setdefault(runtime.room_id, []).append(record)
        return record

    def _decision_preview_contexts(
        self,
        room: dict[str, Any],
        runtime: RoomRuntime,
        now: datetime,
        *,
        sector_id: str | None = None,
        layer_id: str | None = None,
        mode: str | None = None,
        overrides: dict[str, Any] | None = None,
        snapshot: InputSnapshot | None = None,
        virtual_solar: bool = True,
        trajectory: Any = None,
    ) -> list[tuple[dict[str, Any] | None, dict[str, Any] | None, DecisionContext]]:
        """Return virtual production contexts selected by stable IDs.

        ``mode`` remains accepted for callers from the first Issue-79 draft,
        but it intentionally no longer replaces factual candidates.  A day
        preview must report what the production resolver would decide from
        its virtual inputs; scenarios should override those inputs directly.
        """
        virtual_snapshot = snapshot or self._advanced_virtual_snapshot(
            room,
            runtime,
            now,
            overrides,
            virtual_solar=virtual_solar,
            trajectory=trajectory,
        )
        contexts: list[tuple[dict[str, Any] | None, dict[str, Any] | None, DecisionContext]] = []
        for sector in room.get("sectors", []):
            if sector_id and str(sector.get("id")) != str(sector_id):
                continue
            facts = self._advanced_virtual_facts(
                room,
                runtime,
                sector,
                virtual_snapshot,
                now,
            )
            for layer in sector.get("layers", []):
                if layer_id and str(layer.get("id")) != str(layer_id):
                    continue
                contexts.append(
                    (
                        sector,
                        layer,
                        self._advanced_decision_context(
                            room,
                            runtime,
                            now,
                            facts=facts,
                            snapshot=virtual_snapshot,
                            sector=sector,
                            layer=layer,
                        ),
                    )
                )
        if not contexts:
            contexts.append(
                (
                    None,
                    None,
                    self._advanced_decision_context(
                        room,
                        runtime,
                        now,
                        facts=self._advanced_decision_facts(idle_active=True),
                        snapshot=virtual_snapshot,
                    ),
                )
            )
        return contexts

    @staticmethod
    def _preview_day_start(value: Any, fallback: datetime) -> datetime:
        """Resolve a selected preview date while retaining the local timezone."""
        if isinstance(value, datetime):
            selected = value.date()
        else:
            try:
                selected = datetime.fromisoformat(str(value).strip()[:10]).date()
            except (TypeError, ValueError):
                selected = fallback.date()
        return fallback.replace(
            year=selected.year,
            month=selected.month,
            day=selected.day,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

    @staticmethod
    def _preview_boundary_time(
        day_start: datetime,
        value: Any,
        fallback: tuple[int, int, int],
        *,
        after: timedelta | None = None,
    ) -> datetime:
        """Build a same-day clock boundary using established config parsing."""
        hour, minute, second = SmartShadingEngine._clock_parts(value, fallback)
        return day_start.replace(hour=hour, minute=minute, second=second) + (
            after or timedelta()
        )

    def _preview_sector_geometry_from_values(
        self,
        sector: dict[str, Any],
        values: dict[str, float | str] | None,
    ) -> bool:
        """Evaluate facade entry/exit from raw virtual solar coordinates."""
        if not values or values.get("sun_state") != "above_horizon":
            return False
        sector_id = str(sector.get("id") or "")
        if not sector_id or not bool(self.sector_value(sector_id, "enabled", True)):
            return False
        try:
            return bool(
                azimuth_inside(
                    float(values["sun_azimuth"]),
                    float(
                        self.sector_value(
                            sector_id,
                            "azimuth_start",
                            sector.get("azimuth_start", 0),
                        )
                    ),
                    float(
                        self.sector_value(
                            sector_id,
                            "azimuth_end",
                            sector.get("azimuth_end", 359),
                        )
                    ),
                )
                and float(values["sun_elevation"])
                >= float(
                    self.sector_value(
                        sector_id,
                        "elevation_min",
                        sector.get("elevation_min", 0),
                    )
                )
            )
        except (KeyError, TypeError, ValueError):
            return False

    def _preview_elevation_thresholds(self, room: dict[str, Any]) -> tuple[float, ...]:
        """Return elevation boundaries that can change a visible target."""
        values: set[float] = {0.0}
        for sector in room.get("sectors", []):
            sector_id = str(sector.get("id") or "")
            if not sector_id:
                continue
            elevation_min = parse_numeric_value(
                self.sector_value(
                    sector_id,
                    "elevation_min",
                    sector.get("elevation_min", 0),
                )
            )
            if elevation_min is not None:
                values.add(float(elevation_min))
            for layer in sector.get("layers", []):
                profile = str(layer.get("profile", DEVICE_VENETIAN))
                if profile not in {DEVICE_VENETIAN, DEVICE_VERTICAL}:
                    continue
                layer_id = str(layer.get("id") or "")
                defaults = PROFILE_DEFAULTS.get(
                    profile, PROFILE_DEFAULTS[DEVICE_VENETIAN]
                )
                for index, point in enumerate(
                    layer.get("tilt_curve", defaults.get("tilt_curve", [])),
                    start=1,
                ):
                    if not isinstance(point, dict):
                        continue
                    threshold = parse_numeric_value(
                        self.layer_value(
                            layer_id,
                            f"tilt_elevation_{index}",
                            point.get("elevation", 0),
                        )
                    )
                    if threshold is not None:
                        values.add(float(threshold))
        return tuple(sorted(value for value in values if math.isfinite(value)))

    @staticmethod
    def _preview_refine_boundary(
        start: datetime,
        end: datetime,
        predicate: Callable[[datetime], bool],
    ) -> datetime | None:
        """Bisect a known virtual transition to approximately one second."""
        try:
            start_value = bool(predicate(start))
            if start_value == bool(predicate(end)):
                return None
            lower, upper = start, end
            for _index in range(22):
                if (upper - lower).total_seconds() <= 1.0:
                    break
                middle = lower + (upper - lower) / 2
                if bool(predicate(middle)) == start_value:
                    lower = middle
                else:
                    upper = middle
        except (ArithmeticError, TypeError, ValueError):
            return None
        # ``upper`` is always on the new side of the transition.  Snap it up
        # to an explicit second so the preceding grid sample remains distinct.
        rounded = upper.replace(microsecond=0)
        if upper.microsecond:
            rounded += timedelta(seconds=1)
        return rounded

    def _preview_virtual_times(
        self,
        room: dict[str, Any],
        runtime: RoomRuntime,
        day_start: datetime,
        *,
        trajectory: Any = None,
    ) -> tuple[list[datetime], dict[str, Any]]:
        """Build a dense date-specific grid plus exact decision boundaries."""
        day_end = day_start + timedelta(days=1) - timedelta(seconds=1)
        grid = [
            day_start + timedelta(minutes=minute)
            for minute in range(0, 24 * 60, 5)
        ]
        grid.append(day_end)
        geometry_cache: dict[datetime, dict[str, float | str] | None] = {}
        source_cache: dict[datetime, str] = {}

        def coordinates(at: datetime) -> dict[str, float | str] | None:
            if at not in geometry_cache:
                values, source = self._virtual_solar_geometry(
                    at, trajectory=trajectory
                )
                geometry_cache[at] = values
                source_cache[at] = source
            return geometry_cache[at]

        coordinates(day_start)
        solar_source = source_cache.get(day_start, "unavailable")
        boundaries: set[datetime] = {day_start, day_end}
        if room.get("schedule_enabled", False) and room.get(
            "day_window", "sector_sun"
        ) == DAY_WINDOW_FIXED:
            boundaries.add(
                self._preview_boundary_time(
                    day_start, room.get("start_time", "00:00:00"), (0, 0, 0)
                )
            )
            boundaries.add(
                self._preview_boundary_time(
                    day_start,
                    room.get("end_time", "23:59:59"),
                    (23, 59, 59),
                    after=timedelta(seconds=1),
                )
            )
        boundaries.add(
            self._preview_boundary_time(
                day_start,
                room.get(
                    "evening_release_time",
                    self.config.get("evening_release_time", "18:00:00"),
                ),
                (18, 0, 0),
            )
        )
        if runtime.pause_until and day_start <= runtime.pause_until <= day_end:
            boundaries.add(runtime.pause_until)
        if (
            runtime.night_morning_hold_until
            and day_start <= runtime.night_morning_hold_until <= day_end
        ):
            boundaries.add(runtime.night_morning_hold_until)

        # Astral provides exact Night offsets; trajectory and location-less
        # fallbacks still receive horizon/sector boundaries below from the
        # same dense coordinates rather than a fabricated sunrise/sunset.
        if solar_source == "astral":
            sunrise, sunset = self._virtual_solar_events(day_start)
            for event in (sunrise, sunset):
                if event is not None:
                    boundaries.add(event)
            if room.get("night_enabled") and room.get("night_source") == "sun":
                if sunrise is not None:
                    boundaries.add(
                        sunrise
                        + timedelta(
                            minutes=float(
                                room.get("night_end_offset_minutes", 0)
                            )
                        )
                    )
                if sunset is not None:
                    boundaries.add(
                        sunset
                        + timedelta(
                            minutes=float(
                                room.get("night_start_offset_minutes", 0)
                            )
                        )
                    )

        thresholds = self._preview_elevation_thresholds(room)
        for left, right in zip(grid, grid[1:]):
            left_values = coordinates(left)
            right_values = coordinates(right)
            if left_values is None or right_values is None:
                continue
            for sector in room.get("sectors", []):
                boundary = self._preview_refine_boundary(
                    left,
                    right,
                    lambda at, item=sector: self._preview_sector_geometry_from_values(
                        item, coordinates(at)
                    ),
                )
                if boundary is not None:
                    boundaries.add(boundary)
            for threshold in thresholds:
                boundary = self._preview_refine_boundary(
                    left,
                    right,
                    lambda at, level=threshold: bool(
                        (coordinates(at) or {}).get("sun_elevation", -90.0)
                        >= level
                    ),
                )
                if boundary is not None:
                    boundaries.add(boundary)

        points = sorted(
            point for point in set(grid).union(boundaries) if day_start <= point <= day_end
        )
        return points, {
            "solar_source": solar_source,
            "solar_available": coordinates(day_start) is not None,
            "grid_minutes": 5,
            "boundary_count": len(boundaries),
        }

    @staticmethod
    def _preview_sun_summary(context: DecisionContext) -> dict[str, Any]:
        """Expose coordinates beside each sample for compact Card/export use."""
        snapshot = context.snapshot
        state = snapshot.get("sun_state")
        return {
            "state": state.value if state.valid else None,
            "azimuth": SmartShadingEngine._virtual_input_number(
                snapshot, "sun_azimuth"
            ),
            "elevation": SmartShadingEngine._virtual_input_number(
                snapshot, "sun_elevation"
            ),
            "source": snapshot.details.get("virtual_solar_source"),
        }

    @staticmethod
    def _preview_scoped_transitions(
        samples: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Derive transitions per sector/layer instead of interleaving scopes."""
        previous: dict[tuple[str | None, str | None], dict[str, Any]] = {}
        transitions: list[dict[str, Any]] = []
        for sample in samples:
            scope = sample.get("scope") if isinstance(sample.get("scope"), dict) else {}
            key = (scope.get("sector_id"), scope.get("layer_id"))
            prior = previous.get(key)
            result = sample.get("result") if isinstance(sample.get("result"), dict) else {}
            if prior is not None:
                prior_result = prior.get("result", {})
                if (
                    prior_result.get("mode") != result.get("mode")
                    or prior_result.get("target") != result.get("target")
                ):
                    transitions.append(
                        {
                            "at": sample.get("at"),
                            "scope": dict(scope),
                            "previous_mode": prior_result.get("mode"),
                            "mode": result.get("mode"),
                            "previous_target": prior_result.get("target"),
                            "target": result.get("target"),
                            "reason_code": "decision_changed",
                        }
                    )
            previous[key] = sample
        return transitions

    @staticmethod
    def _preview_sector_periods(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Project deterministic sector entry/exit periods from scoped samples."""
        by_sector: dict[str, list[dict[str, Any]]] = {}
        seen: set[tuple[str, str]] = set()
        for sample in samples:
            scope = sample.get("scope") if isinstance(sample.get("scope"), dict) else {}
            sector_id = scope.get("sector_id")
            at = sample.get("at")
            if not sector_id or not at or (sector_id, at) in seen:
                continue
            seen.add((sector_id, at))
            by_sector.setdefault(str(sector_id), []).append(sample)
        periods: list[dict[str, Any]] = []
        for sector_id, sector_samples in by_sector.items():
            active_since: str | None = None
            last_sample: dict[str, Any] | None = None
            for sample in sector_samples:
                active = bool(sample.get("sector_geometry_active"))
                if active and active_since is None:
                    active_since = sample.get("at")
                elif not active and active_since is not None:
                    periods.append(
                        {
                            "sector_id": sector_id,
                            "started_at": active_since,
                            "ended_at": sample.get("at"),
                            "sun": sample.get("sun"),
                        }
                    )
                    active_since = None
                last_sample = sample
            if active_since is not None:
                periods.append(
                    {
                        "sector_id": sector_id,
                        "started_at": active_since,
                        "ended_at": None,
                        "sun": last_sample.get("sun") if last_sample else None,
                    }
                )
        return periods

    async def async_simulate_room(
        self, room_id: str, overrides: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Run the production decision pipeline without planning a command.

        This public Advanced-only API deliberately takes only virtual input
        values.  It neither touches the command planner nor calls a Home
        Assistant service, making it safe for the card and diagnostics.
        """
        if not self.advanced_mode:
            return {
                "available": False,
                "reason_code": "simulation_advanced_mode_required",
                "room_id": room_id,
            }
        room = self.room_config(room_id)
        runtime = self.rooms[room_id]
        now = dt_util.now()
        virtual = dict(overrides or {})
        simulated_at = self._virtual_when(virtual, now)
        results: list[dict[str, Any]] = []
        for sector, layer, context in self._decision_preview_contexts(
            room, runtime, simulated_at, overrides=virtual
        ):
            result = simulate_decision(
                context,
                pipeline=self.decision_pipeline,
            )
            results.append(
                {
                    "sector_id": sector.get("id") if sector else None,
                    "layer_id": layer.get("id") if layer else None,
                    "result": result.as_dict(),
                    "cover_targets": (
                        self._simulation_cover_targets(
                            room,
                            sector,
                            layer,
                            result,
                            context.snapshot,
                        )
                        if sector is not None and layer is not None
                        else []
                    ),
                }
            )
        payload = {
            "schema": 1,
            "available": True,
            "completed": True,
            "room_id": room_id,
            "simulated_at": simulated_at.isoformat(),
            "overrides": virtual,
            "results": results,
            "result": results[0]["result"] if len(results) == 1 else None,
            "reason_code": "simulation_never_executes_services",
        }
        # A simulation is an instantaneous calculation, not a mode.  Keeping
        # this flag set made the customer UI report "Simulation active" long
        # after the result was available.
        runtime.simulation_active = False
        runtime.simulation_trace = payload
        self._notify()
        return payload

    async def async_clear_simulation(self, room_id: str) -> None:
        """Remove transient customer simulation output without reevaluating HA."""
        runtime = self.rooms[room_id]
        runtime.simulation_active = False
        runtime.simulation_trace = {}
        runtime.day_preview = {}
        self._notify()

    async def async_preview_room_day(
        self,
        room_id: str,
        points: Any | None = None,
        *,
        date: Any | None = None,
    ) -> dict[str, Any]:
        """Build a non-executing day preview through the same decision pipeline.

        ``points`` accepts :class:`PreviewPoint` instances or dictionaries with
        ``at`` (datetime/ISO string), optional ``label``, ``overrides``,
        ``sector_id`` and ``layer_id``.  The old point-level ``mode`` hint is
        accepted for compatibility but deliberately ignored: virtual inputs,
        not a fabricated mode, drive the production resolver.  With no
        explicit points, ``date=`` (or ``{"date": ...}``) selects a complete
        virtual day with deterministic Astral/trajectory solar geometry.
        """
        if not self.advanced_mode:
            return {
                "available": False,
                "reason_code": "preview_advanced_mode_required",
                "room_id": room_id,
            }
        room = self.room_config(room_id)
        runtime = self.rooms[room_id]
        now = dt_util.now()
        request: dict[str, Any] = {}
        raw_points = points
        if (
            isinstance(points, dict)
            and "at" not in points
            and any(
                key in points
                for key in (
                    "date",
                    "points",
                    "overrides",
                    "sun_trajectory",
                    "solar_trajectory",
                )
            )
        ):
            request = dict(points)
            raw_points = request.get("points")
            if date is None:
                date = request.get("date")
        day_start = self._preview_day_start(date, now)
        base_overrides = (
            dict(request.get("overrides", {}))
            if isinstance(request.get("overrides"), dict)
            else {}
        )
        trajectory = request.get(
            "sun_trajectory", request.get("solar_trajectory")
        )
        supplied = (
            list(raw_points)
            if isinstance(raw_points, (list, tuple))
            else ([raw_points] if raw_points else [])
        )
        preview_assumptions: dict[str, Any]
        if not supplied:
            generated_times, preview_assumptions = self._preview_virtual_times(
                room,
                runtime,
                day_start,
                trajectory=trajectory,
            )
            supplied = [
                {
                    "at": at,
                    "label": at.strftime("%H:%M"),
                    "overrides": base_overrides,
                    "_generated_preview_point": True,
                }
                for at in generated_times
            ]
        else:
            solar_values, solar_source = self._virtual_solar_geometry(
                day_start, trajectory=trajectory
            )
            preview_assumptions = {
                "solar_source": solar_source,
                "solar_available": solar_values is not None,
                "grid_minutes": None,
                "boundary_count": 0,
            }

        preview_records: list[tuple[PreviewPoint, dict[str, Any], int]] = []
        ignored_mode_hints: list[dict[str, Any]] = []
        for raw in supplied:
            if isinstance(raw, PreviewPoint):
                preview_records.append(
                    (
                        raw,
                        {
                            "scope": {
                                "sector_id": raw.context.sector_id,
                                "layer_id": raw.context.group_id,
                            },
                            "sun": self._preview_sun_summary(raw.context),
                            "sector_geometry_active": bool(
                                raw.context.sun_geometry
                                and raw.context.sun_geometry.direct_sun
                            ),
                        },
                        len(preview_records),
                    )
                )
                continue
            if not isinstance(raw, dict):
                continue
            at = _parse_datetime(raw.get("at"))
            if at is None and (
                raw.get("date") is not None or raw.get("time") is not None
            ):
                point_clock = dict(raw)
                at = self._virtual_when(point_clock, day_start)
            if at is None:
                continue
            if at.tzinfo is None and day_start.tzinfo is not None:
                at = at.replace(tzinfo=day_start.tzinfo)
            if raw.get("mode") is not None:
                ignored_mode_hints.append(
                    {"at": at.isoformat(), "mode": str(raw.get("mode"))}
                )
            point_overrides = dict(base_overrides)
            if isinstance(raw.get("overrides"), dict):
                point_overrides.update(raw["overrides"])
            contexts = self._decision_preview_contexts(
                room,
                runtime,
                at,
                sector_id=raw.get("sector_id"),
                layer_id=raw.get("layer_id"),
                mode=raw.get("mode"),
                overrides=point_overrides,
                virtual_solar=True,
                trajectory=raw.get(
                    "sun_trajectory",
                    raw.get("solar_trajectory", trajectory),
                ),
            )
            for sector, layer, context in contexts:
                scope = raw.get("label") or ""
                if not scope and (sector or layer):
                    scope = ":".join(
                        value
                        for value in (
                            str(sector.get("id")) if sector else "",
                            str(layer.get("id")) if layer else "",
                        )
                        if value
                    )
                preview_point = PreviewPoint(at=at, context=context, label=str(scope))
                preview_records.append(
                    (
                        preview_point,
                        {
                            "scope": {
                                "sector_id": str(sector.get("id")) if sector else None,
                                "sector_name": str(sector.get("name") or "") if sector else "",
                                "layer_id": str(layer.get("id")) if layer else None,
                                "layer_name": str(layer.get("name") or "") if layer else "",
                            },
                            "sun": self._preview_sun_summary(context),
                            "sector_geometry_active": bool(
                                sector
                                and self._virtual_sector_geometry(context.snapshot, sector)
                            ),
                        },
                        len(preview_records),
                    )
                )

        ordered_records = sorted(
            preview_records,
            key=lambda record: (record[0].at, record[2]),
        )
        preview = preview_day(
            [record[0] for record in ordered_records],
            pipeline=self.decision_pipeline,
        )
        preview_payload = preview.as_dict()
        preview_payload["day"] = day_start.date().isoformat()
        enriched_samples = preview_payload["samples"]
        for sample, (_point, metadata, _sequence) in zip(
            enriched_samples, ordered_records
        ):
            sample.update(metadata)
            result = sample.get("result") if isinstance(sample.get("result"), dict) else {}
            trace = result.get("trace") if isinstance(result.get("trace"), dict) else {}
            winner = trace.get("winner") if isinstance(trace.get("winner"), dict) else {}
            sample["reason_code"] = winner.get("reason_code")
        preview_payload["transitions"] = self._preview_scoped_transitions(
            enriched_samples
        )
        preview_payload["sector_periods"] = self._preview_sector_periods(
            enriched_samples
        )
        preview_payload["assumptions"] = {
            **preview_assumptions,
            "date": day_start.date().isoformat(),
            "non_solar_inputs": "current_or_supplied_virtual_values",
            "mode_hints_are_ignored": bool(ignored_mode_hints),
        }
        payload = {
            "schema": 1,
            "available": True,
            "completed": True,
            "room_id": room_id,
            "generated_at": now.isoformat(),
            "date": day_start.date().isoformat(),
            "preview": preview_payload,
            "day_preview": preview_payload,
            "assumptions": preview_payload["assumptions"],
            "ignored_mode_hints": ignored_mode_hints,
            "reason_code": "preview_never_executes_services",
        }
        runtime.day_preview = payload
        self._notify()
        return payload

    async def _evaluate_room(
        self, room: dict[str, Any], now: datetime
    ) -> None:
        runtime = self.rooms[room["id"]]
        runtime.last_evaluation = now
        runtime.active_sectors = []
        runtime.targets = []
        self._decision_target_traces[runtime.room_id] = []
        self._decision_room_facts.pop(runtime.room_id, None)
        for configured_sector in room.get("sectors", []):
            sector_runtime = self.sun_runtime.get(configured_sector["id"])
            if sector_runtime:
                sector_runtime.geometry_active = False
                sector_runtime.shading_active = False
                sector_runtime.effective_active = False
                sector_runtime.mode = MODE_IDLE
                sector_runtime.status = "not_evaluated"
                sector_runtime.status_reason = "Evaluation started"
        self._schedule_geometry_boundary_timer(room, now)
        if not self.advanced_mode:
            await self._evaluate_easy_room(room, runtime, now)
            return
        schedule_active, schedule_reason, next_change = self._schedule_status(room, now)
        runtime.schedule_active = schedule_active
        runtime.schedule_reason = schedule_reason
        runtime.next_schedule_change = next_change
        self._schedule_schedule_timer(room["id"], next_change)
        await self._async_update_night_state(room, now)
        self._schedule_heat_release_timer(room, runtime, now)

        # Build the actual high-priority facts before taking any production
        # branch.  The resolver, rather than this control-flow order, selects
        # the effective Advanced mode; the legacy code below only performs
        # the selected lifecycle/action.
        pause_active = self._pause_active(runtime, now)
        blockers = [
            entity
            for entity in room.get("safety_blockers", [])
            if _is_on(self.hass, entity)
        ]
        unavailable_blockers = [
            entity
            for entity in room.get("safety_blockers", [])
            if (
                (state := self.hass.states.get(entity)) is None
                or state.state
                in {"unknown", "unavailable", "none", ""}
            )
        ]
        # Calculate normal candidates before checking Safety/Pause/Night.
        # The high-priority branch below may return without sending a normal
        # command, but the trace must still show the real Solar/Comfort/Open
        # candidates it rejected.
        priority_snapshot = self._advanced_virtual_snapshot(room, runtime, now)
        priority_facts = self._advanced_room_candidate_facts(
            room, runtime, priority_snapshot, now
        )
        priority_facts.update(
            {
                "safety_active": bool(blockers),
                "safety_source_hold_active": bool(unavailable_blockers),
                "manual_override_active": not runtime.enabled,
                "room_pause_active": (
                    pause_active
                    and not (
                        bool(room.get("heat_during_pause", False))
                        and runtime.heat_active
                    )
                ),
                # Preserve normal candidates already calculated above.  These
                # overrides only describe the room-wide priority facts.
                "night_source_hold_active": (
                    bool(priority_facts.get("night_source_hold_active"))
                    or runtime.night_blocked
                ),
                "night_active": (
                    bool(priority_facts.get("night_active"))
                    or runtime.night_active
                ),
                "heat_active": (
                    bool(priority_facts.get("heat_active"))
                    or runtime.heat_active
                ),
                "idle_active": (
                    bool(priority_facts.get("idle_active"))
                    or runtime.night_blocked
                ),
            }
        )
        priority_result = self._resolve_advanced_decision(
            room, runtime, now, facts=priority_facts, snapshot=priority_snapshot
        )
        self._decision_room_facts[runtime.room_id] = priority_facts

        if priority_result.mode == MODE_SAFETY:
            runtime.mode = priority_result.mode
            runtime.reason = f"Safety active: {self._entity_display_name(blockers[0], 'Safety sensor')}"
            self._mark_room_sectors(room, status="safety", reason=runtime.reason, mode=MODE_SAFETY, active=True)
            if room.get("safety_behavior", "move_safe") == "move_safe":
                await self._apply_room_mode(
                    room,
                    runtime,
                    priority_result.mode,
                    0.0,
                    facts=priority_facts,
                )
            else:
                # "Block normal automation" must also invalidate work that
                # was queued before the Safety input became active.  A hold
                # cannot recall a service call already accepted by the
                # actuator, but it can prevent delayed axes, staggered covers
                # and verification retries from moving later.
                await self._cancel_pending_normal_lifecycles(
                    runtime.room_id,
                    "safety_block_active",
                    include_non_safety=True,
                )
            await self._save_room_runtime(runtime)
            return

        if priority_result.mode == MODE_DISABLED:
            await self._cancel_pending_normal_lifecycles(
                runtime.room_id,
                "room_automation_disabled",
                include_non_safety=True,
            )
            runtime.mode = priority_result.mode
            runtime.reason = "Room automation disabled"
            self._mark_room_sectors(room, status="disabled", reason=runtime.reason, mode=MODE_DISABLED, active=False)
            await self._save_room_runtime(runtime)
            return

        if priority_result.mode == MODE_PAUSED:
            await self._cancel_pending_normal_lifecycles(
                runtime.room_id,
                "room_automation_paused",
                include_non_safety=True,
            )
            runtime.mode = priority_result.mode
            runtime.reason = "Automatic shading is paused"
            self._mark_room_sectors(room, status="paused", reason=runtime.reason, mode=MODE_PAUSED, active=False)
            await self._save_room_runtime(runtime)
            return

        if priority_result.winner.rule == "safety_source_hold":
            await self._cancel_pending_normal_lifecycles(
                runtime.room_id,
                "safety_source_unavailable_hold",
                include_non_safety=True,
            )
            runtime.mode = MODE_IDLE
            names = [
                self._entity_display_name(entity, "Safety sensor")
                for entity in unavailable_blockers
            ]
            runtime.reason = (
                "Safety input unavailable; automatic movements held: "
                + ", ".join(names)
            )
            self._mark_room_sectors(
                room,
                status="safety_unavailable",
                reason=runtime.reason,
                mode=MODE_IDLE,
                active=False,
            )
            await self._save_room_runtime(runtime)
            return

        sun_entity = DEFAULT_SUN_ENTITY
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

        if priority_result.mode == MODE_IDLE and runtime.night_blocked:
            await self._cancel_pending_normal_lifecycles(
                runtime.room_id,
                "night_source_unavailable",
            )
            runtime.mode = priority_result.mode
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

        if priority_result.mode == MODE_NIGHT:
            await self._cancel_pending_normal_lifecycles(
                runtime.room_id,
                "night_mode_active",
                include_non_safety=True,
            )
            if runtime.heat_phase == "release_pending":
                # An evening handoff intentionally keeps covers closed until
                # Night takes ownership.  Once that happens the Heat cycle is
                # terminal for the day, including across a later restart.
                runtime.heat_phase = "released_today"
            if runtime.heat_active:
                # Night is the active room mode, but it must not erase the
                # Heat lifecycle.  The hold is visible in diagnostics and a
                # restart can continue with the same conservative state.
                runtime.heat_phase = "holding"
            runtime.mode = priority_result.mode
            runtime.reason = runtime.night_reason
            self._mark_room_sectors(
                room,
                status="night",
                reason=runtime.reason,
                mode=MODE_NIGHT,
                active=True,
            )
            await self._apply_room_mode(
                room,
                runtime,
                priority_result.mode,
                elevation,
                facts=priority_facts,
            )
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
        heat_schedule_pass = schedule_active
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
        heat_conditions_valid = bool(
            indoor_valid
            and heat_sun_pass
            and heat_schedule_pass
            and heat_weather_pass
            and outdoor_ok
        )
        if (
            not runtime.heat_active
            and not runtime.finished_today
            and heat_conditions_valid
            and indoor is not None
            and indoor < heat_start
        ):
            runtime.heat_phase = "armed"
        if (
            not runtime.heat_active
            and not runtime.finished_today
            and (
                heat_conditions_valid
                and indoor is not None
                and indoor >= heat_start
            )
        ):
            # Heat protection is latched for the day. Falling temperature or
            # Sun Presence ending must not reopen covers and start another
            # heat cycle later. Only the configured evening release clears it.
            runtime.heat_active = True
            runtime.heat_phase = "active"
        self._schedule_heat_release_timer(room, runtime, now)

        if runtime.heat_active and self._evening_release_reached(room, now):
            runtime.heat_phase = "release_pending"
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
                await self._cancel_pending_normal_lifecycles(
                    runtime.room_id,
                    "evening_night_handoff_hold",
                )
                hold_facts = self._advanced_decision_facts(idle_active=True)
                runtime.mode = self._resolve_advanced_decision(
                    room, runtime, now, facts=hold_facts
                ).mode
                self._decision_room_facts[runtime.room_id] = hold_facts
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
            release_opens = bool(
                schedule_active
                or room.get("outside_schedule_behavior", OUTSIDE_OPEN)
                == OUTSIDE_OPEN
            )
            release_facts = self._advanced_decision_facts(
                open_active=release_opens,
                schedule_hold_active=not release_opens,
                idle_active=not release_opens,
            )
            runtime.mode = self._resolve_advanced_decision(
                room, runtime, now, facts=release_facts
            ).mode
            self._decision_room_facts[runtime.room_id] = release_facts
            runtime.reason = "Heat protection released for evening"
            runtime.heat_phase = "released_today"
            if release_opens:
                await self._apply_room_mode(
                    room,
                    runtime,
                    runtime.mode,
                    elevation,
                    facts=release_facts,
                )
            else:
                await self._cancel_pending_normal_lifecycles(
                    runtime.room_id,
                    "heat_released_outside_schedule_hold",
                )
            self._mark_room_sectors(
                room,
                status="outside_sun_sector",
                reason=runtime.reason,
                mode=runtime.mode,
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
            await self._cancel_pending_normal_lifecycles(
                runtime.room_id,
                "evening_night_handoff_hold",
            )
            hold_facts = self._advanced_decision_facts(idle_active=True)
            runtime.mode = self._resolve_advanced_decision(
                room, runtime, now, facts=hold_facts
            ).mode
            self._decision_room_facts[runtime.room_id] = hold_facts
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
        unavailable_source_sectors: set[str] = set()
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
            elif confirmation_source != "geometry" and confirmation_state is None:
                unavailable_source_sectors.add(str(sector["id"]))
                sector_runtime.status = "source_unavailable"
                sector_runtime.status_reason = (
                    "Selected sun source is unavailable; cover position held"
                )
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
            heat_facts = self._advanced_decision_facts(
                heat_active=True,
                room_pause_active=(
                    pause_active and not bool(room.get("heat_during_pause", False))
                ),
            )
            heat_result = self._resolve_advanced_decision(
                room, runtime, now, facts=heat_facts
            )
            runtime.heat_phase = "holding"
            runtime.night_morning_handover_pending = False
            runtime.night_morning_hold_until = None
            runtime.mode = heat_result.mode
            self._decision_room_facts[runtime.room_id] = heat_facts
            runtime.reason = "Heat threshold / hysteresis active"
            self._mark_room_sectors(room, status="heat", reason=runtime.reason, mode=runtime.mode, active=True)
            await self._apply_room_mode(
                room,
                runtime,
                runtime.mode,
                elevation,
                facts=heat_facts,
            )
            await self._save_room_runtime(runtime)
            return

        if pause_active:
            pause_facts = self._advanced_decision_facts(room_pause_active=True)
            runtime.mode = self._resolve_advanced_decision(
                room, runtime, now, facts=pause_facts
            ).mode
            self._decision_room_facts[runtime.room_id] = pause_facts
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
            schedule_facts = self._advanced_decision_facts(
                schedule_hold_active=behavior != OUTSIDE_OPEN,
                open_active=behavior == OUTSIDE_OPEN,
                idle_active=behavior != OUTSIDE_OPEN,
            )
            schedule_result = self._resolve_advanced_decision(
                room, runtime, now, facts=schedule_facts
            )
            runtime.mode = schedule_result.mode
            self._decision_room_facts[runtime.room_id] = schedule_facts
            if runtime.mode == MODE_OPEN:
                runtime.reason = f"{schedule_reason}; covers moved to neutral/open position"
                await self._apply_room_mode(
                    room,
                    runtime,
                    runtime.mode,
                    elevation,
                    facts=schedule_facts,
                )
            else:
                await self._cancel_pending_normal_lifecycles(
                    runtime.room_id,
                    "schedule_outside_hold",
                )
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

        # Normal production and virtual replay share this factual calculator.
        # The legacy expressions above remain solely for customer-facing
        # reason text and the stateful Venetian hysteresis update.
        production_snapshot = self._advanced_virtual_snapshot(room, runtime, now)

        highest_mode = MODE_IDLE
        reasons: list[str] = []
        morning_transition_waiting = False
        unavailable_source_waiting = False
        quality_hold_waiting = False
        representative_facts: dict[str, bool] | None = None
        for sector in room.get("sectors", []):
            if not bool(self.sector_value(sector["id"], "enabled", True)):
                # Disabled sectors are neither an Open fallback nor a hidden
                # command source.  They were already marked above; skip their
                # physical planner path entirely.
                reasons.append(f"{sector['name']}: Sector disabled")
                continue
            source_unavailable = (
                str(sector["id"]) in unavailable_source_sectors
            )
            solar_active = False
            comfort_active = False
            open_active = False
            idle_active = False
            if source_unavailable:
                idle_active = True
                unavailable_source_waiting = True
                reason = "Selected sun source is unavailable; cover position held"
            elif sector in active_sectors:
                if venetian_only:
                    if weather_pass and outdoor_ok and comfort_allowed and (glare or runtime.shading_active):
                        solar_active = True
                        reason = "Normal adaptive solar shading"
                    else:
                        idle_active = True
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
                    solar_active = True
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
                    comfort_active = True
                    reason = "Glare / comfort protection"
                else:
                    idle_active = True
                    waiting = weather_failed or [
                        "temperature / occupancy / outdoor condition"
                    ]
                    reason = f"Waiting: {', '.join(waiting)}"
            else:
                open_active = True
                reason = "Sun outside this sector"

            morning_handover = bool(
                runtime.night_morning_handover_pending
                and self.sun_runtime[sector["id"]].geometry_active
                and not (comfort_active or solar_active)
            )
            morning_hold = bool(
                morning_handover
                and runtime.night_morning_hold_until
                and runtime.night_morning_hold_until > now
            )
            if morning_handover:
                if morning_hold:
                    solar_active = False
                    comfort_active = False
                    open_active = False
                    idle_active = True
                    morning_transition_waiting = True
                    reason = "Morning transition holds Night target while shading conditions settle"
                else:
                    solar_active = False
                    comfort_active = False
                    open_active = True
                    idle_active = False
                    reason = "Morning transition window ended; cover opened"

            sector_facts = self._advanced_virtual_facts(
                room,
                runtime,
                sector,
                production_snapshot,
                now,
            )
            if source_unavailable:
                sector_facts.update(
                    solar_active=False,
                    comfort_active=False,
                    open_active=False,
                    idle_active=True,
                )
            elif morning_handover:
                sector_facts.update(
                    solar_active=False,
                    comfort_active=False,
                    open_active=not morning_hold,
                    idle_active=morning_hold,
                )
            sector_result = self._resolve_advanced_decision(
                room,
                runtime,
                now,
                facts=sector_facts,
                sector=sector,
            )
            if source_unavailable:
                await self._cancel_pending_normal_lifecycles(
                    runtime.room_id,
                    "selected_sun_source_unavailable",
                    sector_id=str(sector.get("id") or "") or None,
                )
            elif sector_result.winner.rule == "input_quality_hold":
                await self._cancel_pending_normal_lifecycles(
                    runtime.room_id,
                    "normal_input_quality_invalid_hold",
                    sector_id=str(sector.get("id") or "") or None,
                )
            requested_mode = sector_result.mode
            mode = await self._apply_sector_mode(
                room,
                sector,
                runtime,
                requested_mode,
                elevation,
                reason,
                facts=sector_facts,
            )
            if mode == MODE_GLARE:
                reason = "Direct sun reaches a configured protected area"
            if sector_result.winner.rule == "input_quality_hold":
                quality_hold_waiting = True
                reason = "Input quality is unavailable, stale or pending; cover positions held"
            sector_runtime = self.sun_runtime[sector["id"]]
            sector_runtime.mode = mode
            sector_runtime.shading_active = mode in {
                MODE_COMFORT,
                MODE_SOLAR,
                MODE_GLARE,
                MODE_HEAT,
                MODE_SAFETY,
            }
            if mode in {MODE_COMFORT, MODE_SOLAR, MODE_GLARE}:
                sector_runtime.status = "shading_active"
            elif (
                mode == MODE_IDLE
                and sector_runtime.geometry_active
                and not source_unavailable
            ):
                sector_runtime.status = (
                    "night_transition_hold" if morning_hold else "waiting_conditions"
                )
            sector_runtime.status_reason = reason
            reasons.append(f"{sector['name']}: {reason}")
            if self._mode_priority(mode) > self._mode_priority(highest_mode):
                highest_mode = mode
                representative_facts = sector_facts

        if runtime.night_morning_handover_pending and not morning_transition_waiting:
            runtime.night_morning_handover_pending = False
            runtime.night_morning_hold_until = None
        runtime.mode = (
            MODE_IDLE
            if (
                (
                    morning_transition_waiting
                    or unavailable_source_waiting
                    or quality_hold_waiting
                )
                and highest_mode == MODE_OPEN
            )
            else highest_mode if room.get("sectors") else MODE_IDLE
        )
        if representative_facts is None:
            representative_facts = self._advanced_decision_facts(idle_active=True)
        # For a mixed room the selected sector fact set is the room-level
        # production trace.  It retains the full live candidates rather than
        # reconstructing a synthetic fact from the final mode at save time.
        self._decision_room_facts[runtime.room_id] = representative_facts
        runtime.reason = " · ".join(reasons) if reasons else "No sectors configured"
        await self._save_room_runtime(runtime)

    @staticmethod
    def _mode_priority(mode: str) -> int:
        return {
            MODE_IDLE: 0,
            MODE_OPEN: 1,
            MODE_COMFORT: 2,
            MODE_SOLAR: 3,
            MODE_GLARE: 4,
            MODE_HEAT: 5,
            MODE_NIGHT: 6,
            MODE_SAFETY: 7,
        }.get(mode, 0)

    def _evening_release_reached(
        self, room: dict[str, Any], now: datetime
    ) -> bool:
        return self._heat_release_due(room, now) <= now

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
            await self._cancel_pending_normal_lifecycles(
                runtime.room_id,
                "room_automation_disabled",
                include_non_safety=True,
            )
            runtime.mode = MODE_DISABLED
            runtime.reason = "Manual Override is active"
            self._mark_room_sectors(
                room, status="disabled", reason=runtime.reason,
                mode=MODE_DISABLED, active=False,
            )
            await self._save_room_runtime(runtime)
            return

        sun_entity = DEFAULT_SUN_ENTITY
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
            for sector in room.get("sectors", []):
                await self._cancel_pending_normal_lifecycles(
                    runtime.room_id,
                    "sun_position_unavailable",
                    sector_id=str(sector.get("id") or "") or None,
                )
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
        unavailable_count = 0
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
            source_unavailable = (
                geometry and source != "geometry" and confirmation is None
            )
            confirmed = source == "geometry" or confirmation is True
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
            elif source_unavailable:
                unavailable_count += 1
                sector_runtime.status = "source_unavailable"
                sector_runtime.status_reason = (
                    f"{source_label_map[source]} is unavailable; cover position held"
                )
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
            if source_unavailable:
                await self._cancel_pending_normal_lifecycles(
                    runtime.room_id,
                    "selected_sun_source_unavailable",
                    sector_id=str(sector.get("id") or "") or None,
                )
            else:
                await self._apply_sector_mode(
                    room, sector, runtime,
                    MODE_SOLAR if active else MODE_OPEN,
                    elevation,
                    sector_runtime.status_reason,
                )

        if not geometry_count:
            runtime.easy_confirmation_state = "inactive"
        elif unavailable_count:
            runtime.easy_confirmation_state = (
                "unavailable"
                if unavailable_count == geometry_count
                else "mixed"
            )
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
        runtime.mode = (
            MODE_SOLAR
            if active_count
            else MODE_IDLE if unavailable_count else MODE_OPEN
        )
        runtime.shading_active = bool(active_count)
        if active_count:
            runtime.reason = "Sun is active in a configured facade sector"
        elif unavailable_count:
            runtime.reason = "Selected sun source is unavailable; cover positions held"
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
        *,
        facts: dict[str, bool] | None = None,
    ) -> None:
        for sector in room.get("sectors", []):
            await self._apply_sector_mode(
                room,
                sector,
                runtime,
                mode,
                elevation,
                runtime.reason,
                facts=facts,
            )

    async def _apply_sector_mode(
        self,
        room: dict[str, Any],
        sector: dict[str, Any],
        runtime: RoomRuntime,
        mode: str,
        elevation: float,
        reason: str,
        *,
        facts: dict[str, bool] | None = None,
    ) -> str:
        resolved_mode = mode
        highest_resolved_mode = mode
        for layer in sector.get("layers", []):
            position, tilt = self._targets(layer, resolved_mode, elevation)
            decision_result = None
            trace_record = None
            if self.advanced_mode:
                if facts is None:
                    decision_result = self.decision_pipeline.evaluate(
                        self._advanced_decision_context(
                            room,
                            runtime,
                            runtime.last_evaluation or dt_util.now(),
                            mode=mode,
                            sector=sector,
                            layer=layer,
                        )
                    )
                else:
                    decision_result = self._resolve_advanced_decision(
                        room,
                        runtime,
                        runtime.last_evaluation or dt_util.now(),
                        facts=facts,
                        sector=sector,
                        layer=layer,
                    )
                resolved_mode = decision_result.mode
                # The production resolver owns the effective mode.  The
                # established profile mapper still supplies all physical
                # targets, then protected zones may narrow the Solar target.
                position, tilt = self._targets(layer, resolved_mode, elevation)
                if decision_result.target is not None:
                    if decision_result.target.position is not None:
                        position = decision_result.target.position
                    if decision_result.target.tilt is not None:
                        tilt = decision_result.target.tilt
                trace_record = self._append_advanced_target_trace(
                    runtime,
                    sector=sector,
                    layer=layer,
                    result=decision_result,
                )
                glare_probe = bool(
                    facts
                    and facts.get("glare_allowed")
                    and self.room_feature_enabled(
                        str(room.get("id") or ""),
                        FEATURE_GLARE_PROTECTION,
                    )
                    and sector.get("protected_zones")
                )
                if (
                    resolved_mode in {MODE_IDLE, MODE_PAUSED, MODE_DISABLED}
                    and not glare_probe
                ):
                    # A resolver hold is operational, not merely a trace. In
                    # particular it prevents a stale normal source from
                    # reaching the legacy cover adapter after the pipeline
                    # rejected it.
                    trace_record["held"] = True
                    trace_record["hold_reason_code"] = decision_result.winner.reason_code
                    return resolved_mode
            for cover in layer.get("covers", []):
                before = len(runtime.targets)
                cover_decision_result = decision_result
                cover_mode = resolved_mode
                cover_position = position
                cover_tilt = tilt
                if decision_result is not None:
                    pause = self.cover_pause_info(cover)
                    local_pause_active = bool(
                        pause.get("active")
                        and resolved_mode != MODE_SAFETY
                    )
                    if facts is None:
                        cover_decision_result = (
                            self.decision_pipeline.evaluate(
                                self._advanced_decision_context(
                                    room,
                                    runtime,
                                    runtime.last_evaluation
                                    or dt_util.now(),
                                    mode=mode,
                                    sector=sector,
                                    layer=layer,
                                    cover_entity=str(
                                        cover.get("entity") or ""
                                    ),
                                    local_pause_active=local_pause_active,
                                )
                            )
                        )
                    else:
                        cover_decision_result = (
                            self._resolve_advanced_decision(
                                room,
                                runtime,
                                runtime.last_evaluation
                                or dt_util.now(),
                                facts=facts,
                                sector=sector,
                                layer=layer,
                                cover_entity=str(
                                    cover.get("entity") or ""
                                ),
                                local_pause_active=local_pause_active,
                            )
                        )
                    cover_mode = cover_decision_result.mode
                    if self._mode_priority(cover_mode) > self._mode_priority(
                        highest_resolved_mode
                    ):
                        highest_resolved_mode = cover_mode
                    cover_position, cover_tilt = self._targets(
                        layer, cover_mode, elevation
                    )
                    if cover_decision_result.target is not None:
                        if (
                            cover_decision_result.target.position
                            is not None
                        ):
                            cover_position = (
                                cover_decision_result.target.position
                            )
                        if cover_decision_result.target.tilt is not None:
                            cover_tilt = cover_decision_result.target.tilt
                if cover_mode in {MODE_IDLE, MODE_PAUSED, MODE_DISABLED}:
                    if cover_decision_result is not None and trace_record is not None:
                        trace_record["covers"].append(
                            {
                                "cover_id": self._cover_id(cover),
                                "entity_id": cover.get("entity"),
                                "command": cover_decision_result.as_dict(),
                                "held": True,
                            }
                        )
                    continue
                cover_reason = (
                    "Direct sun reaches a configured protected area"
                    if cover_mode == MODE_GLARE
                    else reason
                )
                await self._apply_cover(
                    room,
                    sector,
                    layer,
                    cover,
                    runtime,
                    cover_mode,
                    cover_position,
                    cover_tilt,
                    cover_reason,
                )
                if cover_decision_result is None or trace_record is None:
                    continue
                for target_record in runtime.targets[before:]:
                    status = target_record.get(
                        "command_result", CommandResult.PLANNED.value
                    )
                    command_trace = self._decision_with_command_result(
                        cover_decision_result,
                        status=status,
                        reason_code=str(
                            target_record.get("command_reason_code")
                            or target_record.get("reason_code")
                            or "command_adapter_result"
                        ),
                        details={
                            "cover_id": self._cover_id(cover),
                            "entity_id": cover.get("entity"),
                            "lifecycle_id": target_record.get("lifecycle_id"),
                        },
                    )
                    protected = command_trace.trace.protected_zones
                    target_record["decision_mode"] = command_trace.mode
                    target_record["protected_zone_hit_ids"] = [
                        item.zone_id for item in protected if item.hit
                    ]
                    target_record["protected_zone_applied_ids"] = list(
                        command_trace.trace.winner.details.get(
                            "protected_zone_applied_ids", ()
                        )
                    )
                    target_record["protected_zone_calculations"] = [
                        item.as_dict() for item in protected
                    ]
                    target_record["ordinary_target"] = (
                        command_trace.trace.winner.details.get(
                            "ordinary_target"
                        )
                    )
                    target_record["final_target"] = (
                        command_trace.target.as_dict()
                        if command_trace.target is not None
                        else None
                    )
                    trace_record["covers"].append(
                        {
                            "cover_id": self._cover_id(cover),
                            "entity_id": cover.get("entity"),
                            "command": command_trace.as_dict(),
                        }
                    )
        return highest_resolved_mode

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
                return value(
                    "comfort_position", float(defaults["comfort_position"])
                ), value("comfort_tilt", float(defaults["comfort_tilt"]))
            if mode == MODE_SOLAR:
                return value(
                    "solar_position", float(defaults["solar_position"])
                ), adaptive(float(defaults["solar_tilt"]))
            if mode == MODE_HEAT:
                return value(
                    "heat_position", float(defaults["heat_position"])
                ), value("heat_tilt", float(defaults["heat_tilt"]))
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

    @staticmethod
    def _simulation_boolean(value: Any) -> bool | None:
        """Parse a virtual binary value without treating unknown as false."""
        if isinstance(value, bool):
            return value
        token = str(value or "").strip().lower()
        if token in {"1", "on", "true", "open", "yes"}:
            return True
        if token in {"0", "off", "false", "closed", "no"}:
            return False
        return None

    def _simulation_cover_input(
        self,
        snapshot: InputSnapshot,
        cover: dict[str, Any],
        field: str,
        *aliases: str,
    ) -> InputValue | None:
        """Find a scoped virtual cover input, then an intentional global one.

        Scenario inputs use ``cover:<cover-id>:<field>`` (or the cover entity
        in place of the ID).  A bare field is useful when a developer wants to
        model every configured cover with one window/lock condition.  Invalid
        supplied inputs remain observable to the projection rather than being
        silently substituted with a live state.
        """
        cover_id = self._cover_id(cover)
        entity_id = str(cover.get("entity") or "")
        fields = (field, *aliases)
        for identifier in (cover_id, entity_id):
            if not identifier:
                continue
            for token in fields:
                value = snapshot.get(f"cover:{identifier}:{token}")
                if value.quality is not QualityState.NOT_CONFIGURED:
                    return value
        for token in fields:
            value = snapshot.get(token)
            if value.quality is not QualityState.NOT_CONFIGURED:
                return value
        return None

    def _simulation_cover_targets(
        self,
        room: dict[str, Any],
        sector: dict[str, Any],
        layer: dict[str, Any],
        result,
        snapshot: InputSnapshot,
    ) -> list[dict[str, Any]]:
        """Project logical simulation output through real cover constraints.

        This adapter is intentionally read-only: it mirrors profile mapping,
        inversion, local ownership pauses, locks, window policy, maximum-open
        limits and tolerance suppression, but never calls the command planner.
        It lets a scenario prove that a virtual unsafe window would block a
        specific cover while preserving the same logical room decision.
        """
        profile = str(layer.get("profile", DEVICE_VENETIAN))
        logical_target = result.target
        mode = str(result.mode or MODE_IDLE)
        projections: list[dict[str, Any]] = []
        for cover in layer.get("covers", []):
            if not isinstance(cover, dict):
                continue
            cover_id = self._cover_id(cover)
            entity_id = str(cover.get("entity") or "")
            target_position = (
                clamp_percent(logical_target.position)
                if logical_target and logical_target.position is not None
                else None
            )
            target_tilt = (
                clamp_percent(logical_target.tilt)
                if logical_target and logical_target.tilt is not None
                else None
            )
            if (
                target_position is not None
                and mode != MODE_SAFETY
                and profile != DEVICE_BINARY
                and self._maximum_opening_enabled(room, layer, cover)
            ):
                try:
                    target_position = min(
                        target_position,
                        clamp_percent(float(cover.get("max_open_position", 100.0))),
                    )
                except (TypeError, ValueError):
                    target_position = min(target_position, 100.0)
            command_position = (
                100.0 - target_position
                if target_position is not None and cover.get("invert_position", False)
                else target_position
            )
            command_tilt = (
                100.0 - target_tilt
                if target_tilt is not None and cover.get("invert_tilt", False)
                else target_tilt
            )

            state = self.hass.states.get(entity_id) if entity_id else None
            current_position = parse_numeric_value(
                state.attributes.get("current_position") if state else None
            )
            current_tilt = parse_numeric_value(
                state.attributes.get("current_tilt_position") if state else None
            )
            if profile == DEVICE_BINARY and state is not None and current_position is None:
                if state.state == "open":
                    current_position = 100.0
                elif state.state == "closed":
                    current_position = 0.0
            virtual_position = self._simulation_cover_input(
                snapshot, cover, "current_position", "position"
            )
            virtual_tilt = self._simulation_cover_input(
                snapshot, cover, "current_tilt", "tilt"
            )
            if virtual_position is not None:
                current_position = (
                    parse_numeric_value(virtual_position.value)
                    if virtual_position.valid
                    else None
                )
            if virtual_tilt is not None:
                current_tilt = (
                    parse_numeric_value(virtual_tilt.value)
                    if virtual_tilt.valid
                    else None
                )

            suppressions: list[str] = []
            pause = self.cover_pause_info(cover)
            virtual_pause = self._simulation_cover_input(
                snapshot, cover, "pause_active", "cover_pause", "pause"
            )
            pause_active = bool(pause["active"])
            if virtual_pause is not None:
                parsed_pause = (
                    self._simulation_boolean(virtual_pause.value)
                    if virtual_pause.valid
                    else None
                )
                pause_active = True if parsed_pause is None else parsed_pause
            if pause_active and mode != MODE_SAFETY:
                suppressions.append("cover_paused_until_morning")

            lock = str(cover.get("lock") or "")
            virtual_lock = self._simulation_cover_input(
                snapshot, cover, "lock_active", "lock"
            )
            lock_active = bool(lock and _is_on(self.hass, lock))
            if virtual_lock is not None:
                parsed_lock = (
                    self._simulation_boolean(virtual_lock.value)
                    if virtual_lock.valid
                    else None
                )
                lock_active = True if parsed_lock is None else parsed_lock
            if lock_active and mode != MODE_SAFETY:
                suppressions.append("automation_lock")

            window = str(cover.get("window") or "")
            window_safe_state = str(cover.get("window_safe_state", "on"))
            virtual_window_safe = self._simulation_cover_input(
                snapshot, cover, "window_safe"
            )
            virtual_window_state = self._simulation_cover_input(
                snapshot, cover, "window_state", "window"
            )
            window_safe = (
                not window or self.hass.states.is_state(window, window_safe_state)
            )
            window_input_invalid = False
            if virtual_window_safe is not None:
                parsed_safe = (
                    self._simulation_boolean(virtual_window_safe.value)
                    if virtual_window_safe.valid
                    else None
                )
                window_input_invalid = parsed_safe is None
                window_safe = bool(parsed_safe) if parsed_safe is not None else False
            elif virtual_window_state is not None:
                if virtual_window_state.valid:
                    state_value = virtual_window_state.value
                    if isinstance(state_value, bool):
                        state_value = "on" if state_value else "off"
                    window_safe = str(state_value).strip().lower() == window_safe_state.lower()
                else:
                    window_input_invalid = True
                    window_safe = False
            if window and not window_safe and mode != MODE_SAFETY:
                policy = cover.get("window_policy", WINDOW_POLICY_BLOCK_CLOSING)
                if policy == WINDOW_POLICY_BLOCK_ALL:
                    suppressions.append("unsafe_window")
                elif (
                    policy == WINDOW_POLICY_BLOCK_CLOSING
                    and (
                        command_position is None
                        or current_position is None
                        or command_position < current_position
                    )
                ):
                    suppressions.append("unsafe_window_closing_blocked")
                if window_input_invalid:
                    suppressions.append("window_state_unavailable")

            position_tolerance, tilt_tolerance = self._layer_tolerances(layer)
            position_needed = bool(
                command_position is not None
                and (
                    current_position is None
                    or abs(current_position - command_position) > position_tolerance
                )
            )
            tilt_needed = bool(
                command_tilt is not None
                and (
                    current_tilt is None
                    or abs(current_tilt - command_tilt) > tilt_tolerance
                )
            )
            movement_needed = position_needed or tilt_needed
            if suppressions:
                command_status = CommandResult.BLOCKED.value
                command_reason = suppressions[0]
            elif logical_target is None:
                command_status = CommandResult.SUPPRESSED.value
                command_reason = "no_cover_target"
            elif not movement_needed:
                command_status = CommandResult.SUPPRESSED.value
                command_reason = "target_within_tolerance"
            else:
                command_status = CommandResultStatus.SIMULATED.value
                command_reason = "simulation_never_executes_services"
            projections.append(
                {
                    "cover_id": cover_id,
                    "entity_id": entity_id,
                    "name": cover.get("name") or entity_id or cover_id,
                    "sector_id": str(sector.get("id") or ""),
                    "layer_id": str(layer.get("id") or ""),
                    "profile": profile,
                    "mode": mode,
                    "logical_target": (
                        logical_target.as_dict() if logical_target is not None else None
                    ),
                    "position": target_position,
                    "tilt": target_tilt,
                    "command_position": command_position,
                    "command_tilt": command_tilt,
                    "current_position": current_position,
                    "current_tilt": current_tilt,
                    "constraints": list(dict.fromkeys(suppressions)),
                    "command_result": command_status,
                    "reason_code": command_reason,
                    "simulation": True,
                }
            )
        return projections

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
        ordinary_position = target_position
        maximum_opening_enabled = self._maximum_opening_enabled(
            room, layer, cover
        )
        maximum_opening = clamp_percent(
            float(cover.get("max_open_position", 100.0))
        )
        if (
            mode != MODE_SAFETY
            and profile != DEVICE_BINARY
            and maximum_opening_enabled
        ):
            target_position = min(target_position, maximum_opening)

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
        logical_current_position = (
            (
                100.0 - float(current_position)
                if cover.get("invert_position", False)
                else float(current_position)
            )
            if current_position is not None
            else None
        )
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
            "ordinary_position": ordinary_position,
            "position": target_position,
            "command_position": displayed_position,
            "current_position": current_position,
            "logical_current_position": logical_current_position,
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
            "maximum_opening": {
                "enabled": maximum_opening_enabled,
                "limit": maximum_opening if maximum_opening_enabled else None,
                "constrained": bool(
                    maximum_opening_enabled
                    and target_position < ordinary_position
                ),
                "effective_position": target_position,
                "current_position": logical_current_position,
                "violation": bool(
                    maximum_opening_enabled
                    and logical_current_position is not None
                    and logical_current_position
                    > maximum_opening + DEFAULT_MAX_OPEN_TOLERANCE
                ),
            },
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

        # The executor owns physical sequencing, suppression, verification and
        # persisted ownership.  The legacy direct-service code below remains
        # as a narrow compatibility fallback for tests that intentionally
        # replace the planner, but normal runtime never bypasses this layer.
        if self.command_planner is not None:
            await self._apply_cover_with_planner(
                room=room,
                sector=sector,
                layer=layer,
                cover=cover,
                runtime=runtime,
                mode=mode,
                reason=reason,
                target_record=target_record,
                suppressions=suppressions,
                current_position=parse_numeric_value(current_position),
                current_tilt=parse_numeric_value(current_tilt),
                target_position=displayed_position,
                target_tilt=displayed_tilt,
                position_tolerance=position_tolerance,
                tilt_tolerance=tilt_tolerance,
                movement_needed=movement_needed,
                state=state,
            )
            return

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

    async def _apply_cover_with_planner(
        self,
        *,
        room: dict[str, Any],
        sector: dict[str, Any],
        layer: dict[str, Any],
        cover: dict[str, Any],
        runtime: RoomRuntime,
        mode: str,
        reason: str,
        target_record: dict[str, Any],
        suppressions: list[str],
        current_position: float | None,
        current_tilt: float | None,
        target_position: float | None,
        target_tilt: float | None,
        position_tolerance: float,
        tilt_tolerance: float,
        movement_needed: bool,
        state,
    ) -> None:
        """Adapt one resolved target to the pure command planner.

        Constraints remain visible in ``target_record``; the planner merely
        makes their effect finite, cancelable and persistent.  This keeps the
        decision layer free of Home Assistant service calls.
        """
        entity_id = str(cover.get("entity") or "")
        cover_id = self._cover_id(cover)
        profile = str(layer.get("profile", DEVICE_VENETIAN))
        constraints = list(suppressions)
        nonblocking_suppressions: list[str] = []
        supported_features = int(
            state.attributes.get("supported_features", 0) if state else 0
        )
        can_set_position = bool(
            supported_features & int(CoverEntityFeature.SET_POSITION)
        )
        can_set_tilt = bool(
            supported_features & int(CoverEntityFeature.SET_TILT_POSITION)
        )
        if (
            target_position is not None
            and current_position is None
            and profile != DEVICE_BINARY
            and not can_set_position
        ):
            constraints.append("position_control_unsupported")
        if (
            target_tilt is not None
            and current_tilt is None
            and profile != DEVICE_BINARY
            and not can_set_tilt
        ):
            # A missing slat capability must not prevent a compatible height
            # target from being sent.  The requested tilt stays visible in
            # the runtime record, while the planner receives only the axis it
            # can safely execute.
            nonblocking_suppressions.append("tilt_control_unsupported")
            target_tilt = None

        verification = bool(
            self.advanced_mode
            and (
                cover.get("verify_target", False)
                or room.get("target_verification_enabled", False)
                or (
                    mode == MODE_SAFETY
                    and room.get("safety_target_verification_enabled", False)
                )
            )
        )
        try:
            movement_seconds = max(
                0.0,
                float(layer.get("movement_seconds", room.get("movement_seconds", 45.0))),
            )
            settle_seconds = max(
                0.0,
                float(layer.get("settling_seconds", room.get("settling_seconds", 5.0))),
            )
            retries = max(0, int(room.get("verification_retries", 1)))
            stagger_seconds = max(
                0.0, float(room.get("command_stagger_seconds", 0.0))
            )
        except (TypeError, ValueError):
            movement_seconds, settle_seconds, retries, stagger_seconds = (
                45.0,
                5.0,
                1,
                0.0,
            )
        # Customer configuration deliberately has only two scopes.  A room
        # scope must use the stable room ID (not the literal token ``room``,
        # which would accidentally serialize every room into one queue),
        # while the house scope intentionally shares one global reservation.
        stagger_scope = (
            "house"
            if str(room.get("stagger_scope", "room") or "room").strip().lower()
            == "house"
            else runtime.room_id
        )

        request = CommandRequest(
            cover_id=cover_id,
            profile=profile,
            target=CommandTarget(position=target_position, tilt=target_tilt),
            rule=mode,
            reason_code=self._reason_code_for_mode(mode, reason),
            context=CommandContext(
                room_id=runtime.room_id,
                sector_id=str(sector.get("id") or "") or None,
                group_id=str(layer.get("id") or "") or None,
            ),
            priority=self._command_priority(mode),
            current_position=current_position,
            current_tilt=current_tilt,
            position_tolerance=position_tolerance,
            tilt_tolerance=tilt_tolerance,
            feedback_quality=self._feedback_quality(
                cover.get("feedback_quality", "trusted"),
                verification=verification,
            ),
            verification_delay=timedelta(seconds=movement_seconds + settle_seconds),
            retry_limit=retries,
            settle_delay=timedelta(seconds=settle_seconds),
            # Easy has no hidden execution controls, even when a crafted
            # payload bypasses config normalization.  The planner validates
            # Advanced values again and falls back to height-before-tilt.
            opening_order=(
                str(
                    layer.get("opening_order", "height_then_tilt")
                    or "height_then_tilt"
                )
                if self.advanced_mode
                else "height_then_tilt"
            ),
            constraint_reasons=tuple(dict.fromkeys(constraints)),
            stagger_seconds=stagger_seconds,
            stagger_scope=stagger_scope,
            safety=mode == MODE_SAFETY,
            safety_bypasses_stagger=(
                room.get("safety_bypasses_stagger")
                if isinstance(room.get("safety_bypasses_stagger"), bool)
                else True
            ),
            allow_automatic_reverse=bool(
                self.advanced_mode and cover.get("allow_automatic_reverse") is True
            ),
            # This request comes from the newest complete, serialized room
            # evaluation.  It may therefore replace a still-travelling
            # lifecycle whose higher-priority source has since cleared.
            authoritative_replacement=True,
        )
        result = self.command_planner.plan(request, now=dt_util.now())
        target_record.update(
            {
                "cover_id": cover_id,
                "reason_code": request.reason_code,
                "command_result": result.status.value,
                "command_reason_code": result.reason_code,
                "commands_sent": 0,
                "queued_until": (
                    result.steps[0].execute_at.isoformat()
                    if result.steps and result.steps[0].execute_at > dt_util.now()
                    else None
                ),
                "ownership": (
                    result.ledger.owned_by_smart_shading
                    if result.ledger is not None
                    else False
                ),
                "lifecycle_id": (
                    result.ledger.lifecycle_id if result.ledger is not None else None
                ),
            }
        )
        if result.status is CommandResult.BLOCKED:
            target_record["suppressed"] = (
                constraints + nonblocking_suppressions
            ) or [result.reason_code]
            if movement_needed:
                runtime.suppressed_commands += 1
        elif result.status is CommandResult.SUPPRESSED:
            target_record["suppressed"] = [
                *nonblocking_suppressions,
                result.reason_code,
            ]
        elif result.status is CommandResult.QUEUED:
            target_record["suppressed"] = nonblocking_suppressions
            self._diag(
                "cover_command_queued",
                room_id=runtime.room_id,
                cover=target_record.get("name") or entity_id,
                mode=mode,
                execute_at=target_record["queued_until"],
                lifecycle_id=target_record["lifecycle_id"],
            )
        else:
            target_record["suppressed"] = nonblocking_suppressions
        runtime.targets.append(target_record)
        if result.cancelled_steps:
            self._diag(
                "cover_command_cancelled",
                full=True,
                room_id=runtime.room_id,
                cover=target_record.get("name") or entity_id,
                reason="replaced_by_newer_target",
                cancelled_steps=[step.step_id for step in result.cancelled_steps],
            )
        if result.status in {CommandResult.BLOCKED, CommandResult.SUPPRESSED}:
            self._diag(
                "cover_command_suppressed",
                full=result.status is CommandResult.SUPPRESSED,
                room_id=runtime.room_id,
                cover=target_record.get("name") or entity_id,
                mode=mode,
                reasons=list(target_record["suppressed"]),
            )
        await self._persist_command_planner()
        await self._dispatch_due_command_steps()
        self._schedule_command_executor_timers()

    @staticmethod
    def _reason_code_for_mode(mode: str, reason: str) -> str:
        """Return a stable code rather than making trace consumers parse prose."""
        codes = {
            MODE_SAFETY: "safety_active",
            MODE_DISABLED: "manual_master_override",
            MODE_PAUSED: "room_or_cover_pause_active",
            MODE_NIGHT: "night_mode_active",
            MODE_HEAT: "heat_protection_active",
            MODE_GLARE: "protected_zone_target_adjusted",
            MODE_SOLAR: "solar_conditions_matched",
            MODE_COMFORT: "comfort_conditions_matched",
            MODE_OPEN: "open_target_selected",
            MODE_IDLE: "conditions_waiting",
        }
        return codes.get(mode, "decision_selected")

    async def _save_room_runtime(self, runtime: RoomRuntime) -> None:
        # Always rebuild the persisted trace from the final runtime mode.  A
        # room can return early for Safety, Pause, Night, schedule holds or an
        # unavailable source, so wiring this to the common save path guarantees
        # an explainable winner for every Advanced evaluation.
        self._refresh_advanced_decision_trace(runtime)
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
                "heat_phase": runtime.heat_phase,
                "shading_active": runtime.shading_active,
                "finished_today": runtime.finished_today,
                "sent_commands": runtime.sent_commands,
                "suppressed_commands": runtime.suppressed_commands,
            },
        )
        if runtime.decision_trace:
            await self.store.async_save_decision_trace(
                runtime.room_id, runtime.decision_trace
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
