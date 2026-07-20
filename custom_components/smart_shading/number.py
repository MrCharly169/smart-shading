from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.helpers.entity import EntityCategory

from .const import (
    DEVICE_BINARY, DEVICE_VERTICAL, DEVICE_VENETIAN, PROFILE_DEFAULTS
)
from .entity import SmartShadingEntity, localized


@dataclass(frozen=True, slots=True)
class NumberDefinition:
    key: str
    name: str
    minimum: float
    maximum: float
    step: float
    unit: str | None
    icon: str


ROOM_NUMBERS = (
    NumberDefinition("normal_shading_temperature", "Normal shading temperature", 5, 40, 0.1, "°C", "mdi:thermometer-lines"),
    NumberDefinition("comfort_temperature", "Comfort temperature", 5, 40, 0.1, "°C", "mdi:thermometer-low"),
    NumberDefinition("solar_temperature", "Solar temperature", 5, 40, 0.1, "°C", "mdi:thermometer-high"),
    NumberDefinition("heat_temperature", "Heat protection start", 5, 45, 0.1, "°C", "mdi:thermometer-alert"),
    NumberDefinition("heat_release_temperature", "Heat protection release", 5, 45, 0.1, "°C", "mdi:thermometer-chevron-down"),
    NumberDefinition("reopen_temperature", "Cool-room reopen threshold", 5, 35, 0.1, "°C", "mdi:blinds-open"),
    NumberDefinition("outdoor_minimum", "Minimum outdoor temperature", -30, 50, 0.1, "°C", "mdi:home-thermometer-outline"),
    NumberDefinition("irradiance_minimum", "Minimum irradiance", 0, 1500, 10, "W/m²", "mdi:white-balance-sunny"),
    NumberDefinition("cloud_cover_maximum", "Maximum cloud cover", 0, 100, 1, "%", "mdi:weather-cloudy"),
)

SECTOR_NUMBERS = (
    NumberDefinition("azimuth_start", "Azimuth start", 0, 359, 1, "°", "mdi:angle-acute"),
    NumberDefinition("azimuth_end", "Azimuth end", 0, 359, 1, "°", "mdi:angle-obtuse"),
    NumberDefinition("elevation_min", "Minimum sun elevation", -10, 90, 1, "°", "mdi:sun-angle-outline"),
)

SUN_NUMBERS = (
    NumberDefinition("sun_on_lux", "Sun ON lux threshold", 0, 200000, 500, "lx", "mdi:brightness-7"),
    NumberDefinition("sun_off_lux", "Sun OFF lux threshold", 0, 200000, 500, "lx", "mdi:brightness-5"),
    NumberDefinition("sun_on_delay", "Sun ON delay", 0, 60, 0.5, "min", "mdi:timer-plus-outline"),
    NumberDefinition("sun_off_delay", "Sun OFF delay", 0, 120, 0.5, "min", "mdi:timer-minus-outline"),
)

PROFILE_NUMBER_KEYS = {
    DEVICE_VENETIAN: (
        ("open_position", "Open position", "mdi:blinds-open"),
        ("night_position", "Night position", "mdi:weather-night"),
        ("night_tilt", "Night slat position", "mdi:weather-night"),
        ("safety_position", "Safety position", "mdi:shield-alert"),
    ),
    DEVICE_VERTICAL: (
        ("open_position", "Open position", "mdi:blinds-open"),
        ("comfort_tilt", "Comfort tilt", "mdi:rotate-right"),
        ("heat_tilt", "Heat tilt", "mdi:rotate-right"),
        ("night_position", "Night position", "mdi:weather-night"),
        ("night_tilt", "Night slat position", "mdi:weather-night"),
        ("safety_position", "Safety position", "mdi:shield-alert"),
    ),
}

DEFAULT_POSITION_KEYS = (
    ("open_position", "Open position", "mdi:blinds-open"),
    ("comfort_position", "Comfort position", "mdi:sun-angle"),
    ("solar_position", "Solar position", "mdi:weather-sunny-alert"),
    ("heat_position", "Heat position", "mdi:shield-sun"),
    ("night_position", "Night position", "mdi:weather-night"),
    ("safety_position", "Safety position", "mdi:shield-alert"),
)



