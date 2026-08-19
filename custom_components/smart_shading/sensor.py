from __future__ import annotations

from copy import deepcopy
import json

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers import entity_registry as er

from .const import (
    CARD_RESOURCE,
    DEFAULT_MAX_OPEN_HEARTBEAT_SECONDS,
    DEFAULT_MAX_OPEN_TOLERANCE,
    DEFAULT_SUN_ENTITY,
)
from .entity import SmartShadingEntity, localized


STATE_ATTRIBUTE_BUDGET = 15_500
STATUS_OPTIONS = [
    "idle",
    "open",
    "comfort",
    "solar",
    "glare",
    "heat",
    "night",
    "safety",
    "paused",
    "disabled",
    "finished",
]


def _status_icon(status: str) -> str:
    """Return the native entity icon for a dashboard status."""
    return {
        "idle": "mdi:blinds-horizontal",
        "open": "mdi:blinds-open",
        "comfort": "mdi:sun-angle",
        "solar": "mdi:weather-sunny-alert",
        "glare": "mdi:shield-sun-outline",
        "heat": "mdi:shield-sun",
        "night": "mdi:weather-night",
        "safety": "mdi:shield-alert",
        "paused": "mdi:pause-circle",
        "disabled": "mdi:power",
        "finished": "mdi:calendar-check",
    }.get(status, "mdi:blinds-horizontal")


def _compact_cover(cover: dict) -> dict:
    return {
        key: cover.get(key)
        for key in (
            "id", "entity", "name", "short", "lock", "window",
            "window_safe_state", "enforce_max_open_position",
            "max_open_position",
        )
        if cover.get(key) not in (None, "")
    }


def _compact_room_configuration(room: dict) -> dict:
    """Return only configuration fields rendered by the public status Card."""
    return {
        key: room.get(key)
        for key in (
            "id", "name", "indoor_temperature", "outdoor_temperature",
            "normal_shading_temperature", "comfort_temperature",
            "heat_temperature", "advanced_features", "night_enabled",
            "night_source", "schedule_enabled",
        )
        if room.get(key) not in (None, "")
    } | {
        "safety_blockers": list(room.get("safety_blockers", [])),
        "sectors": [
            {
                key: sector.get(key)
                for key in (
                    "id", "name", "short", "azimuth_start", "azimuth_end",
                    "elevation_min", "lux_sensor", "sun_presence_entity",
                )
                if sector.get(key) not in (None, "")
            }
            | {
                "protected_zones": [
                    {
                        key: zone.get(key)
                        for key in (
                            "id", "name", "enabled", "cover_entity",
                            "calculation_mode",
                        )
                        if zone.get(key) not in (None, "")
                    }
                    for zone in sector.get("protected_zones", [])
                    if isinstance(zone, dict)
                ],
                "layers": [
                    {
                        key: layer.get(key)
                        for key in ("id", "name", "profile")
                        if layer.get(key) not in (None, "")
                    }
                    | {
                        "covers": [
                            _compact_cover(cover)
                            for cover in layer.get("covers", [])
                        ]
                    }
                    for layer in sector.get("layers", [])
                ]
            }
            for sector in room.get("sectors", [])
        ],
    }


def _compact_target(target: dict) -> dict:
    compact = {
        key: target.get(key)
        for key in (
            "entity_id", "name", "mode", "decision_mode", "position", "tilt",
            "ordinary_position", "ordinary_target", "final_target", "layer",
            "layer_id",
        )
        if target.get(key) is not None
    }
    compact["suppressed"] = list(target.get("suppressed", []))[:4]
    maximum = target.get("maximum_opening")
    if isinstance(maximum, dict) and maximum.get("enabled"):
        compact["maximum_opening"] = {
            key: maximum.get(key)
            for key in (
                "enabled", "limit", "effective_position", "current_position",
                "constrained", "violation",
            )
            if maximum.get(key) is not None
        }
    zones = target.get("protected_zone_calculations")
    if isinstance(zones, list):
        compact["protected_zone_calculations"] = [
            _compact_protected_zone(zone)
            for zone in zones[:3]
            if isinstance(zone, dict)
        ]
        compact["protected_zone_applied_ids"] = list(
            target.get("protected_zone_applied_ids", [])
        )[:3]
    return compact


