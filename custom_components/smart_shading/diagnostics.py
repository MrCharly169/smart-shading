from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data

from .const import VERSION


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
    return {
        "configuration": async_redact_data(engine.config, []),
        "diagnostic_level": engine.diagnostic_level,
        "diagnostic_journal": engine.recent_diagnostics(limit=500),
        "schema_version": 3,
        "integration_version": VERSION,
        "evaluation_interval_seconds": engine.config.get("evaluation_interval", 1200),
        "test_mode_legacy": engine.test_mode,
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
                "last_evaluation": runtime.last_evaluation,
                "last_command": runtime.last_command,
                "sent_commands": runtime.sent_commands,
                "suppressed_commands": runtime.suppressed_commands,
                "heat_active": runtime.heat_active,
                "shading_active": runtime.shading_active,
                "finished_today": runtime.finished_today,
                "pause_mode": runtime.pause_mode,
                "pause_until": runtime.pause_until,
                "manual_master_active": not runtime.enabled,
                "schedule_active": runtime.schedule_active,
                "schedule_reason": runtime.schedule_reason,
                "next_schedule_change": runtime.next_schedule_change,
            }
            for room_id, runtime in engine.rooms.items()
        },
        "cover_pauses": {
            cover_id: {
                "active": pause.active,
                "until": pause.until,
                "reason": pause.reason,
                "lock_owned": pause.lock_owned,
                "entity_id": pause.entity_id,
                "room_id": pause.room_id,
            }
            for cover_id, pause in engine.cover_pauses.items()
        },
        "sun_presence": {
            sector_id: {
                "is_on": runtime.is_on,
                "source": engine._configured_sun_source(
                    engine.sector_config(sector_id)
                ),
                "source_valid": runtime.source_valid,
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
                "mode": runtime.mode,
                "lux_state": _state_snapshot(
                    hass, engine.sector_config(sector_id).get("lux_sensor", "")
                ),
                "external_state": _state_snapshot(
                    hass,
                    engine.sector_config(sector_id).get(
                        "sun_presence_entity", ""
                    ),
                ),
            }
            for sector_id, runtime in engine.sun_runtime.items()
        },
    }