async def async_setup_entry(hass, entry, async_add_entities) -> None:
    engine = entry.runtime_data
    if not engine.advanced_mode:
        async_add_entities([])
        return
    entities = []
    for room in engine.config.get("rooms", []):
        room_id = room["id"]
        entities.append(PauseHoursNumber(engine, room_id))
        entities.append(PauseSunOffsetNumber(engine, room_id))
        for definition in ROOM_NUMBERS:
            if _room_number_relevant(room, definition.key):
                entities.append(RoomSettingNumber(engine, room_id, definition))
        for sector in room.get("sectors", []):
            sector_id = sector["id"]
            for definition in SECTOR_NUMBERS:
                entities.append(
                    SectorSettingNumber(
                        engine, room_id, sector_id, definition
                    )
                )
            if sector.get("lux_sensor"):
                for definition in SUN_NUMBERS:
                    entities.append(
                        SectorSettingNumber(
                            engine, room_id, sector_id, definition
                        )
                    )
            for layer in sector.get("layers", []):
                profile = layer.get("profile", "venetian")
                if profile == DEVICE_BINARY:
                    continue
                keys = PROFILE_NUMBER_KEYS.get(profile, DEFAULT_POSITION_KEYS)
                for key, name, icon in keys:
                    if key.startswith("night_") and not (
                        engine.config.get("advanced_mode", False)
                        and room.get("night_enabled", False)
                    ):
                        continue
                    entities.append(
                        LayerSettingNumber(
                            engine, room_id, sector_id, layer["id"],
                            NumberDefinition(key, name, 0, 100, 1, "%", icon),
                        )
                    )
                if profile in {DEVICE_VENETIAN, DEVICE_VERTICAL} and layer.get("adaptive_tilt", False):
                    stage_names = ("Very low sun", "Low sun", "Medium sun", "High sun")
                    for index, point in enumerate(layer.get("tilt_curve", []), start=1):
                        stage = stage_names[min(index - 1, len(stage_names) - 1)]
                        entities.append(
                            LayerSettingNumber(
                                engine, room_id, sector_id, layer["id"],
                                NumberDefinition(
                                    f"tilt_elevation_{index}",
                                    f"{stage} elevation",
                                    -10, 90, 1, "°", "mdi:sun-angle-outline"
                                ),
                                default_value=float(point.get("elevation", 0)),
                            )
                        )
                        entities.append(
                            LayerSettingNumber(
                                engine, room_id, sector_id, layer["id"],
                                NumberDefinition(
                                    f"tilt_value_{index}",
                                    f"{stage} slat position",
                                    0, 100, 1, "%", "mdi:rotate-right"
                                ),
                                default_value=float(point.get("tilt", 0)),
                            )
                        )
    async_add_entities(entities)


def _room_profiles(room: dict) -> set[str]:
    return {
        str(layer.get("profile", DEVICE_VENETIAN))
        for sector in room.get("sectors", [])
        for layer in sector.get("layers", [])
    }


def _room_number_relevant(room: dict, key: str) -> bool:
    profiles = _room_profiles(room)
    venetian_only = bool(profiles) and profiles == {DEVICE_VENETIAN}
    if key == "normal_shading_temperature":
        return venetian_only
    if key in {"comfort_temperature", "solar_temperature"}:
        return not venetian_only
    if key == "outdoor_minimum":
        return bool(room.get("outdoor_temperature"))
    if key == "irradiance_minimum":
        return bool(room.get("irradiance_sensor"))
    if key == "cloud_cover_maximum":
        return bool(room.get("cloud_cover_sensor"))
    return True