def _compact_protected_zone(zone: dict) -> dict:
    details = zone.get("details")
    if not isinstance(details, dict):
        details = {}
    compact = {
        key: deepcopy(zone.get(key))
        for key in (
            "zone_id", "name", "status", "reason_code", "target",
            "ordinary_target", "final_target", "projected_height_range_m",
        )
        if zone.get(key) is not None
    }
    compact_details = {
        key: deepcopy(details.get(key))
        for key in (
            "calculation", "calculated_position", "calculated_tilt",
            "relative_azimuth_degrees", "projected_height_range_m",
            "protected_height_range_m", "sun_vector", "valid",
        )
        if details.get(key) is not None
    }
    if compact_details:
        compact["details"] = compact_details
    return compact


def _compact_candidate(value) -> dict:
    if not isinstance(value, dict):
        return {}
    return {
        key: value.get(key)
        for key in ("rule", "mode", "reason_code", "target")
        if value.get(key) is not None
    }


def _compact_pure_trace(value) -> dict:
    if not isinstance(value, dict):
        return {}
    trace = value.get("trace") if isinstance(value.get("trace"), dict) else value
    inputs = trace.get("input_snapshot", {})
    raw_inputs = inputs.get("inputs", {}) if isinstance(inputs, dict) else {}
    return {
        "winner": _compact_candidate(trace.get("winner")),
        "entries": [
            {
                "candidate": _compact_candidate(entry.get("candidate")),
                "outcome": entry.get("outcome"),
                "resolution_reason_code": entry.get("resolution_reason_code"),
            }
            for entry in trace.get("entries", [])[:8]
            if isinstance(entry, dict)
        ],
        "rejected": [
            _compact_candidate(candidate)
            for candidate in trace.get("rejected", [])[:8]
        ],
        "input_snapshot": {
            "evaluated_at": inputs.get("evaluated_at")
            if isinstance(inputs, dict) else None,
            "inputs": {
                str(key): {
                    field: raw.get(field)
                    for field in (
                        "value", "raw_value", "unit", "quality", "reason_code",
                    )
                    if raw.get(field) is not None
                }
                for key, raw in list(raw_inputs.items())[:8]
                if isinstance(raw, dict)
            },
        },
        "command_result": {
            key: trace.get("command_result", {}).get(key)
            for key in ("status", "reason_code", "target")
            if isinstance(trace.get("command_result"), dict)
            and trace["command_result"].get(key) is not None
        },
        "protected_zones": [
            _compact_protected_zone(zone)
            for zone in trace.get("protected_zones", [])[:3]
            if isinstance(zone, dict)
        ],
    }


def _compact_decision_trace(value) -> dict:
    if not isinstance(value, dict) or not value:
        return {}
    compact = {
        key: value.get(key)
        for key in ("schema", "evaluated_at", "trigger", "room_id", "mode", "reason")
        if value.get(key) is not None
    }
    compact.update(_compact_pure_trace(value))
    compact["command_results"] = [
        {
            key: row.get(key)
            for key in ("cover_id", "status", "reason_code")
            if row.get(key) is not None
        }
        for row in value.get("command_results", [])[:8]
        if isinstance(row, dict)
    ]
    compact["target_decisions"] = [
        {
            key: row.get(key)
            for key in ("sector_id", "sector_name", "layer_id", "layer_name")
            if row.get(key) is not None
        }
        | {"trace": _compact_pure_trace(row.get("decision", row))}
        for row in value.get("target_decisions", [])[:4]
        if isinstance(row, dict)
    ]
    return compact


