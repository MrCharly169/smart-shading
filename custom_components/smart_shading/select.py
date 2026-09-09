from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import EntityCategory

from .const import (
    DIAGNOSTIC_EVENTS,
    DIAGNOSTIC_FULL,
    DIAGNOSTIC_OFF,
    DIAGNOSTIC_OPTIONS,
    OPERATING_PROFILE_AUTOMATIC,
    OPERATING_PROFILE_INHERIT,
    OPERATING_PROFILE_OPTIONS,
    OPERATING_PROFILE_PROTECTION_ONLY,
    OPERATING_PROFILE_YEAR_ROUND,
    PAUSE_AUTO,
    PAUSE_MANUAL,
    PAUSE_NEXT_NIGHT_END,
    PAUSE_NEXT_SUNRISE,
    PAUSE_NEXT_SUNSET,
    PAUSE_TIMED,
    SUN_PRESET_OPTIONS,
)
from .entity import SmartShadingEntity, localized
from .options_navigation import pause_modes_for_room


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    engine = entry.runtime_data
    if not engine.advanced_mode:
        async_add_entities([])
        return
    entities = [DiagnosticLoggingSelect(engine), HouseOperatingProfileSelect(engine)]
    for room_id in engine.rooms:
        entities.append(RoomOperatingProfileSelect(engine, room_id))
        entities.append(RoomPauseSelect(engine, room_id))
    for room in engine.config.get("rooms", []):
        for sector in room.get("sectors", []):
            if sector.get("lux_sensor"):
                entities.append(SunSensitivitySelect(engine, room["id"], sector["id"]))
    async_add_entities(entities)


class DiagnosticLoggingSelect(SmartShadingEntity, SelectEntity):
    _attr_icon = "mdi:text-box-search-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, engine) -> None:
        super().__init__(engine)
        self._attr_translation_key = 'diagnostic_logging'
        self._attr_unique_id = f"{self.entry.entry_id}_diagnostic_level"
        self._labels = {
            DIAGNOSTIC_OFF: localized(engine, "Off", "Aus"),
            DIAGNOSTIC_EVENTS: localized(engine, "Events", "Ereignisse"),
            DIAGNOSTIC_FULL: localized(engine, "Full", "Vollständig"),
        }
        self._reverse = {label: key for key, label in self._labels.items()}
        self._attr_options = [self._labels[key] for key in DIAGNOSTIC_OPTIONS]

    @property
    def current_option(self):
        return self._labels.get(self.engine.diagnostic_level, self._labels[DIAGNOSTIC_OFF])

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        attrs["smart_shading_control_key"] = "diagnostic_level"
        attrs["diagnostic_level_key"] = self.engine.diagnostic_level
        return attrs

    async def async_select_option(self, option: str) -> None:
        await self.engine.async_set_diagnostic_level(self._reverse.get(option, option))


class RoomPauseSelect(SmartShadingEntity, SelectEntity):
    _attr_icon = "mdi:pause-circle-outline"

    def __init__(self, engine, room_id: str) -> None:
        super().__init__(engine, room_id=room_id)
        self._attr_translation_key = 'pause_mode'
        self._attr_unique_id = f"{self.entry.entry_id}_{room_id}_pause"
        self._labels = {
            PAUSE_AUTO: localized(engine, "Not paused", "Nicht pausiert"),
            PAUSE_NEXT_SUNRISE: localized(engine, "Until next morning", "Bis zum nächsten Morgen"),
            PAUSE_NEXT_SUNSET: localized(engine, "Until next sunset", "Bis zum nächsten Sonnenuntergang"),
            PAUSE_NEXT_NIGHT_END: localized(engine, "Until the end of the next Night", "Bis zum Ende der nächsten Nacht"),
            PAUSE_TIMED: localized(engine, "For a fixed duration", "Für eine feste Dauer"),
            PAUSE_MANUAL: localized(engine, "Until manually resumed", "Bis manuell fortgesetzt"),
        }
        self._reverse = {label: key for key, label in self._labels.items()}
        room = engine.room_config(room_id)
        pause_options = [PAUSE_AUTO, *pause_modes_for_room(room)]
        self._attr_options = [self._labels[key] for key in pause_options]

    @property
    def current_option(self):
        key = self.engine.rooms[self.room_id].pause_mode
        return self._labels.get(key, self._labels[PAUSE_AUTO])

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        attrs["smart_shading_control_key"] = "pause_mode"
        attrs["pause_mode_key"] = self.engine.rooms[self.room_id].pause_mode
        return attrs

    async def async_select_option(self, option: str) -> None:
        await self.engine.async_set_pause_mode(self.room_id, self._reverse.get(option, option))


