from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers import entity_registry as er

from .const import CARD_RESOURCE
from .entity import SmartShadingEntity, localized


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

    def __init__(self, engine) -> None:
        super().__init__(engine)
        self._attr_name = localized(engine, "House status", "Hausstatus")
        self._attr_unique_id = f"{self.entry.entry_id}_house_status"

    @property
    def native_value(self):
        values = [room.mode for room in self.engine.rooms.values()]
        for priority in (
            "safety",
            "night",
            "heat",
            "solar",
            "comfort",
            "paused",
            "finished",
            "open",
            "idle",
        ):
            if priority in values:
                return priority
        return "idle"

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
                    }
                    for runtime in self.engine.rooms.values()
                ],
                "card_yaml": (
                    "type: custom:smart-shading-card\n"
                    f"entity: {self.entity_id}\n"
                ),
                "card_resource": CARD_RESOURCE,
            }
        )
        return attrs


class RoomStatusSensor(SmartShadingEntity, SensorEntity):
    _attr_name = "Status"

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
        return {
            "heat": "mdi:shield-sun",
            "night": "mdi:weather-night",
            "solar": "mdi:weather-sunny-alert",
            "comfort": "mdi:sun-angle",
            "safety": "mdi:shield-alert",
            "paused": "mdi:pause-circle",
            "open": "mdi:blinds-open",
            "finished": "mdi:calendar-check",
        }.get(self.runtime.mode, "mdi:blinds-horizontal")

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        room = self.engine.room_config(self.room_id)
        attrs.update(
            {
                "name": self.runtime.name,
                "reason": self.runtime.reason,
                "active_sectors": self.runtime.active_sectors,
                "targets": self.runtime.targets,
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
                    self.runtime.decision_trace
                    if self.engine.advanced_mode
                    else {}
                ),
                "simulation_active": bool(
                    self.engine.advanced_mode
                    and self.runtime.simulation_active
                ),
                "simulation_trace": (
                    self.runtime.simulation_trace
                    if self.engine.advanced_mode
                    else {}
                ),
                "day_preview": (
                    self.runtime.day_preview
                    if self.engine.advanced_mode
                    else {}
                ),
                "diagnostic_level": self.engine.diagnostic_level,
                "diagnostic_events": self.engine.recent_diagnostics(self.room_id, 30),
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
                        "sun_settings": self.engine._sun_settings(sector["id"]),
                        "pending_target": self.engine.sun_runtime[sector["id"]].pending_target,
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
                "sun_entity": self.engine.config.get("sun_entity", "sun.sun"),
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
                "configuration": room,
                "card_yaml": (
                    "type: custom:smart-shading-card\n"
                    f"entity: {self.entity_id}\n"
                ),
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
        return attrs


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
        sun_entity = self.engine.config.get("sun_entity", "sun.sun")
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