def _compact_simulation_trace(value) -> dict:
    if not isinstance(value, dict) or not value:
        return {}
    return {
        key: value.get(key)
        for key in (
            "schema", "available", "completed", "room_id", "simulated_at",
            "reason_code",
        )
        if value.get(key) is not None
    } | {
        "results": [
            {
                key: row.get(key)
                for key in (
                    "sector_id", "sector_name", "layer_id", "layer_name",
                    "mode", "status", "reason_code",
                )
                if row.get(key) is not None
            }
            | {
                "cover_targets": [
                    {
                        key: target.get(key)
                        for key in (
                            "cover_id", "entity_id", "name", "position", "tilt",
                            "command_position", "command_tilt", "command_result",
                            "reason_code", "constraints",
                        )
                        if target.get(key) is not None
                    }
                    for target in row.get("cover_targets", [])[:6]
                    if isinstance(target, dict)
                ],
                "result": {
                    "mode": row.get("result", {}).get("mode"),
                    "target": row.get("result", {}).get("target"),
                    "trace": _compact_pure_trace(row.get("result", {})),
                },
            }
            for row in value.get("results", [])[:4]
            if isinstance(row, dict)
        ]
    }


def _compact_day_preview(value) -> dict:
    if not isinstance(value, dict) or not value:
        return {}
    preview = value.get("preview")
    if not isinstance(preview, dict):
        preview = value.get("day_preview") if isinstance(value.get("day_preview"), dict) else value
    return {
        "day": preview.get("day") or preview.get("date") or value.get("date"),
        "transitions": [
            {
                key: transition.get(key)
                for key in (
                    "at", "time", "timestamp", "previous_mode", "mode",
                    "reason", "reason_code", "sector_id", "sector_name",
                )
                if transition.get(key) is not None
            }
            | {
                "target": {
                    key: transition.get("target", {}).get(key)
                    for key in ("position", "tilt")
                    if isinstance(transition.get("target"), dict)
                    and transition["target"].get(key) is not None
                }
            }
            for transition in preview.get("transitions", [])[:12]
            if isinstance(transition, dict)
        ],
    }


def _compact_diagnostic_events(events) -> list[dict]:
    fields = (
        "time", "timestamp", "created_at", "event", "type", "room", "cover",
        "mode", "previous", "reason", "status", "axis", "direction", "trigger",
        "level", "entity_id", "active_sectors", "targets",
    )
    return [
        {key: event.get(key) for key in fields if event.get(key) is not None}
        for event in list(events)[-8:]
        if isinstance(event, dict)
    ]


def _attribute_size(attributes: dict) -> int:
    return len(json.dumps(attributes, default=str, separators=(",", ":")).encode())


def _fit_attribute_budget(attributes: dict) -> dict:
    """Keep recorder-facing attributes below HA's hard 16-KB limit."""
    if _attribute_size(attributes) <= STATE_ATTRIBUTE_BUDGET:
        return attributes
    attributes["diagnostic_events"] = attributes.get("diagnostic_events", [])[-3:]
    if _attribute_size(attributes) <= STATE_ATTRIBUTE_BUDGET:
        return attributes
    attributes["simulation_trace"] = {}
    if _attribute_size(attributes) <= STATE_ATTRIBUTE_BUDGET:
        return attributes
    trace = attributes.get("decision_trace")
    if isinstance(trace, dict):
        trace.pop("target_decisions", None)
        trace.pop("entries", None)
        trace.pop("rejected", None)
        trace.pop("input_snapshot", None)
    if _attribute_size(attributes) <= STATE_ATTRIBUTE_BUDGET:
        return attributes
    attributes["diagnostic_events"] = []
    if _attribute_size(attributes) <= STATE_ATTRIBUTE_BUDGET:
        return attributes
    attributes["decision_trace"] = {}
    if _attribute_size(attributes) <= STATE_ATTRIBUTE_BUDGET:
        return attributes
    preview = attributes.get("day_preview")
    if isinstance(preview, dict):
        preview["transitions"] = preview.get("transitions", [])[:4]
    if _attribute_size(attributes) <= STATE_ATTRIBUTE_BUDGET:
        return attributes
    if isinstance(preview, dict):
        preview["transitions"] = []
    if _attribute_size(attributes) > STATE_ATTRIBUTE_BUDGET:
        attributes["configuration"] = {
            "id": attributes.get("configuration", {}).get("id"),
            "name": attributes.get("configuration", {}).get("name"),
            "configuration_truncated": True,
        }
    return attributes


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    engine = entry.runtime_data
    entities = [HouseStatusSensor(engine)]
    entities.extend(RoomStatusSensor(engine, room_id) for room_id in engine.rooms)
    if not engine.advanced_mode:
        async_add_entities(entities)
        return
    for room in engine.config.get("rooms", []):
        for sector in room.get("sectors", []):
            entities.append(SectorStatusSensor(engine, room["id"], sector["id"]))
    async_add_entities(entities)