class RoomOperatingProfileSelect(SmartShadingEntity, SelectEntity):
    """Expose the bundled seasonal policy as one native HA/voice control."""

    _attr_icon = "mdi:home-switch"

    def __init__(self, engine, room_id: str) -> None:
        super().__init__(engine, room_id=room_id)
        self._attr_translation_key = 'operating_profile'
        self._attr_unique_id = f"{self.entry.entry_id}_{room_id}_operating_profile"
        self._labels = {
            OPERATING_PROFILE_INHERIT: localized(
                engine, "Global setting", "Globale Einstellung"
            ),
            OPERATING_PROFILE_AUTOMATIC: localized(
                engine,
                "By season and schedule",
                "Nach Saison und Zeitplan",
            ),
            OPERATING_PROFILE_PROTECTION_ONLY: localized(
                engine, "Protection only", "Nur Schutz"
            ),
            OPERATING_PROFILE_YEAR_ROUND: localized(
                engine, "Year-round", "Ganzjährig"
            ),
        }
        self._reverse = {label: key for key, label in self._labels.items()}
        self._attr_options = [
            self._labels[key]
            for key in [OPERATING_PROFILE_INHERIT, *OPERATING_PROFILE_OPTIONS]
        ]

    @property
    def current_option(self):
        key = str(
            self.engine.room_value(
                self.room_id,
                "operating_profile",
                OPERATING_PROFILE_INHERIT,
            )
        )
        return self._labels.get(key, self._labels[OPERATING_PROFILE_INHERIT])

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        attrs["smart_shading_control_key"] = "operating_profile"
        attrs["operating_profile_key"] = str(
            self.engine.room_value(
                self.room_id,
                "operating_profile",
                OPERATING_PROFILE_INHERIT,
            )
        )
        return attrs

    async def async_select_option(self, option: str) -> None:
        await self.engine.async_set_operating_profile(
            self.room_id, self._reverse.get(option, option)
        )


class HouseOperatingProfileSelect(SmartShadingEntity, SelectEntity):
    """Expose the global thermal policy as one HA and voice control."""

    _attr_icon = "mdi:home-shield"

    def __init__(self, engine) -> None:
        super().__init__(engine)
        self._attr_translation_key = 'operation_and_protection'
        self._attr_unique_id = f"{self.entry.entry_id}_operating_profile"
        self._labels = {
            OPERATING_PROFILE_AUTOMATIC: localized(
                engine,
                "By season and schedule",
                "Nach Saison und Zeitplan",
            ),
            OPERATING_PROFILE_PROTECTION_ONLY: localized(
                engine, "Protection only", "Nur Schutz"
            ),
            OPERATING_PROFILE_YEAR_ROUND: localized(
                engine, "Year-round", "Ganzjährig"
            ),
        }
        self._reverse = {label: key for key, label in self._labels.items()}
        self._attr_options = [
            self._labels[key] for key in OPERATING_PROFILE_OPTIONS
        ]

    @property
    def current_option(self):
        key = str(
            self.engine.house_value(
                "operating_profile", OPERATING_PROFILE_AUTOMATIC
            )
        )
        return self._labels.get(key, self._labels[OPERATING_PROFILE_AUTOMATIC])

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        attrs["smart_shading_control_key"] = "house_operating_profile"
        attrs["operating_profile_key"] = str(
            self.engine.house_value(
                "operating_profile", OPERATING_PROFILE_AUTOMATIC
            )
        )
        return attrs

    async def async_select_option(self, option: str) -> None:
        await self.engine.async_set_operating_profile(
            None, self._reverse.get(option, option)
        )


class SunSensitivitySelect(SmartShadingEntity, SelectEntity):
    _attr_icon = "mdi:weather-sunny-alert"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, engine, room_id: str, sector_id: str) -> None:
        super().__init__(engine, room_id=room_id, sector_id=sector_id)
        sector = engine.sector_config(sector_id)
        self._attr_translation_key = 'sun_sensitivity'
        self._attr_translation_placeholders = {"scope": str(sector.get("name", ""))}
        self._attr_unique_id = f"{self.entry.entry_id}_{sector_id}_sun_preset"
        self._labels = {
            "low": localized(engine, "Less sensitive", "Weniger empfindlich"),
            "medium": localized(engine, "Balanced", "Ausgewogen"),
            "high": localized(engine, "Sensitive", "Empfindlich"),
            "custom": localized(engine, "Custom", "Benutzerdefiniert"),
        }
        self._reverse = {label: key for key, label in self._labels.items()}
        self._attr_options = [self._labels[key] for key in SUN_PRESET_OPTIONS]

    @property
    def current_option(self):
        key = str(self.engine.sector_value(self.sector_id, "sun_preset", "medium"))
        return self._labels.get(key, self._labels["medium"])

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        attrs["smart_shading_control_key"] = "sun_preset"
        attrs["sun_preset_key"] = str(self.engine.sector_value(self.sector_id, "sun_preset", "medium"))
        return attrs

    async def async_select_option(self, option: str) -> None:
        await self.engine.async_set_sun_preset(self.sector_id, self._reverse.get(option, option))