class BaseSettingNumber(SmartShadingEntity, NumberEntity):
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, engine, definition: NumberDefinition, **kwargs) -> None:
        super().__init__(engine, **kwargs)
        self.definition = definition
        self._attr_name = localized(engine, definition.name, {
            "Normal shading temperature": "Normale Beschattung ab",
            "Comfort temperature": "Comfort-Temperatur",
            "Solar temperature": "Solar-Temperatur",
            "Heat protection start": "Heat-Protection-Start",
            "Heat protection release": "Heat-Protection-Freigabe",
            "Cool-room reopen threshold": "Wiederöffnungs-Temperatur",
            "Minimum outdoor temperature": "Mindestaußentemperatur",
            "Minimum irradiance": "Mindesteinstrahlung",
            "Maximum cloud cover": "Maximale Bewölkung",
            "Azimuth start": "Azimut Start",
            "Azimuth end": "Azimut Ende",
            "Minimum sun elevation": "Minimale Sonnenhöhe",
            "Sun ON lux threshold": "Sun-ON-Luxgrenze",
            "Sun OFF lux threshold": "Sun-OFF-Luxgrenze",
            "Sun ON delay": "Sun-ON-Verzögerung",
            "Sun OFF delay": "Sun-OFF-Verzögerung",
            "Open position": "Öffnungsposition",
            "Open tilt": "Öffnungs-Lamelle",
            "Comfort position": "Comfort-Position",
            "Comfort tilt": "Comfort-Lamelle",
            "Solar position": "Solar-Position",
            "Solar tilt": "Solar-Lamelle",
            "Heat position": "Heat-Position",
            "Night position": "Nachtposition",
            "Night slat position": "Nacht-Lamellenposition",
            "Heat tilt": "Heat-Lamelle",
            "Safety position": "Safety-Position",
            "Safety tilt": "Safety-Lamelle",
            "Very low sun elevation": "Tiefe Sonne – Sonnenhöhe",
            "Very low sun slat position": "Tiefe Sonne – Lamellenposition",
            "Low sun elevation": "Niedrige Sonne – Sonnenhöhe",
            "Low sun slat position": "Niedrige Sonne – Lamellenposition",
            "Medium sun elevation": "Mittlere Sonne – Sonnenhöhe",
            "Medium sun slat position": "Mittlere Sonne – Lamellenposition",
            "High sun elevation": "Hohe Sonne – Sonnenhöhe",
            "High sun slat position": "Hohe Sonne – Lamellenposition",
        }.get(definition.name, definition.name))
        self._attr_native_min_value = definition.minimum
        self._attr_native_max_value = definition.maximum
        self._attr_native_step = definition.step
        self._attr_native_unit_of_measurement = definition.unit
        self._attr_icon = definition.icon

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        attrs["smart_shading_control_key"] = self.definition.key
        return attrs


class PauseHoursNumber(SmartShadingEntity, NumberEntity):
    _attr_name = "Pause duration"
    _attr_native_min_value = 0
    _attr_native_max_value = 48
    _attr_native_step = 0.5
    _attr_native_unit_of_measurement = "h"
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:timer-outline"

    def __init__(self, engine, room_id: str) -> None:
        super().__init__(engine, room_id=room_id)
        self._attr_name = localized(engine, "Pause duration", "Pausendauer")
        self._attr_unique_id = f"{self.entry.entry_id}_{room_id}_pause_hours"

    @property
    def native_value(self):
        return self.engine.rooms[self.room_id].pause_hours

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        attrs["smart_shading_control_key"] = "pause_hours"
        return attrs

    async def async_set_native_value(self, value: float) -> None:
        await self.engine.async_set_pause_hours(self.room_id, value)


class PauseSunOffsetNumber(SmartShadingEntity, NumberEntity):
    _attr_name = "Pause sun offset"
    _attr_native_min_value = -120
    _attr_native_max_value = 240
    _attr_native_step = 5
    _attr_native_unit_of_measurement = "min"
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:weather-sunset-up"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, engine, room_id: str) -> None:
        super().__init__(engine, room_id=room_id)
        self._attr_name = localized(engine, "Pause sun offset", "Pausen-Offset zur Sonne")
        self._attr_unique_id = f"{self.entry.entry_id}_{room_id}_pause_sun_offset"

    @property
    def native_value(self):
        return float(self.engine.room_value(self.room_id, "pause_sun_offset_minutes", 0))

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        attrs["smart_shading_control_key"] = "pause_sun_offset_minutes"
        return attrs

    async def async_set_native_value(self, value: float) -> None:
        await self.engine.async_set_room_value(self.room_id, "pause_sun_offset_minutes", value)