class HouseStatusSensor(SmartShadingEntity, SensorEntity):
    _attr_name = "House status"
    _attr_icon = "mdi:home-analytics"
    _attr_translation_key = "house_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUS_OPTIONS

    def __init__(self, engine) -> None:
        super().__init__(engine)
        self._attr_name = localized(engine, "House status", "Hausstatus")
        self._attr_unique_id = f"{self.entry.entry_id}_house_status"

    @property
    def native_value(self):
        rooms = list(self.engine.rooms.values())
        values = [room.mode for room in rooms]
        if "safety" in values:
            return "safety"
        if any(not room.enabled for room in rooms):
            return "disabled"
        if any(room.pause_mode and room.pause_mode != "auto" for room in rooms):
            return "paused"
        for priority in (
            "night",
            "heat",
            "glare",
            "solar",
            "comfort",
            "finished",
            "open",
            "idle",
        ):
            if priority in values:
                return priority
        return "idle"

    @property
    def icon(self):
        return _status_icon(self.native_value)

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        attrs.update(
            {
                "name": self.entry.title,
                "rooms": [
                    {
                        "id": runtime.room_id,
                        "name": runtime.name,
                        "mode": runtime.mode,
                        "reason": runtime.reason,
                        "enabled": runtime.enabled,
                        "pause_mode": runtime.pause_mode,
                        "pause_until": runtime.pause_until,
                        "night_active": runtime.night_active,
                    }
                    for runtime in self.engine.rooms.values()
                ],
                "cover_profiles": sorted(
                    {
                        str(layer.get("profile") or "")
                        for room in self.engine.config.get("rooms", [])
                        for sector in room.get("sectors", [])
                        for layer in sector.get("layers", [])
                        if layer.get("profile")
                    }
                ),
                "card_resource": CARD_RESOURCE,
            }
        )
        return _fit_attribute_budget(attrs)


