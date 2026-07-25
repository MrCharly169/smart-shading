from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data

from .const import (
    DEFAULT_MAX_OPEN_HEARTBEAT_SECONDS,
    DEFAULT_MAX_OPEN_TOLERANCE,
    VERSION,
)


def _state_snapshot(hass, entity_id: str) -> dict | None:
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None:
        return {"entity_id": entity_id, "state": None, "available": False}
    return {
        "entity_id": entity_id,
        "state": state.state,
        "available": state.state not in {"unknown", "unavailable"},
        "unit": state.attributes.get("unit_of_measurement"),
        "device_class": state.attributes.get("device_class"),
        "current_position": state.attributes.get("current_position"),
        "current_tilt_position": state.attributes.get("current_tilt_position"),
    }


async def async_get_config_entry_diagnostics(hass, entry):
    engine = entry.runtime_data
    configured_entities = sorted(engine.referenced_entities())
    advanced = bool(engine.advanced_mode)
    planner = getattr(engine, "command_planner", None)
    command_ledger = (
        planner.export_ledger() if planner is not None else {}
    )
    queued_commands = (
        planner.export_pending_steps() if planner is not None else []
    )
    return {
        "configuration": async_redact_data(engine.config, []),
        "diagnostic_level": engine.diagnostic_level,
        "diagnostic_journal": engine.recent_diagnostics(limit=500),
        "schema_version": 8,
        "integration_version": VERSION,
        "evaluation_interval_seconds": engine.config.get("evaluation_interval", 1200),
        "evaluation_debounce_seconds": engine.config.get(
            "evaluation_debounce_seconds", 0.35
        ),
        "decision_runtime": {
            "event_driven": True,
            "watchdog_interval_seconds": engine.config.get("evaluation_interval", 1200),
            "maximum_opening_feedback_check": (
                "immediate_on_cover_state_change"
            ),
            "maximum_opening_heartbeat_seconds": (
                DEFAULT_MAX_OPEN_HEARTBEAT_SECONDS
            ),
            "maximum_opening_tolerance_percent": (
                DEFAULT_MAX_OPEN_TOLERANCE
            ),
            "command_ledger": command_ledger if advanced else {},
            "queued_commands": queued_commands if advanced else [],
        },
        "input_states": {
            entity_id: _state_snapshot(hass, entity_id)
            for entity_id in configured_entities
        },
        "rooms": {
            room_id: {
                "name": runtime.name,
                "mode": runtime.mode,
                "reason": runtime.reason,
                "active_sectors": runtime.active_sectors,
                "targets": runtime.targets,
                "protected_zone_calculations": [
                    {
                        "cover_entity": target.get("entity_id"),
                        "cover_name": target.get("name"),
                        "ordinary_target": target.get("ordinary_target"),
                        "final_target": target.get("final_target"),
                        "zones": target.get(
                            "protected_zone_calculations", []
                        ),
                    }
                    for target in runtime.targets
                    if target.get("protected_zone_calculations")
                ],
                "maximum_opening_calculations": [
                    {
                        "cover_entity": target.get("entity_id"),
                        "cover_name": target.get("name"),
                        "normal_target": target.get("ordinary_position"),
                        "opening_limit": target.get(
                            "maximum_opening", {}
                        ).get("limit"),
                        "effective_target": target.get(
                            "maximum_opening", {}
                        ).get("effective_position"),
                        "current_position": target.get(
                            "maximum_opening", {}
                        ).get("current_position"),
                        "constrained": target.get(
                            "maximum_opening", {}
                        ).get("constrained"),
                        "violation": target.get(
                            "maximum_opening", {}
                        ).get("violation"),
                    }
                    for target in runtime.targets
                    if target.get("maximum_opening", {}).get("enabled")
                ],
                "last_evaluation": runtime.last_evaluation,
                "last_command": runtime.last_command,
                "sent_commands": runtime.sent_commands,
                "suppressed_commands": runtime.suppressed_commands,
                "heat_active": runtime.heat_active,
                "heat_phase": getattr(runtime, "heat_phase", "inactive"),
                "shading_active": runtime.shading_active,
                "finished_today": runtime.finished_today,
                "pause_mode": runtime.pause_mode,
                "pause_until": runtime.pause_until,
                "manual_master_active": not runtime.enabled,
                "manual_override_groups": (
                    engine.manual_override_groups(room_id)
                    if engine.advanced_mode
                    else []
                ),
                "schedule_active": runtime.schedule_active,
                "schedule_reason": runtime.schedule_reason,
                "next_schedule_change": runtime.next_schedule_change,
                "night_active": runtime.night_active,
                "night_blocked": runtime.night_blocked,
                "night_reason": runtime.night_reason,
                "night_source_state": runtime.night_source_state,
                "night_next_transition": runtime.night_next_transition,
                "night_morning_hold_until": runtime.night_morning_hold_until,
                "night_morning_handover_pending": (
                    runtime.night_morning_handover_pending
                ),
                "easy_confirmation_state": runtime.easy_confirmation_state,
                "easy_source_summary": runtime.easy_source_summary,
                "decision_trace": (
                    getattr(runtime, "decision_trace", {}) if advanced else {}
                ),
                "simulation_active": bool(
                    advanced and getattr(runtime, "simulation_active", False)
                ),
                "simulation_trace": (
                    getattr(runtime, "simulation_trace", {}) if advanced else {}
                ),
                "day_preview": (
                    getattr(runtime, "day_preview", {}) if advanced else {}
                ),
                "outdoor_temperature_condition": {
                    "enabled": runtime.outdoor_temperature_condition_enabled,
                    "source_entity": runtime.outdoor_temperature_source,
                    "value": runtime.outdoor_temperature_value,
                    "minimum": runtime.outdoor_temperature_minimum,
                    "passed": runtime.outdoor_temperature_passed,
                },
            }
            for room_id, runtime in engine.rooms.items()
        },
        "cover_pauses": {
            cover_id: {
                "active": pause.active,
                "until": pause.until,
                "reason": pause.reason,
                "pause_mode": pause.pause_mode,
                "waiting_for_night": pause.waiting_for_night,
                "lock_owned": pause.lock_owned,
                "entity_id": pause.entity_id,
                "room_id": pause.room_id,
            }
            for cover_id, pause in engine.cover_pauses.items()
        },
        "cover_motion_detection": {
            entity_id: {
                "phase": observation.phase,
                "numeric_feedback": {
                    "position_available": observation.last_position is not None,
                    "tilt_available": observation.last_tilt is not None,
                },
                "baseline_position": observation.baseline_position,
                "baseline_tilt": observation.baseline_tilt,
                "last_position": observation.last_position,
                "last_tilt": observation.last_tilt,
                "last_state_informational_only": observation.last_state,
                "candidate_axis": observation.candidate_axis,
                "candidate_direction": observation.candidate_direction,
                "candidate_started_at": observation.candidate_started_at,
                "candidate_last_changed_at": observation.candidate_last_changed_at,
                "candidate_start_position": observation.candidate_start_position,
                "candidate_start_tilt": observation.candidate_start_tilt,
                "candidate_latest_position": observation.candidate_latest_position,
                "candidate_latest_tilt": observation.candidate_latest_tilt,
                "candidate_changed_updates": observation.candidate_updates,
                "candidate_stable_updates": observation.candidate_stable_updates,
                "stability_timer_pending": entity_id
                in getattr(engine, "_external_candidate_timer_unsubs", {}),
                "last_decision_reason": observation.last_decision_reason,
            }
            for entity_id, observation in getattr(engine, "cover_motion", {}).items()
        },
        "window_automation_contexts": {
            entity_id: {
                "window_entity_id": context.window_entity_id,
                "phase": context.phase,
                "started_at": context.started_at,
                "expires_at": context.expires_at,
                "last_feedback_at": context.last_feedback_at,
            }
            for entity_id, context in getattr(
                engine, "window_automation_contexts", {}
            ).items()
        },
        "sun_presence": {
            sector_id: {
                "is_on": runtime.is_on,
                "current_lux": runtime.current_lux,
                "effective_settings": engine._sun_settings(sector_id),
                "pending_target": runtime.pending_target,
                "pending_since": runtime.pending_since,
                "pending_until": runtime.pending_until,
                "last_transition": runtime.last_transition,
                "reason": runtime.reason,
                "status": runtime.status,
                "status_reason": runtime.status_reason,
                "geometry_active": runtime.geometry_active,
                "shading_active": runtime.shading_active,
                "confirmation_source": runtime.confirmation_source,
                "confirmation_entity": runtime.confirmation_entity,
                "confirmation_state": runtime.confirmation_state,
                "effective_active": runtime.effective_active,
                "mode": runtime.mode,
                "sun_presence_state": _state_snapshot(
                    hass,
                    engine.sector_config(sector_id).get(
                        "sun_presence_entity", ""
                    ),
                ),
                "lux_state": _state_snapshot(
                    hass, engine.sector_config(sector_id).get("lux_sensor", "")
                ),
            }
            for sector_id, runtime in engine.sun_runtime.items()
        },
    }