class RoomSettingNumber(BaseSettingNumber):
    def __init__(self, engine, room_id: str, definition: NumberDefinition) -> None:
        super().__init__(engine, definition, room_id=room_id)
        self._attr_unique_id = (
            f"{self.entry.entry_id}_{room_id}_{definition.key}"
        )

    @property
    def native_value(self):
        return float(
            self.engine.room_value(
                self.room_id, self.definition.key, self.definition.minimum
            )
        )

    async def async_set_native_value(self, value: float) -> None:
        await self.engine.async_set_room_value(
            self.room_id, self.definition.key, value
        )


class SectorSettingNumber(BaseSettingNumber):
    def __init__(
        self,
        engine,
        room_id: str,
        sector_id: str,
        definition: NumberDefinition,
    ) -> None:
        sector = engine.sector_config(sector_id)
        named = NumberDefinition(
            definition.key,
            f"{sector['name']} · {localized(engine, definition.name, {'Azimuth start': 'Azimut Start', 'Azimuth end': 'Azimut Ende', 'Minimum sun elevation': 'Minimale Sonnenhöhe', 'Sun ON lux threshold': 'Sun-ON-Luxgrenze', 'Sun OFF lux threshold': 'Sun-OFF-Luxgrenze', 'Sun ON delay': 'Sun-ON-Verzögerung', 'Sun OFF delay': 'Sun-OFF-Verzögerung'}.get(definition.name, definition.name))}",
            definition.minimum,
            definition.maximum,
            definition.step,
            definition.unit,
            definition.icon,
        )
        super().__init__(
            engine, named, room_id=room_id, sector_id=sector_id
        )
        self._attr_unique_id = (
            f"{self.entry.entry_id}_{sector_id}_{definition.key}"
        )

    @property
    def native_value(self):
        return float(
            self.engine.sector_value(
                self.sector_id,
                self.definition.key,
                self.definition.minimum,
            )
        )

    async def async_set_native_value(self, value: float) -> None:
        await self.engine.async_set_sector_value(
            self.sector_id, self.definition.key, value
        )


class LayerSettingNumber(BaseSettingNumber):
    def __init__(
        self,
        engine,
        room_id: str,
        sector_id: str,
        layer_id: str,
        definition: NumberDefinition,
        default_value: float | None = None,
    ) -> None:
        layer = engine.layer_config(layer_id)
        named = NumberDefinition(
            definition.key,
            f"{layer['name']} · {localized(engine, definition.name, {'Open position': 'Öffnungsposition', 'Open tilt': 'Öffnungs-Lamelle', 'Comfort position': 'Comfort-Position', 'Comfort tilt': 'Comfort-Lamelle', 'Solar position': 'Solar-Position', 'Solar tilt': 'Solar-Lamelle', 'Heat position': 'Heat-Position', 'Heat tilt': 'Heat-Lamelle', 'Night position': 'Nachtposition', 'Night slat position': 'Nacht-Lamellenposition', 'Safety position': 'Safety-Position', 'Safety tilt': 'Safety-Lamelle'}.get(definition.name, definition.name))}",
            definition.minimum,
            definition.maximum,
            definition.step,
            definition.unit,
            definition.icon,
        )
        super().__init__(
            engine,
            named,
            room_id=room_id,
            sector_id=sector_id,
            layer_id=layer_id,
        )
        self._attr_unique_id = (
            f"{self.entry.entry_id}_{layer_id}_{definition.key}"
        )
        self._default_value = (
            definition.minimum if default_value is None else default_value
        )

    @property
    def native_value(self):
        return float(
            self.engine.layer_value(
                self.layer_id,
                self.definition.key,
                self._default_value,
            )
        )

    async def async_set_native_value(self, value: float) -> None:
        await self.engine.async_set_layer_value(
            self.layer_id, self.definition.key, value
        )