class RoomStatusSensor(SmartShadingEntity, SensorEntity):
    _attr_name = "Status"
    _attr_translation_key = "room_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUS_OPTIONS

    def __init__(self, engine, room_id: str) -> None:
        super().__init__(engine, room_id=room_id)
        self._attr_name = localized(engine, "Room status", "Raumstatus")
        self._attr_unique_id = f"{self.entry.entry_id}_{room_id}_status"

    @property
    def runtime(self):
        return self.engine.rooms[self.room_id]

    @property
    def native_value(self):
        return self.runtime.mode

    @property
    def icon(self):
        return _status_icon(self.runtime.mode)

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        room = self.engine.room_config(self.room_id)
        compact_targets = [
            _compact_target(target) for target in self.runtime.targets
        ]
        attrs.update(
            {
                "name": self.runtime.name,
                "reason": self.runtime.reason,
                "active_sectors": self.runtime.active_sectors,
                "targets": compact_targets,
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
                    for target in compact_targets
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
                    for target in compact_targets
                    if target.get("maximum_opening", {}).get("enabled")
                ],
                "maximum_opening_monitor": {
                    "feedback_check": "immediate_on_cover_state_change",
                    "heartbeat_seconds": DEFAULT_MAX_OPEN_HEARTBEAT_SECONDS,
                    "tolerance_percent": DEFAULT_MAX_OPEN_TOLERANCE,
                },
                "last_evaluation": self.runtime.last_evaluation,
                "last_command": self.runtime.last_command,
                "sent_commands": self.runtime.sent_commands,
                "suppressed_commands": self.runtime.suppressed_commands,
                "heat_active": self.runtime.heat_active,
                "heat_phase": self.runtime.heat_phase,
                "shading_active": self.runtime.shading_active,
                # Advanced-only decision data.  Easy receives no Advanced
                # controls or settings; its compact status remains unchanged.
                "decision_trace": (
                    _compact_decision_trace(self.runtime.decision_trace)
                    if self.engine.advanced_mode
                    else {}
                ),
                "simulation_active": bool(
                    self.engine.advanced_mode
                    and self.runtime.simulation_active
                ),
                "simulation_trace": (
                    _compact_simulation_trace(self.runtime.simulation_trace)
                    if self.engine.advanced_mode
                    else {}
                ),
                "day_preview": (
                    _compact_day_preview(self.runtime.day_preview)
                    if self.engine.advanced_mode
                    else {}
                ),
                "diagnostic_level": self.engine.diagnostic_level,
                "diagnostic_events": _compact_diagnostic_events(
                    self.engine.recent_diagnostics(self.room_id, 30)
                ),
                "sector_statuses": [
                    {
                        "id": sector["id"],
                        "name": sector.get("name", ""),
                        "short": sector.get("short", ""),
                        "azimuth_start": sector.get("azimuth_start", 0),
                        "azimuth_end": sector.get("azimuth_end", 359),
                        "elevation_min": sector.get("elevation_min", 0),
                        "status": self.engine.sun_runtime[sector["id"]].status,
                        "reason": self.engine.sun_runtime[sector["id"]].status_reason,
                        "geometry_active": self.engine.sun_runtime[sector["id"]].geometry_active,
                        "sun_presence": self.engine.sun_runtime[sector["id"]].is_on,
                        "confirmation_source": self.engine.sun_runtime[sector["id"]].confirmation_source,
                        "confirmation_entity": self.engine.sun_runtime[sector["id"]].confirmation_entity,
                        "confirmation_state": self.engine.sun_runtime[sector["id"]].confirmation_state,
                        "effective_active": self.engine.sun_runtime[sector["id"]].effective_active,
                        "lux": self.engine.sun_runtime[sector["id"]].current_lux,
                        "lux_raw_state": (
                            self.engine.hass.states.get(sector.get("lux_sensor", "")).state
                            if sector.get("lux_sensor") and self.engine.hass.states.get(sector.get("lux_sensor", ""))
                            else None
                        ),
                        "lux_unit": (
                            self.engine.hass.states.get(sector.get("lux_sensor", "")).attributes.get("unit_of_measurement")
                            if sector.get("lux_sensor") and self.engine.hass.states.get(sector.get("lux_sensor", ""))
                            else None
                        ),
                        "pending_until": self.engine.sun_runtime[sector["id"]].pending_until,
                        "last_transition": self.engine.sun_runtime[sector["id"]].last_transition,
                        "mode": self.engine.sun_runtime[sector["id"]].mode,
                        "sun_presence_entity_id": er.async_get(self.engine.hass).async_get_entity_id(
                            "binary_sensor", "smart_shading", f"{self.entry.entry_id}_{sector['id']}_sun_presence"
                        ),
                    }
                    for sector in room.get("sectors", [])
                ],
                "finished_today": self.runtime.finished_today,
                "pause_mode": self.runtime.pause_mode,
                "pause_hours": self.runtime.pause_hours,
                "pause_until": self.runtime.pause_until,
                "manual_master_active": not self.runtime.enabled,
                "manual_override_entity": er.async_get(self.engine.hass).async_get_entity_id(
                    "switch", "smart_shading",
                    f"{self.entry.entry_id}_{self.room_id}_enable",
                ),
                "manual_override_groups": (
                    self.engine.manual_override_groups(self.room_id)
                    if self.engine.advanced_mode
                    else []
                ),
                "easy_confirmation_state": self.runtime.easy_confirmation_state,
                "easy_source_summary": self.runtime.easy_source_summary,
                "outdoor_temperature_condition": {
                    "enabled": self.runtime.outdoor_temperature_condition_enabled,
                    "source_entity": self.runtime.outdoor_temperature_source,
                    "value": self.runtime.outdoor_temperature_value,
                    "minimum": self.runtime.outdoor_temperature_minimum,
                    "passed": self.runtime.outdoor_temperature_passed,
                },
                "external_movement_detection_configured": bool(
                    room.get("external_movement_detection", False)
                ),
                "external_movement_detection_enabled": bool(
                    self.engine.advanced_mode
                    and room.get("external_movement_detection", False)
                ),
                "schedule_active": self.runtime.schedule_active,
                "schedule_reason": self.runtime.schedule_reason,
                "next_schedule_change": self.runtime.next_schedule_change,
                "night_enabled": bool(
                    self.engine.config.get("advanced_mode", False)
                    and room.get("night_enabled", False)
                ),
                "night_active": self.runtime.night_active,
                "night_blocked": self.runtime.night_blocked,
                "night_reason": self.runtime.night_reason,
                "night_source": room.get("night_source", "entity"),
                "night_entity": room.get("night_entity", ""),
                "night_source_state": self.runtime.night_source_state,
                "night_next_transition": self.runtime.night_next_transition,
                "night_morning_hold_until": self.runtime.night_morning_hold_until,
                "night_morning_handover_pending": (
                    self.runtime.night_morning_handover_pending
                ),
                "night_morning_transition_minutes": room.get(
                    "night_morning_transition_minutes", 0
                ),
                "night_evening_transition_minutes": room.get(
                    "night_evening_transition_minutes", 0
                ),
                "sun_entity": DEFAULT_SUN_ENTITY,
                "evaluation_interval_seconds": self.engine.config.get("evaluation_interval", 1200),
                "temperature_settings": {
                    "normal_shading_temperature": self.engine.room_value(
                        self.room_id, "normal_shading_temperature", room.get("comfort_temperature", 23.5)
                    ),
                    "comfort_temperature": self.engine.room_value(
                        self.room_id, "comfort_temperature", 23.5
                    ),
                    "solar_temperature": self.engine.room_value(
                        self.room_id, "solar_temperature", 25.5
                    ),
                    "heat_temperature": self.engine.room_value(
                        self.room_id, "heat_temperature", 27.0
                    ),
                    "reopen_temperature": self.engine.room_value(
                        self.room_id, "reopen_temperature", 22.0
                    ),
                },
                "cover_pauses": [
                    {
                        "entity_id": cover.get("entity"),
                        "name": cover.get("name", ""),
                        "short": cover.get("short", ""),
                        **self.engine.cover_pause_info(cover),
                    }
                    for sector in room.get("sectors", [])
                    for layer in sector.get("layers", [])
                    for cover in layer.get("covers", [])
                ],
                "configuration": _compact_room_configuration(room),
            }
        )
        if self.engine.advanced_mode:
            for key in (
                "easy_confirmation_state",
                "easy_source_summary",
                "outdoor_temperature_condition",
            ):
                attrs.pop(key, None)
        else:
            for key in (
                "targets",
                "protected_zone_calculations",
                "heat_active",
                "heat_phase",
                "finished_today",
                "pause_mode",
                "pause_hours",
                "pause_until",
                "manual_override_groups",
                "external_movement_detection_configured",
                "external_movement_detection_enabled",
                "schedule_active",
                "schedule_reason",
                "next_schedule_change",
                "night_enabled",
                "night_active",
                "night_blocked",
                "night_reason",
                "night_source",
                "night_entity",
                "night_source_state",
                "night_next_transition",
                "night_morning_hold_until",
                "night_morning_handover_pending",
                "night_morning_transition_minutes",
                "night_evening_transition_minutes",
                "temperature_settings",
                "maximum_opening_calculations",
                "maximum_opening_monitor",
                "cover_pauses",
                # Decision traces, simulation results, command feedback and
                # diagnostics are deliberately an Advanced Mode contract.
                # Do not merely publish empty placeholders here: an Easy
                # dashboard or template must not be able to discover the
                # Advanced-only surface by inspecting attributes.
                "decision_trace",
                "simulation_active",
                "simulation_trace",
                "day_preview",
                "diagnostic_events",
                "diagnostic_level",
            ):
                attrs.pop(key, None)
            # Easy needs a small amount of sector state to render its compact
            # sun indication.  Strip the remaining diagnostic/geometry detail
            # rather than leaking the Advanced sector runtime object wholesale.
            attrs["sector_statuses"] = [
                {
                    key: sector.get(key)
                    for key in (
                        "id",
                        "name",
                        "short",
                        "status",
                        "reason",
                        "sun_presence",
                        "confirmation_source",
                        "effective_active",
                    )
                }
                for sector in attrs.get("sector_statuses", [])
                if isinstance(sector, dict)
            ]
            attrs["configuration"] = {
                "id": room.get("id"),
                "name": room.get("name", ""),
                "sectors": [
                    {
                        key: sector.get(key)
                        for key in (
                            "id",
                            "name",
                            "short",
                            "azimuth_start",
                            "azimuth_end",
                            "elevation_min",
                            "lux_sensor",
                            "sun_presence_entity",
                        )
                    }
                    | {
                        "layers": [
                            {
                                "id": layer.get("id"),
                                "name": layer.get("name", ""),
                                "profile": layer.get("profile", ""),
                                "covers": [
                                    {
                                        key: cover.get(key)
                                        for key in (
                                            "id",
                                            "entity",
                                            "name",
                                            "short",
                                        )
                                    }
                                    for cover in layer.get("covers", [])
                                ],
                            }
                            for layer in sector.get("layers", [])
                        ]
                    }
                    for sector in room.get("sectors", [])
                ],
            }
        return _fit_attribute_budget(attrs)


class SectorStatusSensor(SmartShadingEntity, SensorEntity):
    """Effective status of one configured sun sector."""

    def __init__(self, engine, room_id: str, sector_id: str) -> None:
        super().__init__(engine, room_id=room_id, sector_id=sector_id)
        sector = engine.sector_config(sector_id)
        suffix = localized(engine, "sector status", "Sektorstatus")
        self._attr_name = f"{sector.get('name', '')} · {suffix}"
        self._attr_unique_id = f"{self.entry.entry_id}_{sector_id}_status"

    @property
    def runtime(self):
        return self.engine.sun_runtime[self.sector_id]

    @property
    def native_value(self):
        return self.runtime.status

    @property
    def icon(self):
        return {
            "shading_active": "mdi:blinds-horizontal",
            "sun_detected": "mdi:white-balance-sunny",
            "waiting_for_lux": "mdi:brightness-6",
            "waiting_conditions": "mdi:timer-sand",
            "outside_sun_sector": "mdi:sun-compass",
            "sun_below_horizon": "mdi:weather-night",
            "schedule_blocked": "mdi:calendar-remove",
            "paused": "mdi:pause-circle",
            "heat": "mdi:shield-sun",
            "night": "mdi:weather-night",
            "night_blocked": "mdi:weather-night-partly-cloudy",
            "night_transition_hold": "mdi:weather-sunset",
            "safety": "mdi:shield-alert",
            "disabled": "mdi:power",
        }.get(self.runtime.status, "mdi:sun-compass")

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        sector = self.engine.sector_config(self.sector_id)
        room = self.engine.room_config(self.room_id)
        sun_entity = DEFAULT_SUN_ENTITY
        sun = self.engine.hass.states.get(sun_entity)
        attrs.update(
            {
                "room_name": room.get("name", ""),
                "sector_name": sector.get("name", ""),
                "sector_short": sector.get("short", ""),
                "mode": self.runtime.mode,
                "reason": self.runtime.status_reason,
                "enabled": bool(self.engine.sector_value(self.sector_id, "enabled", True)),
                "geometry_active": self.runtime.geometry_active,
                "shading_active": self.runtime.shading_active,
                "sun_presence": self.runtime.is_on,
                "lux": self.runtime.current_lux,
                "azimuth_start": self.engine.sector_value(self.sector_id, "azimuth_start", sector.get("azimuth_start")),
                "azimuth_end": self.engine.sector_value(self.sector_id, "azimuth_end", sector.get("azimuth_end")),
                "elevation_min": self.engine.sector_value(self.sector_id, "elevation_min", sector.get("elevation_min")),
                "sun_azimuth": sun.attributes.get("azimuth") if sun else None,
                "sun_elevation": sun.attributes.get("elevation") if sun else None,
                "layers": [
                    {
                        "name": layer.get("name", ""),
                        "profile": layer.get("profile", ""),
                        "covers": [cover.get("name", "") for cover in layer.get("covers", [])],
                    }
                    for layer in sector.get("layers", [])
                ],
            }
        )
        return attrs
