from __future__ import annotations

from copy import deepcopy
import re
import uuid
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult, OptionsFlowWithReload
from homeassistant.core import callback
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from .const import (
    CARD_RESOURCE,
    CONF_ADVANCED_MODE,
    CONF_DIAGNOSTIC_LEVEL,
    CONF_EASY_TEMPERATURE_GATE,
    CONF_EVALUATION_INTERVAL,
    CONF_EXTERNAL_MOVEMENT_DETECTION,
    CONF_HOUSE_NAME,
    CONF_ROOMS,
    CONF_SUN_PRESENCE_ENTITY,
    CONF_SUN_ENTITY,
    CONF_TEST_MODE,
    CONF_WEATHER_ENTITY,
    CONF_WINDOW_RETURNS_TO_AUTOMATION,
    DAY_WINDOW_ALL_DAY,
    DAY_WINDOW_FIXED,
    DAY_WINDOW_OPTIONS,
    DEFAULT_COMMAND_COOLDOWN,
    DEFAULT_EVALUATION_INTERVAL,
    DEFAULT_EXTERNAL_MOVEMENT_DETECTION,
    DEFAULT_EVENING_RELEASE_TIME,
    DEFAULT_POSITION_TOLERANCE,
    DEFAULT_SUNSET_OFFSET_MINUTES,
    DEFAULT_TILT_TOLERANCE,
    DEFAULT_WINDOW_RETURNS_TO_AUTOMATION,
    DIAGNOSTIC_EVENTS,
    DIAGNOSTIC_OPTIONS,
    DEVICE_TYPES,
    DEVICE_VERTICAL,
    DEVICE_VENETIAN,
    DIRECTION_CUSTOM,
    DIRECTION_OPTIONS,
    DIRECTION_PRESETS,
    DOMAIN,
    OUTSIDE_OPEN,
    OUTSIDE_OPTIONS,
    PAUSE_MANUAL,
    PAUSE_NEXT_NIGHT_END,
    PAUSE_NEXT_SUNRISE,
    PAUSE_NEXT_SUNSET,
    PAUSE_TIMED,
    PRESET_CUSTOM,
    PRESET_MEDIUM,
    PROFILE_DEFAULTS,
    ROOM_DEFAULTS,
    SCHEDULE_CUSTOM,
    SCHEDULE_OPTIONS,
    SCHEDULE_SUMMER,
    SCHEDULE_YEAR_ROUND,
    SUN_PRESETS,
    SUN_PRESET_OPTIONS,
    TILT_CURVE_PRESETS,
    TILT_PRESET_BALANCED,
    TILT_PRESET_CUSTOM,
    TILT_PRESET_OPTIONS,
    WINDOW_POLICIES,
)


from .logic import finalize_sector_identity, needs_custom_sun_settings
from .options_navigation import build_main_room_routes, build_room_routes


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return value or uuid.uuid4().hex[:8]


def _new_id(name: str) -> str:
    return f"{_slug(name)}_{uuid.uuid4().hex[:6]}"


def _entity(domain: str | list[str], *, multiple: bool = False):
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=domain, multiple=multiple)
    )


def _number(
    minimum: float,
    maximum: float,
    step: float,
    unit: str,
    *,
    mode: str = "slider",
):
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            unit_of_measurement=unit,
            mode=mode,
        )
    )


def _select(
    options: list[str],
    translation_key: str,
    *,
    multiple: bool = False,
):
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[str(option) for option in options],
            mode="dropdown",
            multiple=multiple,
            translation_key=translation_key,
        )
    )


def _optional_marker(key: str, value: Any = None) -> vol.Optional:
    """Return a clearable optional marker with a frontend suggestion."""
    if value in (None, "", []):
        return vol.Optional(key)
    return vol.Optional(key, description={"suggested_value": value})


def _flatten_sections(user_input: dict[str, Any]) -> dict[str, Any]:
    """Flatten the one supported Home Assistant form-section level."""
    flattened: dict[str, Any] = {}
    for key, value in user_input.items():
        if isinstance(value, dict):
            flattened.update(value)
        else:
            flattened[key] = value
    return flattened


def _nonempty_suggestions(values: dict[str, Any]) -> dict[str, Any]:
    """Remove empty entity suggestions that the frontend cannot resolve."""
    return {
        key: value
        for key, value in values.items()
        if value not in (None, "", [])
    }


def _temperature_entity():
    return selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="sensor",
            device_class="temperature",
        )
    )


def _direction_name(direction: str, language: str) -> tuple[str, str]:
    de = language.lower().startswith("de")
    labels = {
        "north": (("Nord", "N"), ("North", "N")),
        "northeast": (("Nordost", "NO"), ("Northeast", "NE")),
        "east": (("Ost", "O"), ("East", "E")),
        "southeast": (("Südost", "SO"), ("Southeast", "SE")),
        "south": (("Süd", "S"), ("South", "S")),
        "southwest": (("Südwest", "SW"), ("Southwest", "SW")),
        "west": (("West", "W"), ("West", "W")),
        "northwest": (("Nordwest", "NW"), ("Northwest", "NW")),
        "custom": (("Sonnensektor", "X"), ("Sun sector", "X")),
    }
    german, english = labels.get(direction, labels["custom"])
    return german if de else english


def _default_cover(entity_id: str, display_name: str, short_name: str = "") -> dict[str, Any]:
    return {
        "entity": entity_id,
        "name": display_name,
        "short": short_name,
        "lock": "",
        "window": "",
        "window_safe_state": "on",
        "window_policy": "block_closing",
        CONF_WINDOW_RETURNS_TO_AUTOMATION: DEFAULT_WINDOW_RETURNS_TO_AUTOMATION,
        "invert_position": False,
        "invert_tilt": False,
        "max_open_position": 100.0,
        "safety_position_override": None,
    }


SELECT_LABELS_DE: dict[str, dict[str, str]] = {
    "direction_preset": {
        "north": "Nord (N)", "northeast": "Nordost (NO)", "east": "Ost (O)",
        "southeast": "Südost (SO)", "south": "Süd (S)", "southwest": "Südwest (SW)",
        "west": "West (W)", "northwest": "Nordwest (NW)", "custom": "Benutzerdefiniert",
    },
    "sun_preset": {"low": "Weniger empfindlich", "medium": "Ausgewogen", "high": "Empfindlich", "custom": "Benutzerdefiniert"},
    "tilt_preset": {"glare": "Mehr Blendschutz", "balanced": "Ausgewogen", "daylight": "Mehr Tageslicht", "custom": "Benutzerdefiniert"},
    "device_type": {
        "venetian": "Außenjalousie mit Lamellen", "roller_shutter": "Rollladen",
        "exterior_screen": "Außenscreen / Zip-Screen", "curtain": "Innenvorhang",
        "vertical_blind": "Vertikale Innenjalousie", "awning": "Markise",
        "binary_cover": "Einfacher Auf/Zu-Behang",
    },
    "schedule_profile": {"year_round": "Ganzjährig automatisch", "summer": "Sommersaison (Mai–September)", "custom": "Benutzerdefinierter Zeitplan"},
    "day_window": {"sector_sun": "Nur bei Sonne im Sektor", "fixed_time": "Feste Uhrzeit", "all_day": "Ganztägig"},
    "outside_schedule_behavior": {"open": "In Ruheposition fahren", "hold": "Position unverändert lassen"},
    "feedback_policy": {"send": "Befehl senden", "skip": "Ohne Rückmeldung nicht senden"},
    "weather_logic": {"all": "Alle Bedingungen müssen passen", "any": "Eine Bedingung genügt"},
    "safety_behavior": {"move_safe": "In sichere Position fahren", "block": "Normale Automatik nur blockieren"},
    "safe_state": {"on": "Ein / ON ist sicher", "off": "Aus / OFF ist sicher"},
    "window_policy": {"block_all": "Alle Automatikfahrten blockieren", "block_closing": "Nur Schließen blockieren", "ignore": "Fensterkontakt ignorieren"},
    "diagnostic_level": {"off": "Aus", "events": "Ereignisse", "full": "Vollständig"},
    "pause_mode": {"next_sunrise": "Bis zum nächsten Morgen", "next_sunset": "Bis zum nächsten Sonnenuntergang", "next_night_end": "Bis zum Ende der nächsten Nacht", "timed": "Für eine feste Dauer", "manual": "Bis manuell fortgesetzt", "auto": "Nicht pausiert"},
    "night_source": {"entity": "Entität / Zeitplan", "sun": "Sonnenuntergang und Sonnenaufgang"},
    "months": {str(i): name for i, name in enumerate(("", "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember")) if i},
    "weekdays": {str(i): name for i, name in enumerate(("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"))},
}
SELECT_LABELS_EN: dict[str, dict[str, str]] = {
    "direction_preset": {"north": "North (N)", "northeast": "Northeast (NE)", "east": "East (E)", "southeast": "Southeast (SE)", "south": "South (S)", "southwest": "Southwest (SW)", "west": "West (W)", "northwest": "Northwest (NW)", "custom": "Custom"},
    "sun_preset": {"low": "Less sensitive", "medium": "Balanced", "high": "Sensitive", "custom": "Custom"},
    "tilt_preset": {"glare": "More glare protection", "balanced": "Balanced", "daylight": "More daylight", "custom": "Custom"},
    "device_type": {"venetian": "Exterior venetian blind", "roller_shutter": "Roller shutter", "exterior_screen": "Exterior / zip screen", "curtain": "Interior curtain", "vertical_blind": "Vertical blind", "awning": "Awning", "binary_cover": "Simple open/close cover"},
    "schedule_profile": {"year_round": "Automatic all year", "summer": "Summer season (May–September)", "custom": "Custom schedule"},
    "day_window": {"sector_sun": "Only while the sun is in the sector", "fixed_time": "Fixed time", "all_day": "All day"},
    "outside_schedule_behavior": {"open": "Move to neutral/open position", "hold": "Keep current position"},
    "feedback_policy": {"send": "Send command", "skip": "Do not send without feedback"},
    "weather_logic": {"all": "All conditions must pass", "any": "Any condition may pass"},
    "safety_behavior": {"move_safe": "Move to the safe position", "block": "Only block normal automation"},
    "safe_state": {"on": "On is safe", "off": "Off is safe"},
    "window_policy": {"block_all": "Block every automatic move", "block_closing": "Only block closing", "ignore": "Ignore window contact"},
    "diagnostic_level": {"off": "Off", "events": "Events", "full": "Full"},
    "pause_mode": {"next_sunrise": "Until next morning", "next_sunset": "Until next sunset", "next_night_end": "Until the end of the next Night", "timed": "For a fixed duration", "manual": "Until manually resumed", "auto": "Not paused"},
    "night_source": {"entity": "Entity / schedule", "sun": "Sunset and sunrise"},
    "months": {str(i): name for i, name in enumerate(("", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")) if i},
    "weekdays": {str(i): name for i, name in enumerate(("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"))},
}


MENU_LABELS_DE: dict[str, str] = {
    "configure_current_room": "Aktuellen Raum verwalten",
    "add_more_covers": "Weitere Behänge zuordnen",
    "add_another_layer": "Weitere Behanggruppe anlegen",
    "add_another_sector": "Weiteren Sonnensektor anlegen",
    "add_another_room": "Weiteren Raum anlegen",
    "finish": "Speichern und Smart Shading starten",
    "add_room": "Raum hinzufügen",
    "select_room": "Raum verwalten",
    "global_settings": "Allgemeine und erweiterte Einstellungen",
    "edit_room_basic": "Raumname und Sensoren",
    "edit_room_schedule": "Aktivitätszeitplan",
    "edit_room_pause": "Pause und manueller Override",
    "edit_room_night": "Nachtfunktion",
    "room_advanced": "Erweiterte Raumeinstellungen",
    "add_sector": "Sonnensektor hinzufügen",
    "select_sector": "Sonnensektor verwalten",
    "delete_room": "Raum löschen",
    "back_to_overview": "Zur Übersicht",
    "edit_sector_customer": "Richtung und Sun Presence",
    "edit_sector_advanced": "Erweiterte Sektorgeometrie",
    "add_layer": "Behanggruppe hinzufügen",
    "select_layer": "Behanggruppe verwalten",
    "delete_sector": "Sonnensektor löschen",
    "room_actions": "Zurück zum Raum",
    "edit_layer_customer": "Behangtyp und Profil",
    "edit_layer_advanced": "Erweiterte Zielwerte",
    "add_covers": "Mehrere Behänge hinzufügen",
    "select_cover": "Einzelnen Behang bearbeiten",
    "remove_covers": "Behänge entfernen",
    "delete_layer": "Behanggruppe löschen",
    "sector_actions": "Zurück zum Sonnensektor",
}
MENU_LABELS_EN: dict[str, str] = {
    "configure_current_room": "Manage current room",
    "add_more_covers": "Assign more covers",
    "add_another_layer": "Create another cover group",
    "add_another_sector": "Create another sun sector",
    "add_another_room": "Create another room",
    "finish": "Save and start Smart Shading",
    "add_room": "Add room",
    "select_room": "Manage room",
    "global_settings": "General and advanced settings",
    "edit_room_basic": "Room name and sensors",
    "edit_room_schedule": "Activity schedule",
    "edit_room_pause": "Pause and manual override",
    "edit_room_night": "Night Mode",
    "room_advanced": "Advanced room settings",
    "add_sector": "Add sun sector",
    "select_sector": "Manage sun sector",
    "delete_room": "Delete room",
    "back_to_overview": "Back to overview",
    "edit_sector_customer": "Direction and Sun Presence",
    "edit_sector_advanced": "Advanced sector geometry",
    "add_layer": "Add cover group",
    "select_layer": "Manage cover group",
    "delete_sector": "Delete sun sector",
    "room_actions": "Back to room",
    "edit_layer_customer": "Cover type and profile",
    "edit_layer_advanced": "Advanced targets",
    "add_covers": "Add multiple covers",
    "select_cover": "Edit individual cover",
    "remove_covers": "Remove covers",
    "delete_layer": "Delete cover group",
    "sector_actions": "Back to sun sector",
}


class _SmartShadingWizardMixin:
    """Customer-first wizard and explicit advanced editing."""


    def _is_german(self) -> bool:
        return (getattr(self.hass.config, "language", "en") or "en").lower().startswith("de")

    def _menu(self, options: list[str]) -> dict[str, str]:
        labels = MENU_LABELS_DE if self._is_german() else MENU_LABELS_EN
        return {option: labels.get(option, option.replace("_", " ").title()) for option in options}

    def _choice(self, options: list[str], key: str, *, multiple: bool = False):
        return _select(options, key, multiple=multiple)

    def _friendly_name(self, entity_id: str, fallback: str) -> str:
        state = self.hass.states.get(entity_id)
        friendly = state.attributes.get("friendly_name") if state else None
        return str(friendly or fallback)

    @property
    def advanced_mode(self) -> bool:
        return bool(self._working.get(CONF_ADVANCED_MODE, False))

    _STEP_PROGRESS = {
        "user": 1,
        "add_room": 2,
        "room_schedule": 3,
        "room_schedule_custom": 4,
        "room_schedule_time": 4,
        "sector_direction": 5,
        "sector_identity": 6,
        "sector_geometry": 6,
        "sector_lux": 6,
        "sector_lux_custom": 7,
        "add_layer": 8,
        "layer_tilt_profile": 8,
        "layer_tilt_custom": 8,
        "add_covers": 9,
        "name_selected_cover": 9,
    }

    def async_show_form(self, *args: Any, **kwargs: Any) -> ConfigFlowResult:
        """Show a form with compatibility placeholders for older cached translations.

        Earlier beta translations used ``{step}``, ``{total}`` and ``{preset}``
        in step titles. Home Assistant browsers can retain those translations
        briefly after an integration update. Supplying the placeholders on every
        form prevents a Translation format Error during that transition.
        """
        step_id = kwargs.get("step_id")
        if step_id is None and args:
            step_id = args[0]
        preset = ""
        pending = getattr(self, "_pending_sector", None)
        if isinstance(pending, dict):
            preset = str(pending.get("name", ""))
        elif getattr(self, "_sector_id", None):
            try:
                preset = str(self.sector().get("name", ""))
            except (KeyError, StopIteration, AttributeError):
                preset = ""
        placeholders = {
            "step": str(self._STEP_PROGRESS.get(str(step_id), 1)),
            "total": "9",
            "preset": preset,
            "card_resource": CARD_RESOURCE,
        }
        placeholders.update(kwargs.get("description_placeholders") or {})
        kwargs["description_placeholders"] = placeholders
        return super().async_show_form(*args, **kwargs)

    @property
    def rooms(self) -> list[dict[str, Any]]:
        return self._working.setdefault(CONF_ROOMS, [])

    def room(self) -> dict[str, Any]:
        return next(room for room in self.rooms if room["id"] == self._room_id)

    def sector(self) -> dict[str, Any]:
        return next(
            item
            for item in self.room().get("sectors", [])
            if item["id"] == self._sector_id
        )

    def layer(self) -> dict[str, Any]:
        return next(
            item
            for item in self.sector().get("layers", [])
            if item["id"] == self._layer_id
        )

    def all_cover_entities(self) -> set[str]:
        return {
            cover["entity"]
            for room in self.rooms
            for sector in room.get("sectors", [])
            for layer in sector.get("layers", [])
            for cover in layer.get("covers", [])
        }

    def _room_profiles(self, room: dict[str, Any] | None = None) -> set[str]:
        room = room or self.room()
        return {
            str(layer.get("profile", DEVICE_VENETIAN))
            for sector in room.get("sectors", [])
            for layer in sector.get("layers", [])
        }

    def _venetian_only(self, room: dict[str, Any] | None = None) -> bool:
        profiles = self._room_profiles(room)
        return not profiles or profiles == {DEVICE_VENETIAN}

    def _cover_short(self, index: int) -> str:
        return f"B{index + 1}" if self._is_german() else f"C{index + 1}"

    def _direction_defaults(self, direction: str) -> dict[str, Any]:
        name, short = _direction_name(
            direction, getattr(self.hass.config, "language", "en") or "en"
        )
        return {
            "direction": direction,
            "name": name,
            "short": short,
            "enabled": True,
            "layers": [],
            **DIRECTION_PRESETS[direction],
        }

    def _new_layer(self, name: str, profile: str) -> dict[str, Any]:
        layer = deepcopy(PROFILE_DEFAULTS[profile])
        layer.update(
            {
                "id": _new_id(name),
                "name": name,
                "profile": profile,
                "covers": [],
            }
        )
        return layer

    def _append_pending_sector(self) -> None:
        """Append a pending sector and always ensure a stable internal ID."""
        assert self._pending_sector is not None
        self._pending_sector = finalize_sector_identity(
            self._pending_sector,
            name=str(self._pending_sector.get("name") or "Sun sector"),
            short=str(self._pending_sector.get("short") or "S"),
            id_factory=_new_id,
        )
        self.room().setdefault("sectors", []).append(self._pending_sector)
        self._sector_id = str(self._pending_sector["id"])
        self._pending_sector = None

    def _append_pending_layer(self) -> None:
        assert self._pending_layer is not None
        self.sector().setdefault("layers", []).append(self._pending_layer)
        self._layer_id = self._pending_layer["id"]
        self._pending_layer = None

    async def async_step_global_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            values = dict(user_input)
            # Weather is an Easy Mode refinement.  It remains stored while
            # Advanced Mode is selected, but only an Easy form may change or
            # clear it.
            if not self.advanced_mode:
                self._working[CONF_WEATHER_ENTITY] = values.pop(
                    CONF_WEATHER_ENTITY, ""
                )
            if "evaluation_interval_minutes" in values:
                interval_minutes = float(values.pop("evaluation_interval_minutes"))
                values[CONF_EVALUATION_INTERVAL] = max(60, int(interval_minutes * 60))
            self._working.update(values)
            if not bool(self._working.get(CONF_ADVANCED_MODE, False)):
                self._working[CONF_DIAGNOSTIC_LEVEL] = "off"
                self._working[CONF_TEST_MODE] = False
            return await self.async_step_init()
        fields: dict[Any, Any] = {
            vol.Required(CONF_ADVANCED_MODE): selector.BooleanSelector(),
        }
        if not self.advanced_mode:
            fields[vol.Optional(CONF_WEATHER_ENTITY)] = _entity("weather")
        if self.advanced_mode:
            fields.update(
                {
                    vol.Required(CONF_DIAGNOSTIC_LEVEL): self._choice(
                        DIAGNOSTIC_OPTIONS, "diagnostic_level"
                    ),
                    vol.Required("evaluation_interval_minutes"): _number(1, 60, 1, "min"),
                    vol.Required(CONF_SUN_ENTITY): _entity("sun"),
                    vol.Required("position_tolerance"): _number(0, 10, 1, "%"),
                    vol.Required("tilt_tolerance"): _number(0, 15, 1, "%"),
                    vol.Required("command_cooldown"): _number(0, 600, 10, "s"),
                    vol.Required("unknown_feedback_policy"): self._choice(
                        ["send", "skip"], "feedback_policy"
                    ),
                    vol.Required("evening_release_time"): selector.TimeSelector(),
                    vol.Required("sunset_offset_minutes"): _number(-120, 120, 5, "min"),
                }
            )
        suggested = dict(self._working)
        suggested["evaluation_interval_minutes"] = max(1, int(
            float(self._working.get(CONF_EVALUATION_INTERVAL, DEFAULT_EVALUATION_INTERVAL)) / 60
        ))
        return self.async_show_form(
            step_id="global_settings",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(fields), _nonempty_suggestions(suggested)
            ),
            description_placeholders={"card_resource": CARD_RESOURCE},
        )

    async def async_step_add_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            room = deepcopy(ROOM_DEFAULTS)
            room.update(user_input)
            room["id"] = _new_id(room["name"])
            room["sectors"] = []
            room.setdefault("safety_blockers", [])
            if room.get("indoor_temperature"):
                room["indoor_temperature_name"] = self._friendly_name(
                    room["indoor_temperature"],
                    "Raumtemperatur" if self._is_german() else "Room temperature",
                )
            if room.get("outdoor_temperature"):
                room["outdoor_temperature_name"] = self._friendly_name(
                    room["outdoor_temperature"],
                    "Außentemperatur" if self._is_german() else "Outdoor temperature",
                )
            self.rooms.append(room)
            self._room_id = room["id"]
            return await self.async_step_room_schedule()
        return self.async_show_form(
            step_id="add_room",
            data_schema=vol.Schema(
                {
                    vol.Required("name"): selector.TextSelector(),
                    vol.Optional("indoor_temperature"): _temperature_entity(),
                    vol.Optional("outdoor_temperature"): _temperature_entity(),
                    vol.Optional("safety_blockers"): _entity(
                        "binary_sensor", multiple=True
                    ),
                }
            ),
        )

    async def _async_after_schedule(self) -> ConfigFlowResult:
        return await self.async_step_room_pause_setup()

    async def _async_after_pause_setup(self) -> ConfigFlowResult:
        # Temperature tuning depends on the selected cover profiles and is
        # therefore available after the room has at least one cover group.
        return await self.async_step_sector_direction()

    async def async_step_room_pause_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        room = self.room()
        if user_input is not None:
            room.update(user_input)
            mode = user_input["default_pause_mode"]
            if mode in {PAUSE_NEXT_SUNRISE, PAUSE_NEXT_SUNSET}:
                return await self.async_step_room_pause_sun_setup()
            if mode == PAUSE_TIMED:
                return await self.async_step_room_pause_duration_setup()
            return await self._async_after_pause_setup()
        schema = vol.Schema(
            {
                vol.Required("default_pause_mode"): self._choice(
                    [PAUSE_NEXT_SUNRISE, PAUSE_NEXT_SUNSET, PAUSE_TIMED, PAUSE_MANUAL],
                    "pause_mode",
                ),
                vol.Required("heat_during_pause"): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="room_pause_setup",
            data_schema=self.add_suggested_values_to_schema(schema, room),
        )

    async def async_step_room_pause_sun_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        room = self.room()
        if user_input is not None:
            room.update(user_input)
            return await self._async_after_pause_setup()
        schema = vol.Schema(
            {vol.Required("pause_sun_offset_minutes"): _number(-120, 240, 5, "min")}
        )
        return self.async_show_form(
            step_id="room_pause_sun_setup",
            data_schema=self.add_suggested_values_to_schema(schema, room),
        )

    async def async_step_room_pause_duration_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        room = self.room()
        if user_input is not None:
            room.update(user_input)
            return await self._async_after_pause_setup()
        schema = vol.Schema(
            {vol.Required("pause_duration_hours"): _number(0.5, 72, 0.5, "h")}
        )
        return self.async_show_form(
            step_id="room_pause_duration_setup",
            data_schema=self.add_suggested_values_to_schema(schema, room),
        )

    async def async_step_room_advanced_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        room = self.room()
        errors: dict[str, str] = {}
        if user_input is not None and not self.advanced_mode:
            comfort = float(user_input["comfort_temperature"])
            solar = float(user_input["solar_temperature"])
            heat = float(user_input["heat_temperature"])
            release = float(user_input["heat_release_temperature"])
            reopen = float(user_input["reopen_temperature"])
            if not comfort < solar < heat:
                errors["base"] = "temperature_order"
            elif not reopen < release < heat:
                errors["base"] = "release_order"
            else:
                room.update(user_input)
                return await self.async_step_sector_direction()
        schema = vol.Schema(
            {
                vol.Required("comfort_temperature"): _number(5, 40, 0.1, "°C"),
                vol.Required("solar_temperature"): _number(5, 40, 0.1, "°C"),
                vol.Required("heat_temperature"): _number(5, 45, 0.1, "°C"),
                vol.Required("heat_release_temperature"): _number(5, 45, 0.1, "°C"),
                vol.Required("reopen_temperature"): _number(5, 35, 0.1, "°C"),
            }
        )
        return self.async_show_form(
            step_id="room_advanced_setup",
            data_schema=self.add_suggested_values_to_schema(schema, room),
            errors=errors,
        )

    async def async_step_room_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            profile = user_input["schedule_profile"]
            room = self.room()
            room["schedule_profile"] = profile
            if profile == SCHEDULE_SUMMER:
                room["active_months"] = [5, 6, 7, 8, 9]
            elif profile != SCHEDULE_CUSTOM:
                room["active_months"] = list(range(1, 13))
            if profile == SCHEDULE_CUSTOM:
                return await self.async_step_room_schedule_custom()
            return await self._async_after_schedule()
        return self.async_show_form(
            step_id="room_schedule",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "schedule_profile",
                        default=self.room().get("schedule_profile", "year_round"),
                    ): self._choice(SCHEDULE_OPTIONS, "schedule_profile")
                }
            ),
        )

    async def async_step_room_schedule_custom(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        room = self.room()
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get("active_months"):
                errors["active_months"] = "select_at_least_one"
            elif not user_input.get("active_weekdays"):
                errors["active_weekdays"] = "select_at_least_one"
            else:
                room.update(user_input)
                if user_input.get("day_window") == DAY_WINDOW_FIXED:
                    return await self.async_step_room_schedule_time()
                room["start_time"] = "00:00:00"
                room["end_time"] = "23:59:59"
                return await self._async_after_schedule()
        schema = vol.Schema(
            {
                vol.Required("active_months"): self._choice(
                    [str(value) for value in range(1, 13)],
                    "months",
                    multiple=True,
                ),
                vol.Required("active_weekdays"): self._choice(
                    [str(value) for value in range(7)],
                    "weekdays",
                    multiple=True,
                ),
                vol.Required("day_window"): self._choice(
                    DAY_WINDOW_OPTIONS, "day_window"
                ),
                vol.Required("outside_schedule_behavior"): self._choice(
                    OUTSIDE_OPTIONS, "outside_schedule_behavior"
                ),
                vol.Required("heat_outside_schedule"): selector.BooleanSelector(),
            }
        )
        suggested = {
            **room,
            "active_months": [str(v) for v in room.get("active_months", range(1, 13))],
            "active_weekdays": [str(v) for v in room.get("active_weekdays", range(7))],
        }
        if user_input:
            suggested.update(user_input)
        return self.async_show_form(
            step_id="room_schedule_custom",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
        )

    async def async_step_room_schedule_time(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        room = self.room()
        if user_input is not None:
            room.update(user_input)
            return await self._async_after_schedule()
        schema = vol.Schema(
            {
                vol.Required("start_time"): selector.TimeSelector(),
                vol.Required("end_time"): selector.TimeSelector(),
            }
        )
        return self.async_show_form(
            step_id="room_schedule_time",
            data_schema=self.add_suggested_values_to_schema(schema, room),
        )

    async def async_step_add_sector(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_sector_direction(user_input)

    async def async_step_sector_direction(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            direction = user_input["direction"]
            sector = self._direction_defaults(direction)
            sector["id"] = _new_id(sector["name"])
            self._pending_sector = sector
            return await self.async_step_sector_identity()
        return self.async_show_form(
            step_id="sector_direction",
            data_schema=vol.Schema(
                {
                    vol.Required("direction", default="south"): self._choice(
                        DIRECTION_OPTIONS, "direction_preset"
                    )
                }
            ),
        )

    async def async_step_sector_identity(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._pending_sector is not None
        if user_input is not None:
            self._pending_sector["name"] = str(user_input["name"]).strip()
            self._pending_sector["short"] = str(user_input["short"]).strip().upper()
            self._pending_sector["id"] = _new_id(self._pending_sector["name"])
            if self._pending_sector.get("direction") == DIRECTION_CUSTOM or self.advanced_mode:
                return await self.async_step_sector_geometry()
            return await self.async_step_sector_lux()
        return self.async_show_form(
            step_id="sector_identity",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required("name"): selector.TextSelector(),
                        vol.Required("short"): selector.TextSelector(),
                    }
                ),
                self._pending_sector,
            ),
        )

    async def async_step_sector_geometry(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Compatibility and expert step for manual sector geometry.

        The customer wizard normally uses the direction preset directly and
        keeps these values under advanced settings. This step remains available
        for older in-progress beta flows and explicit fine tuning.
        """
        assert self._pending_sector is not None
        if user_input is not None:
            self._pending_sector.update(user_input)
            return await self.async_step_sector_lux()
        schema = vol.Schema(
            {
                vol.Required("name"): selector.TextSelector(),
                vol.Required("short"): selector.TextSelector(),
                vol.Required("azimuth_start"): _number(0, 359, 1, "°"),
                vol.Required("azimuth_end"): _number(0, 359, 1, "°"),
                vol.Required("elevation_min"): _number(-10, 90, 1, "°"),
            }
        )
        return self.async_show_form(
            step_id="sector_geometry",
            data_schema=self.add_suggested_values_to_schema(
                schema, self._pending_sector
            ),
        )

    async def async_step_sector_lux(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._pending_sector is not None
        if user_input is not None:
            self._pending_sector.update(user_input)
            preset = user_input.get("sun_preset", PRESET_MEDIUM)
            if preset in SUN_PRESETS:
                self._pending_sector.update(SUN_PRESETS[preset])
            if user_input.get("lux_sensor") and preset == PRESET_CUSTOM:
                return await self.async_step_sector_lux_custom()
            self._append_pending_sector()
            return await self.async_step_add_layer()
        return self.async_show_form(
            step_id="sector_lux",
            data_schema=vol.Schema(
                {
                    vol.Optional("lux_sensor"): _entity("sensor"),
                    vol.Required("sun_preset", default=PRESET_MEDIUM): self._choice(
                        SUN_PRESET_OPTIONS, "sun_preset"
                    ),
                }
            ),
        )

    async def async_step_sector_lux_custom(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._pending_sector is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            if float(user_input["sun_on_lux"]) <= float(user_input["sun_off_lux"]):
                errors["base"] = "lux_hysteresis"
            else:
                self._pending_sector.update(user_input)
                self._append_pending_sector()
                return await self.async_step_add_layer()
        defaults = {
            **SUN_PRESETS[PRESET_MEDIUM],
            **self._pending_sector,
        }
        schema = vol.Schema(
            {
                vol.Required("sun_on_lux"): _number(0, 200000, 500, "lx"),
                vol.Required("sun_off_lux"): _number(0, 200000, 500, "lx"),
                vol.Required("sun_on_delay"): _number(0, 60, 0.5, "min"),
                vol.Required("sun_off_delay"): _number(0, 120, 0.5, "min"),
            }
        )
        return self.async_show_form(
            step_id="sector_lux_custom",
            data_schema=self.add_suggested_values_to_schema(schema, defaults),
            errors=errors,
        )

    async def async_step_add_layer(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._pending_layer = self._new_layer(
                user_input["name"], user_input["profile"]
            )
            if user_input["profile"] in {DEVICE_VENETIAN, DEVICE_VERTICAL}:
                return await self.async_step_layer_tilt_profile()
            self._append_pending_layer()
            return await self.async_step_add_covers()
        return self.async_show_form(
            step_id="add_layer",
            data_schema=vol.Schema(
                {
                    vol.Required("name"): selector.TextSelector(),
                    vol.Required("profile", default=DEVICE_VENETIAN): self._choice(
                        DEVICE_TYPES, "device_type"
                    ),
                }
            ),
        )

    async def async_step_layer_tilt_profile(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._pending_layer is not None
        if user_input is not None:
            preset = user_input["tilt_preset"]
            self._pending_layer["tilt_preset"] = preset
            if preset == TILT_PRESET_CUSTOM:
                return await self.async_step_layer_tilt_custom()
            self._pending_layer["tilt_curve"] = deepcopy(TILT_CURVE_PRESETS[preset])
            self._append_pending_layer()
            return await self.async_step_add_covers()
        return self.async_show_form(
            step_id="layer_tilt_profile",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "tilt_preset", default=TILT_PRESET_BALANCED
                    ): self._choice(TILT_PRESET_OPTIONS, "tilt_preset")
                }
            ),
        )

    async def async_step_layer_tilt_custom(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._pending_layer is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            elevations = [float(user_input[f"elevation_{i}"]) for i in range(1, 5)]
            if elevations != sorted(elevations) or len(set(elevations)) != 4:
                errors["base"] = "elevation_order"
            else:
                self._pending_layer["tilt_curve"] = [
                    {
                        "elevation": user_input[f"elevation_{i}"],
                        "tilt": user_input[f"tilt_{i}"],
                    }
                    for i in range(1, 5)
                ]
                self._append_pending_layer()
                return await self.async_step_add_covers()
        points = deepcopy(
            self._pending_layer.get(
                "tilt_curve", TILT_CURVE_PRESETS[TILT_PRESET_BALANCED]
            )
        )
        schema_data: dict[Any, Any] = {}
        for index, point in enumerate(points, start=1):
            schema_data[
                vol.Required(f"elevation_{index}", default=point["elevation"])
            ] = _number(-10, 90, 1, "°")
            schema_data[
                vol.Required(f"tilt_{index}", default=point["tilt"])
            ] = _number(0, 100, 1, "%")
        return self.async_show_form(
            step_id="layer_tilt_custom",
            data_schema=vol.Schema(schema_data),
            errors=errors,
        )

    async def async_step_add_cover(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_add_covers(user_input)

    async def async_step_add_covers(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            entities = list(user_input.get("cover_entities", []))
            duplicates = sorted(set(entities) & self.all_cover_entities())
            if duplicates:
                errors["base"] = "cover_already_assigned"
            elif not entities:
                errors["cover_entities"] = "select_at_least_one"
            else:
                self._pending_cover_entities = entities
                self._pending_cover_index = 0
                return await self.async_step_name_selected_cover()
        return self.async_show_form(
            step_id="add_covers",
            data_schema=vol.Schema(
                {
                    vol.Required("cover_entities"): _entity(
                        "cover", multiple=True
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_name_selected_cover(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entities = list(getattr(self, "_pending_cover_entities", []))
        index = int(getattr(self, "_pending_cover_index", 0))
        if not entities or index >= len(entities):
            self._pending_cover_entities = []
            self._pending_cover_index = 0
            return await self.async_step_after_room()

        entity_id = entities[index]
        fallback = f"{'Behang' if self._is_german() else 'Cover'} {index + 1}"
        suggested_name = self._friendly_name(entity_id, fallback)
        suggested_short = self._cover_short(index)
        if user_input is not None:
            name = str(user_input.get("name") or suggested_name).strip()
            short = str(user_input.get("short") or suggested_short).strip().upper()
            self.layer().setdefault("covers", []).append(
                _default_cover(entity_id, name, short)
            )
            self._pending_cover_index = index + 1
            return await self.async_step_name_selected_cover()

        return self.async_show_form(
            step_id="name_selected_cover",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required("name"): selector.TextSelector(),
                        vol.Required("short"): selector.TextSelector(),
                    }
                ),
                {"name": suggested_name, "short": suggested_short},
            ),
            description_placeholders={
                "entity_name": suggested_name,
                "current": str(index + 1),
                "count": str(len(entities)),
            },
        )

    async def async_step_after_room(self, user_input=None) -> ConfigFlowResult:
        options = [
            "configure_current_room",
            "add_more_covers",
            "add_another_layer",
            "add_another_sector",
            "add_another_room",
            "finish",
        ]
        return self.async_show_menu(step_id="after_room", menu_options=self._menu(options))

    async def async_step_configure_current_room(self, user_input=None):
        return await self.async_step_room_actions()

    async def async_step_back_to_overview(self, user_input=None):
        if isinstance(self, SmartShadingOptionsFlow):
            return await self.async_step_init()
        return await self.async_step_after_room()

    async def async_step_add_more_covers(self, user_input=None):
        return await self.async_step_add_covers()

    async def async_step_add_another_layer(self, user_input=None):
        return await self.async_step_add_layer()

    async def async_step_add_another_sector(self, user_input=None):
        return await self.async_step_sector_direction()

    async def async_step_add_another_room(self, user_input=None):
        return await self.async_step_add_room()

    async def async_step_select_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if not self.rooms:
            return self.async_abort(reason="no_rooms")
        if user_input is not None:
            self._room_id = user_input["room_id"]
            return await self.async_step_room_actions()
        return self.async_show_form(
            step_id="select_room",
            data_schema=vol.Schema(
                {
                    vol.Required("room_id"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"value": room["id"], "label": room["name"]}
                                for room in self.rooms
                            ],
                            mode="dropdown",
                        )
                    )
                }
            ),
        )

    async def async_step_room_actions(self, user_input=None) -> ConfigFlowResult:
        options = [
            "edit_room_basic",
            "edit_room_schedule",
            "edit_room_pause",
        ]
        if self.advanced_mode:
            options.append("edit_room_night")
        options.extend([
            "room_advanced",
            "add_sector",
            "select_sector",
            "delete_room",
            "back_to_overview",
        ])
        return self.async_show_menu(
            step_id="room_actions",
            menu_options=self._menu(options),
        )

    async def async_step_edit_room_basic(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        room = self.room()
        if user_input is not None:
            for key in (
                "name",
                "indoor_temperature",
                "outdoor_temperature",
                "safety_blockers",
                "indoor_temperature_name",
                "outdoor_temperature_name",
            ):
                if key in user_input:
                    room[key] = user_input.get(key, [] if key == "safety_blockers" else "")
            return await self.async_step_room_actions()
        fields: dict[Any, Any] = {
            vol.Required("name"): selector.TextSelector(),
            vol.Optional("indoor_temperature"): _temperature_entity(),
            vol.Optional("outdoor_temperature"): _temperature_entity(),
            vol.Optional("safety_blockers"): _entity("binary_sensor", multiple=True),
        }
        if self.advanced_mode:
            fields[vol.Optional("indoor_temperature_name")] = selector.TextSelector()
            fields[vol.Optional("outdoor_temperature_name")] = selector.TextSelector()
        return self.async_show_form(
            step_id="edit_room_basic",
            data_schema=self.add_suggested_values_to_schema(vol.Schema(fields), room),
        )

    async def async_step_edit_room_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            profile = user_input["schedule_profile"]
            room = self.room()
            room["schedule_profile"] = profile
            if profile == SCHEDULE_SUMMER:
                room["active_months"] = [5, 6, 7, 8, 9]
            elif profile != SCHEDULE_CUSTOM:
                room["active_months"] = list(range(1, 13))
            if profile == SCHEDULE_CUSTOM:
                self._return_to_room_actions = True
                return await self.async_step_edit_room_schedule_custom()
            return await self.async_step_room_actions()
        return self.async_show_form(
            step_id="edit_room_schedule",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "schedule_profile",
                        default=self.room().get("schedule_profile", "year_round"),
                    ): self._choice(SCHEDULE_OPTIONS, "schedule_profile")
                }
            ),
        )

    async def async_step_edit_room_schedule_custom(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        room = self.room()
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get("active_months") or not user_input.get("active_weekdays"):
                errors["base"] = "select_at_least_one"
            else:
                room.update(user_input)
                if user_input.get("day_window") == DAY_WINDOW_FIXED:
                    return await self.async_step_edit_room_schedule_time()
                room["start_time"] = "00:00:00"
                room["end_time"] = "23:59:59"
                return await self.async_step_room_actions()
        schema = vol.Schema(
            {
                vol.Required("active_months"): self._choice(
                    [str(value) for value in range(1, 13)], "months", multiple=True
                ),
                vol.Required("active_weekdays"): self._choice(
                    [str(value) for value in range(7)], "weekdays", multiple=True
                ),
                vol.Required("day_window"): self._choice(DAY_WINDOW_OPTIONS, "day_window"),
                vol.Required("outside_schedule_behavior"): self._choice(
                    OUTSIDE_OPTIONS, "outside_schedule_behavior"
                ),
                vol.Required("heat_outside_schedule"): selector.BooleanSelector(),
            }
        )
        suggested = {
            **room,
            "active_months": [str(v) for v in room.get("active_months", range(1, 13))],
            "active_weekdays": [str(v) for v in room.get("active_weekdays", range(7))],
        }
        return self.async_show_form(
            step_id="edit_room_schedule_custom",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
        )

    async def async_step_edit_room_schedule_time(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        room = self.room()
        if user_input is not None:
            room.update(user_input)
            return await self.async_step_room_actions()
        schema = vol.Schema(
            {
                vol.Required("start_time"): selector.TimeSelector(),
                vol.Required("end_time"): selector.TimeSelector(),
            }
        )
        return self.async_show_form(
            step_id="edit_room_schedule_time",
            data_schema=self.add_suggested_values_to_schema(schema, room),
        )

    async def async_step_edit_room_pause(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        room = self.room()
        if user_input is not None:
            room.update(user_input)
            return await self.async_step_room_actions()
        pause_modes = [
            PAUSE_NEXT_SUNRISE,
            PAUSE_NEXT_SUNSET,
            PAUSE_TIMED,
            PAUSE_MANUAL,
        ]
        if self.advanced_mode and room.get("night_enabled", False):
            pause_modes.insert(2, PAUSE_NEXT_NIGHT_END)
        schema = vol.Schema(
            {
                vol.Required("default_pause_mode"): self._choice(
                    pause_modes, "pause_mode",
                ),
                vol.Required("pause_sun_offset_minutes"): _number(-120, 240, 5, "min"),
                vol.Required("pause_duration_hours"): _number(0.5, 72, 0.5, "h"),
                vol.Required("heat_during_pause"): selector.BooleanSelector(),
                vol.Required(
                    CONF_EXTERNAL_MOVEMENT_DETECTION,
                    default=DEFAULT_EXTERNAL_MOVEMENT_DETECTION,
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="edit_room_pause",
            data_schema=self.add_suggested_values_to_schema(schema, room),
        )

    async def async_step_edit_room_night(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if not self.advanced_mode:
            return await self.async_step_room_actions()
        room = self.room()
        if user_input is not None:
            room.update(user_input)
            if not room.get("night_enabled", False):
                if room.get("default_pause_mode") == PAUSE_NEXT_NIGHT_END:
                    room["default_pause_mode"] = PAUSE_MANUAL
                return await self.async_step_room_actions()
            if room.get("night_source") == "sun":
                return await self.async_step_edit_room_night_sun()
            return await self.async_step_edit_room_night_entity()
        schema = vol.Schema(
            {
                vol.Required("night_enabled"): selector.BooleanSelector(),
                vol.Required("night_source"): self._choice(
                    ["entity", "sun"], "night_source"
                ),
                vol.Required("night_morning_transition_minutes"): _number(
                    0, 120, 5, "min"
                ),
                vol.Required("night_evening_transition_minutes"): _number(
                    0, 120, 5, "min"
                ),
            }
        )
        return self.async_show_form(
            step_id="edit_room_night",
            data_schema=self.add_suggested_values_to_schema(schema, room),
        )

    async def async_step_edit_room_night_entity(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        room = self.room()
        if user_input is not None:
            room.update(user_input)
            return await self.async_step_room_actions()
        schema = vol.Schema(
            {
                vol.Required("night_entity"): _entity(
                    ["schedule", "input_boolean", "binary_sensor", "switch"]
                )
            }
        )
        return self.async_show_form(
            step_id="edit_room_night_entity",
            data_schema=self.add_suggested_values_to_schema(schema, room),
        )

    async def async_step_edit_room_night_sun(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        room = self.room()
        if user_input is not None:
            room.update(user_input)
            return await self.async_step_room_actions()
        schema = vol.Schema(
            {
                vol.Required("night_start_offset_minutes"): _number(
                    -240, 240, 5, "min"
                ),
                vol.Required("night_end_offset_minutes"): _number(
                    -240, 240, 5, "min"
                ),
            }
        )
        return self.async_show_form(
            step_id="edit_room_night_sun",
            data_schema=self.add_suggested_values_to_schema(schema, room),
        )

    async def async_step_room_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        room = self.room()
        errors: dict[str, str] = {}
        if user_input is not None:
            heat = float(user_input["heat_temperature"])
            release = float(user_input["heat_release_temperature"])
            reopen = float(user_input["reopen_temperature"])
            if self._venetian_only(room):
                normal = float(user_input["normal_shading_temperature"])
                if not reopen < normal < heat:
                    errors["base"] = "normal_temperature_order"
                elif not reopen < release < heat:
                    errors["base"] = "release_order"
                else:
                    room.update(user_input)
                    room["comfort_temperature"] = normal
                    room["solar_temperature"] = normal
                    return await self.async_step_room_actions()
            else:
                comfort = float(user_input["comfort_temperature"])
                solar = float(user_input["solar_temperature"])
                if not comfort < solar < heat:
                    errors["base"] = "temperature_order"
                elif not reopen < release < heat:
                    errors["base"] = "release_order"
                else:
                    room.update(user_input)
                    return await self.async_step_room_actions()
        temperature_fields: dict[Any, Any] = {
            vol.Required("heat_temperature"): _number(5, 45, 0.1, "°C"),
            vol.Required("heat_release_temperature"): _number(5, 45, 0.1, "°C"),
            vol.Required("reopen_temperature"): _number(5, 35, 0.1, "°C"),
        }
        if self._venetian_only(room):
            temperature_fields = {
                vol.Required("normal_shading_temperature"): _number(5, 40, 0.1, "°C"),
                **temperature_fields,
            }
        else:
            temperature_fields = {
                vol.Required("comfort_temperature"): _number(5, 40, 0.1, "°C"),
                vol.Required("solar_temperature"): _number(5, 40, 0.1, "°C"),
                **temperature_fields,
            }
        schema = vol.Schema(
            {
                **temperature_fields,
                vol.Optional("irradiance_sensor"): _entity("sensor"),
                vol.Optional("cloud_cover_sensor"): _entity("sensor"),
                vol.Optional("weather_permission"): _entity("binary_sensor"),
                vol.Optional("glare_sensor"): _entity("binary_sensor"),
                vol.Optional("occupancy_sensor"): _entity("binary_sensor"),
                vol.Required("weather_logic"): self._choice(["all", "any"], "weather_logic"),
                vol.Required("heat_ignores_weather"): selector.BooleanSelector(),
                vol.Required("heat_fail_safe"): selector.BooleanSelector(),
                vol.Required("heat_requires_sun"): selector.BooleanSelector(),
                vol.Required("comfort_requires_occupancy"): selector.BooleanSelector(),
                vol.Required("safety_behavior"): self._choice(
                    ["move_safe", "block"], "safety_behavior"
                ),
            }
        )
        return self.async_show_form(
            step_id="room_advanced",
            data_schema=self.add_suggested_values_to_schema(schema, room),
            errors=errors,
        )

    async def async_step_select_sector(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        sectors = self.room().get("sectors", [])
        if not sectors:
            return self.async_abort(reason="no_sectors")
        if user_input is not None:
            self._sector_id = user_input["sector_id"]
            return await self.async_step_sector_actions()
        return self.async_show_form(
            step_id="select_sector",
            data_schema=vol.Schema(
                {
                    vol.Required("sector_id"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"value": item["id"], "label": item["name"]}
                                for item in sectors
                            ],
                            mode="dropdown",
                        )
                    )
                }
            ),
        )

    async def async_step_sector_actions(self, user_input=None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="sector_actions",
            menu_options=self._menu([
                "edit_sector_customer",
                "edit_sector_advanced",
                "add_layer",
                "select_layer",
                "delete_sector",
                "room_actions",
            ]),
        )

    async def async_step_edit_sector_customer(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        sector = self.sector()
        if user_input is not None:
            direction = user_input["direction"]
            if direction != sector.get("direction"):
                defaults = self._direction_defaults(direction)
                sector.update(
                    {
                        key: defaults[key]
                        for key in (
                            "direction", "azimuth_start", "azimuth_end", "elevation_min"
                        )
                    }
                )
            sector["name"] = str(user_input["name"]).strip()
            sector["short"] = str(user_input["short"]).strip().upper()
            sector["lux_sensor"] = user_input.get("lux_sensor", "")
            preset = user_input.get("sun_preset", PRESET_MEDIUM)
            sector["sun_preset"] = preset
            if preset in SUN_PRESETS:
                sector.update(SUN_PRESETS[preset])
            if sector.get("lux_sensor") and preset == PRESET_CUSTOM:
                return await self.async_step_edit_sector_lux_custom()
            return await self.async_step_sector_actions()
        schema = vol.Schema(
            {
                vol.Required("direction"): self._choice(DIRECTION_OPTIONS, "direction_preset"),
                vol.Required("name"): selector.TextSelector(),
                vol.Required("short"): selector.TextSelector(),
                vol.Optional("lux_sensor"): _entity("sensor"),
                vol.Required("sun_preset"): self._choice(SUN_PRESET_OPTIONS, "sun_preset"),
            }
        )
        return self.async_show_form(
            step_id="edit_sector_customer",
            data_schema=self.add_suggested_values_to_schema(schema, sector),
        )

    async def async_step_edit_sector_lux_custom(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        sector = self.sector()
        errors: dict[str, str] = {}
        if user_input is not None:
            if float(user_input["sun_on_lux"]) <= float(user_input["sun_off_lux"]):
                errors["base"] = "lux_hysteresis"
            else:
                sector.update(user_input)
                return await self.async_step_sector_actions()
        schema = vol.Schema(
            {
                vol.Required("sun_on_lux"): _number(0, 200000, 500, "lx"),
                vol.Required("sun_off_lux"): _number(0, 200000, 500, "lx"),
                vol.Required("sun_on_delay"): _number(0, 60, 0.5, "min"),
                vol.Required("sun_off_delay"): _number(0, 120, 0.5, "min"),
            }
        )
        return self.async_show_form(
            step_id="edit_sector_lux_custom",
            data_schema=self.add_suggested_values_to_schema(schema, sector),
            errors=errors,
        )

    async def async_step_edit_sector_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        sector = self.sector()
        if user_input is not None:
            sector.update(user_input)
            return await self.async_step_sector_actions()
        schema = vol.Schema(
            {
                vol.Required("name"): selector.TextSelector(),
                vol.Required("short"): selector.TextSelector(),
                vol.Required("azimuth_start"): _number(0, 359, 1, "°"),
                vol.Required("azimuth_end"): _number(0, 359, 1, "°"),
                vol.Required("elevation_min"): _number(-10, 90, 1, "°"),
            }
        )
        return self.async_show_form(
            step_id="edit_sector_advanced",
            data_schema=self.add_suggested_values_to_schema(schema, sector),
        )

    async def async_step_select_layer(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        layers = self.sector().get("layers", [])
        if not layers:
            return self.async_abort(reason="no_layers")
        if user_input is not None:
            self._layer_id = user_input["layer_id"]
            return await self.async_step_layer_actions()
        return self.async_show_form(
            step_id="select_layer",
            data_schema=vol.Schema(
                {
                    vol.Required("layer_id"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"value": item["id"], "label": item["name"]}
                                for item in layers
                            ],
                            mode="dropdown",
                        )
                    )
                }
            ),
        )

    async def async_step_layer_actions(self, user_input=None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="layer_actions",
            menu_options=self._menu([
                "edit_layer_customer",
                "edit_layer_advanced",
                "add_covers",
                "select_cover",
                "remove_covers",
                "delete_layer",
                "sector_actions",
            ]),
        )

    async def async_step_edit_layer_customer(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        layer = self.layer()
        if user_input is not None:
            old_profile = layer.get("profile")
            new_profile = user_input["profile"]
            covers = layer.get("covers", [])
            layer_id = layer["id"]
            if old_profile != new_profile:
                layer.clear()
                layer.update(deepcopy(PROFILE_DEFAULTS[new_profile]))
                layer.update(
                    {
                        "id": layer_id,
                        "name": user_input["name"],
                        "profile": new_profile,
                        "covers": covers,
                    }
                )
            else:
                layer["name"] = user_input["name"]
            if new_profile in {DEVICE_VENETIAN, DEVICE_VERTICAL}:
                return await self.async_step_edit_layer_tilt_profile()
            return await self.async_step_layer_actions()
        return self.async_show_form(
            step_id="edit_layer_customer",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required("name"): selector.TextSelector(),
                        vol.Required("profile"): self._choice(DEVICE_TYPES, "device_type"),
                    }
                ),
                layer,
            ),
        )

    async def async_step_edit_layer_tilt_profile(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        layer = self.layer()
        if user_input is not None:
            preset = user_input["tilt_preset"]
            layer["tilt_preset"] = preset
            if preset == TILT_PRESET_CUSTOM:
                return await self.async_step_edit_layer_tilt_custom()
            layer["tilt_curve"] = deepcopy(TILT_CURVE_PRESETS[preset])
            return await self.async_step_layer_actions()
        return self.async_show_form(
            step_id="edit_layer_tilt_profile",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "tilt_preset",
                        default=layer.get("tilt_preset", TILT_PRESET_BALANCED),
                    ): self._choice(TILT_PRESET_OPTIONS, "tilt_preset")
                }
            ),
        )

    async def async_step_edit_layer_tilt_custom(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        layer = self.layer()
        points = deepcopy(
            layer.get("tilt_curve", TILT_CURVE_PRESETS[TILT_PRESET_BALANCED])
        )
        errors: dict[str, str] = {}
        if user_input is not None:
            elevations = [float(user_input[f"elevation_{i}"]) for i in range(1, 5)]
            if elevations != sorted(elevations) or len(set(elevations)) != 4:
                errors["base"] = "elevation_order"
            else:
                layer["tilt_curve"] = [
                    {
                        "elevation": user_input[f"elevation_{i}"],
                        "tilt": user_input[f"tilt_{i}"],
                    }
                    for i in range(1, 5)
                ]
                return await self.async_step_layer_actions()
        schema_data: dict[Any, Any] = {}
        for index, point in enumerate(points[:4], start=1):
            schema_data[vol.Required(f"elevation_{index}", default=point["elevation"])] = _number(-10, 90, 1, "°")
            schema_data[vol.Required(f"tilt_{index}", default=point["tilt"])] = _number(0, 100, 1, "%")
        return self.async_show_form(
            step_id="edit_layer_tilt_custom",
            data_schema=vol.Schema(schema_data),
            errors=errors,
        )

    async def async_step_edit_layer_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        layer = self.layer()
        if user_input is not None:
            layer.update(user_input)
            return await self.async_step_layer_actions()
        profile = layer.get("profile", DEVICE_VENETIAN)
        fields: dict[Any, Any] = {}
        # Only technically relevant values are exposed for the selected profile.
        if profile == DEVICE_VENETIAN:
            fields = {
                vol.Required("open_position"): _number(0, 100, 1, "%"),
                vol.Required("night_position"): _number(0, 100, 1, "%"),
                vol.Required("night_tilt"): _number(0, 100, 1, "%"),
                vol.Required("safety_position"): _number(0, 100, 1, "%"),
            }
        elif profile == DEVICE_VERTICAL:
            fields = {
                vol.Required("open_position"): _number(0, 100, 1, "%"),
                vol.Required("comfort_tilt"): _number(0, 100, 1, "%"),
                vol.Required("heat_tilt"): _number(0, 100, 1, "%"),
                vol.Required("night_position"): _number(0, 100, 1, "%"),
                vol.Required("night_tilt"): _number(0, 100, 1, "%"),
                vol.Required("safety_position"): _number(0, 100, 1, "%"),
            }
        else:
            fields = {
                vol.Required("open_position"): _number(0, 100, 1, "%"),
                vol.Required("comfort_position"): _number(0, 100, 1, "%"),
                vol.Required("solar_position"): _number(0, 100, 1, "%"),
                vol.Required("heat_position"): _number(0, 100, 1, "%"),
                vol.Required("night_position"): _number(0, 100, 1, "%"),
                vol.Required("safety_position"): _number(0, 100, 1, "%"),
            }
        return self.async_show_form(
            step_id="edit_layer_advanced",
            data_schema=self.add_suggested_values_to_schema(vol.Schema(fields), layer),
        )

    async def async_step_select_cover(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        covers = self.layer().get("covers", [])
        if not covers:
            return self.async_abort(reason="no_covers")
        if user_input is not None:
            self._cover_index = int(user_input["cover_index"])
            return await self.async_step_edit_cover()
        return self.async_show_form(
            step_id="select_cover",
            data_schema=vol.Schema(
                {
                    vol.Required("cover_index"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {
                                    "value": str(index),
                                    "label": cover.get("name") or self._friendly_name(
                                        cover["entity"],
                                        f"{'Behang' if self._is_german() else 'Cover'} {index + 1}",
                                    ),
                                }
                                for index, cover in enumerate(covers)
                            ],
                            mode="dropdown",
                        )
                    )
                }
            ),
        )

    async def async_step_edit_cover(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        cover = self.layer()["covers"][self._cover_index]
        if user_input is not None:
            entity = cover["entity"]
            old_name = cover.get("name") or ("Behang" if self._is_german() else "Cover")
            old_short = cover.get("short", "")
            cover.clear()
            cover.update(_default_cover(entity, user_input.get("name") or old_name, user_input.get("short") or old_short))
            cover.update(user_input)
            cover["entity"] = entity
            return await self.async_step_layer_actions()
        schema = vol.Schema(
            {
                vol.Required("name"): selector.TextSelector(),
                vol.Required("short"): selector.TextSelector(),
                vol.Optional("lock"): _entity(["switch", "input_boolean"]),
                vol.Optional("window"): _entity("binary_sensor"),
                vol.Required("window_safe_state"): self._choice(["on", "off"], "safe_state"),
                vol.Required("window_policy"): self._choice(WINDOW_POLICIES, "window_policy"),
                vol.Required(
                    CONF_WINDOW_RETURNS_TO_AUTOMATION,
                    default=DEFAULT_WINDOW_RETURNS_TO_AUTOMATION,
                ): selector.BooleanSelector(),
                vol.Required("max_open_position"): _number(0, 100, 1, "%"),
                vol.Required("invert_position"): selector.BooleanSelector(),
                vol.Required("invert_tilt"): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="edit_cover",
            data_schema=self.add_suggested_values_to_schema(schema, cover),
        )

    async def async_step_remove_covers(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        covers = self.layer().get("covers", [])
        if not covers:
            return self.async_abort(reason="no_covers")
        if user_input is not None:
            indices = {int(value) for value in user_input["cover_indices"]}
            self.layer()["covers"] = [
                cover for index, cover in enumerate(covers) if index not in indices
            ]
            return await self.async_step_layer_actions()
        return self.async_show_form(
            step_id="remove_covers",
            data_schema=vol.Schema(
                {
                    vol.Required("cover_indices"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {
                                    "value": str(index),
                                    "label": cover.get("name") or self._friendly_name(
                                        cover["entity"],
                                        f"{'Behang' if self._is_german() else 'Cover'} {index + 1}",
                                    ),
                                }
                                for index, cover in enumerate(covers)
                            ],
                            mode="dropdown",
                            multiple=True,
                        )
                    )
                }
            ),
        )

    async def async_step_delete_layer(self, user_input=None):
        self.sector()["layers"] = [
            item for item in self.sector().get("layers", []) if item["id"] != self._layer_id
        ]
        return await self.async_step_sector_actions()

    async def async_step_delete_sector(self, user_input=None):
        self.room()["sectors"] = [
            item for item in self.room().get("sectors", []) if item["id"] != self._sector_id
        ]
        return await self.async_step_room_actions()

    async def async_step_delete_room(self, user_input=None):
        self._working[CONF_ROOMS] = [
            item for item in self.rooms if item["id"] != self._room_id
        ]
        return await self.async_step_back_to_overview()


class SmartShadingConfigFlow(
    _SmartShadingWizardMixin, config_entries.ConfigFlow, domain=DOMAIN
):
    """Initial customer setup. The entry is created after a complete first room."""

    VERSION = 13

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        sun_state = self.hass.states.get("sun.sun")
        if user_input is not None:
            if sun_state is None:
                errors["base"] = "sun_missing"
            elif sun_state.state in {STATE_UNAVAILABLE, STATE_UNKNOWN}:
                errors["base"] = "sun_unavailable"
            else:
                await self.async_set_unique_id(_slug(user_input[CONF_HOUSE_NAME]))
                self._abort_if_unique_id_configured()
                self._working = {
                    CONF_HOUSE_NAME: user_input[CONF_HOUSE_NAME],
                    CONF_SUN_ENTITY: "sun.sun",
                    CONF_DIAGNOSTIC_LEVEL: "off",
                    CONF_TEST_MODE: False,
                    CONF_ADVANCED_MODE: bool(user_input[CONF_ADVANCED_MODE]),
                    CONF_EVALUATION_INTERVAL: DEFAULT_EVALUATION_INTERVAL,
                    "position_tolerance": DEFAULT_POSITION_TOLERANCE,
                    "tilt_tolerance": DEFAULT_TILT_TOLERANCE,
                    "command_cooldown": DEFAULT_COMMAND_COOLDOWN,
                    "unknown_feedback_policy": "send",
                    "evening_release_time": DEFAULT_EVENING_RELEASE_TIME,
                    "sunset_offset_minutes": DEFAULT_SUNSET_OFFSET_MINUTES,
                    CONF_ROOMS: [],
                }
                self._room_id = None
                self._sector_id = None
                self._layer_id = None
                self._cover_index = None
                self._pending_sector = None
                self._pending_layer = None
                self._pending_cover_entities = []
                self._pending_cover_index = 0
                return await self.async_step_room_setup()
        current_sun_state = "missing" if sun_state is None else sun_state.state
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOUSE_NAME): selector.TextSelector(),
                    vol.Required(CONF_ADVANCED_MODE, default=False): selector.BooleanSelector(),
                }
            ),
            errors=errors,
            description_placeholders={"sun_state": current_sun_state},
        )


    async def async_step_room_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the first room in one page, keeping setup two levels deep."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = _flatten_sections(user_input)
            entities = list(user_input.get("cover_entities", []))
            if not entities:
                errors["base"] = "select_at_least_one"
            elif not self.advanced_mode and user_input.get("lux_sensor") and user_input.get(
                CONF_SUN_PRESENCE_ENTITY
            ):
                errors["base"] = "choose_one_sun_confirmation"
            else:
                if self.advanced_mode:
                    diagnostic_level = str(
                        user_input.get(CONF_DIAGNOSTIC_LEVEL, DIAGNOSTIC_EVENTS)
                    )
                    self._working[CONF_DIAGNOSTIC_LEVEL] = diagnostic_level
                    self._working[CONF_TEST_MODE] = diagnostic_level != "off"
                    self._working[CONF_EVALUATION_INTERVAL] = max(
                        60,
                        int(float(user_input.get("evaluation_interval_minutes", 20)) * 60),
                    )
                direction = str(user_input.get("direction", "south"))
                sector = self._direction_defaults(direction)
                sector["id"] = _new_id(sector["name"])
                sector["direction"] = direction
                sector["lux_sensor"] = user_input.get("lux_sensor", "")
                sector[CONF_SUN_PRESENCE_ENTITY] = (
                    user_input.get(CONF_SUN_PRESENCE_ENTITY, "")
                    if not self.advanced_mode
                    else ""
                )
                sector["sun_preset"] = user_input.get(
                    "sun_preset", PRESET_MEDIUM
                )
                if self.advanced_mode and direction == DIRECTION_CUSTOM:
                    for key in ("azimuth_start", "azimuth_end", "elevation_min"):
                        sector[key] = float(user_input[key])
                if not self.advanced_mode:
                    self._working[CONF_WEATHER_ENTITY] = user_input.get(
                        CONF_WEATHER_ENTITY, ""
                    )

                profile = str(user_input.get("profile", DEVICE_VENETIAN))
                group_name = str(
                    user_input.get("group_name")
                    or ("Behanggruppe" if self._is_german() else "Cover group")
                )
                layer = self._new_layer(group_name, profile)
                if profile in {DEVICE_VENETIAN, DEVICE_VERTICAL}:
                    preset = str(user_input.get("tilt_preset", TILT_PRESET_BALANCED))
                    layer["tilt_preset"] = preset
                    layer["tilt_curve"] = deepcopy(
                        TILT_CURVE_PRESETS.get(preset, TILT_CURVE_PRESETS[TILT_PRESET_BALANCED])
                    )
                layer["covers"] = [
                    _default_cover(
                        entity_id,
                        self._friendly_name(
                            entity_id,
                            f"{'Behang' if self._is_german() else 'Cover'} {index + 1}",
                        ),
                        self._cover_short(index),
                    )
                    for index, entity_id in enumerate(entities)
                ]
                sector["layers"] = [layer]

                room = deepcopy(ROOM_DEFAULTS)
                room["id"] = _new_id(str(user_input["name"]))
                room["name"] = str(user_input["name"])
                room["sectors"] = [sector]
                room["outdoor_temperature"] = user_input.get(
                    "outdoor_temperature", ""
                )
                room["outdoor_minimum"] = float(
                    user_input.get("outdoor_minimum", 18.0)
                )
                room[CONF_EASY_TEMPERATURE_GATE] = bool(
                    user_input.get(CONF_EASY_TEMPERATURE_GATE, False)
                ) if not self.advanced_mode else False
                room[CONF_EXTERNAL_MOVEMENT_DETECTION] = bool(
                    user_input.get(
                        CONF_EXTERNAL_MOVEMENT_DETECTION,
                        DEFAULT_EXTERNAL_MOVEMENT_DETECTION,
                    )
                ) if self.advanced_mode else False
                if self.advanced_mode:
                    room.update({
                        "indoor_temperature": user_input.get("indoor_temperature", ""),
                        "safety_blockers": list(user_input.get("safety_blockers", [])),
                        "schedule_profile": user_input.get("schedule_profile", SCHEDULE_YEAR_ROUND),
                        "default_pause_mode": user_input.get("default_pause_mode", PAUSE_NEXT_SUNRISE),
                        "heat_during_pause": bool(user_input.get("heat_during_pause", False)),
                    })
                    room["active_months"] = (
                        [5, 6, 7, 8, 9]
                        if room["schedule_profile"] == SCHEDULE_SUMMER
                        else list(range(1, 13))
                    )
                self.rooms.append(room)
                return self.async_create_entry(
                    title=self._working[CONF_HOUSE_NAME], data=self._working
                )

        room_fields: dict[Any, Any] = {
            vol.Required("name"): selector.TextSelector(),
            vol.Required("direction", default="south"): self._choice(
                DIRECTION_OPTIONS
                if self.advanced_mode
                else [item for item in DIRECTION_OPTIONS if item != DIRECTION_CUSTOM],
                "direction_preset",
            ),
            vol.Required(
                "group_name",
                default="Behanggruppe" if self._is_german() else "Cover group",
            ): selector.TextSelector(),
            vol.Required("profile", default=DEVICE_VENETIAN): self._choice(
                DEVICE_TYPES, "device_type"
            ),
            vol.Required("cover_entities"): _entity("cover", multiple=True),
        }
        sun_fields: dict[Any, Any] = {
            vol.Optional("lux_sensor"): _entity("sensor"),
            vol.Required("sun_preset", default=PRESET_MEDIUM): self._choice(
                ["low", "medium", "high"], "sun_preset"
            ),
        }
        if not self.advanced_mode:
            sun_fields[vol.Optional(CONF_SUN_PRESENCE_ENTITY)] = _entity(
                ["binary_sensor", "input_boolean", "switch"]
            )
        optional_fields: dict[Any, Any] = {
            vol.Optional(CONF_WEATHER_ENTITY): _entity("weather"),
            vol.Required(
                CONF_EASY_TEMPERATURE_GATE, default=False
            ): selector.BooleanSelector(),
            vol.Optional("outdoor_temperature"): _temperature_entity(),
            vol.Required("outdoor_minimum", default=18.0): _number(
                -20, 40, 0.5, "°C"
            ),
        }
        if self.advanced_mode:
            defaults = DIRECTION_PRESETS["south"]
            sun_fields.update({
                vol.Required(
                    "azimuth_start", default=defaults["azimuth_start"]
                ): _number(0, 359, 1, "°"),
                vol.Required(
                    "azimuth_end", default=defaults["azimuth_end"]
                ): _number(0, 359, 1, "°"),
                vol.Required(
                    "elevation_min", default=defaults["elevation_min"]
                ): _number(-10, 90, 1, "°"),
            })
            advanced_fields: dict[Any, Any] = {
                vol.Optional("indoor_temperature"): _temperature_entity(),
                vol.Optional("outdoor_temperature"): _temperature_entity(),
                vol.Required("outdoor_minimum", default=18.0): _number(
                    -20, 40, 0.5, "°C"
                ),
                vol.Optional("safety_blockers"): _entity("binary_sensor", multiple=True),
                vol.Required("schedule_profile", default=SCHEDULE_YEAR_ROUND): self._choice(
                    ["year_round", "summer"], "schedule_profile"
                ),
                vol.Required("default_pause_mode", default=PAUSE_NEXT_SUNRISE): self._choice(
                    [PAUSE_NEXT_SUNRISE, PAUSE_NEXT_SUNSET, PAUSE_TIMED, PAUSE_MANUAL],
                    "pause_mode",
                ),
                vol.Required("heat_during_pause", default=False): selector.BooleanSelector(),
                vol.Required(
                    CONF_EXTERNAL_MOVEMENT_DETECTION,
                    default=DEFAULT_EXTERNAL_MOVEMENT_DETECTION,
                ): selector.BooleanSelector(),
                vol.Required(CONF_DIAGNOSTIC_LEVEL, default=DIAGNOSTIC_EVENTS): self._choice(
                    DIAGNOSTIC_OPTIONS, "diagnostic_level"
                ),
                vol.Required("evaluation_interval_minutes", default=20): _number(
                    1, 60, 1, "min"
                ),
            }
        form_fields: dict[Any, Any] = {
            vol.Required("room_and_covers"): section(
                vol.Schema(room_fields), {"collapsed": False}
            ),
            vol.Required("sun_control"): section(
                vol.Schema(sun_fields), {"collapsed": False}
            ),
        }
        if self.advanced_mode:
            form_fields[vol.Required("advanced_conditions")] = section(
                vol.Schema(advanced_fields), {"collapsed": True}
            )
        else:
            form_fields[vol.Required("optional_improvements")] = section(
                vol.Schema(optional_fields), {"collapsed": True}
            )
        return self.async_show_form(
            step_id="room_setup", data_schema=vol.Schema(form_fields), errors=errors
        )

    async def async_step_compact_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Customer setup: room, core sensors, schedule and pause in one page."""
        errors: dict[str, str] = {}
        if user_input is not None:
            room = deepcopy(ROOM_DEFAULTS)
            room.update(user_input)
            room["id"] = _new_id(room["name"])
            room["sectors"] = []
            room.setdefault("safety_blockers", [])
            profile = room.get("schedule_profile", "year_round")
            if profile == SCHEDULE_SUMMER:
                room["active_months"] = [5, 6, 7, 8, 9]
            elif profile != SCHEDULE_CUSTOM:
                room["active_months"] = list(range(1, 13))
            if room.get("indoor_temperature"):
                room["indoor_temperature_name"] = self._friendly_name(
                    room["indoor_temperature"],
                    "Raumtemperatur" if self._is_german() else "Room temperature",
                )
            if room.get("outdoor_temperature"):
                room["outdoor_temperature_name"] = self._friendly_name(
                    room["outdoor_temperature"],
                    "Außentemperatur" if self._is_german() else "Outdoor temperature",
                )
            self.rooms.append(room)
            self._room_id = room["id"]
            if profile == SCHEDULE_CUSTOM:
                return await self.async_step_compact_schedule_custom()
            return await self.async_step_compact_sector()

        schema = vol.Schema(
            {
                vol.Required("name"): selector.TextSelector(),
                vol.Optional("indoor_temperature"): _temperature_entity(),
                vol.Optional("outdoor_temperature"): _temperature_entity(),
                vol.Optional("safety_blockers"): _entity("binary_sensor", multiple=True),
                vol.Required("schedule_profile", default="summer"): self._choice(
                    SCHEDULE_OPTIONS, "schedule_profile"
                ),
                vol.Required("default_pause_mode", default=PAUSE_NEXT_SUNRISE): self._choice(
                    [PAUSE_NEXT_SUNRISE, PAUSE_NEXT_SUNSET, PAUSE_TIMED, PAUSE_MANUAL],
                    "pause_mode",
                ),
                vol.Required("heat_during_pause", default=False): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="compact_room", data_schema=schema)

    async def async_step_compact_schedule_custom(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        room = self.room()
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get("active_months"):
                errors["active_months"] = "select_at_least_one"
            elif not user_input.get("active_weekdays"):
                errors["active_weekdays"] = "select_at_least_one"
            else:
                room.update(user_input)
                return await self.async_step_compact_sector()
        schema = vol.Schema(
            {
                vol.Required("active_months"): self._choice([str(i) for i in range(1, 13)], "months", multiple=True),
                vol.Required("active_weekdays"): self._choice([str(i) for i in range(7)], "weekdays", multiple=True),
                vol.Required("day_window", default="sector_sun"): self._choice(DAY_WINDOW_OPTIONS, "day_window"),
                vol.Required("outside_schedule_behavior", default=OUTSIDE_OPEN): self._choice(OUTSIDE_OPTIONS, "outside_schedule_behavior"),
                vol.Required("heat_outside_schedule", default=True): selector.BooleanSelector(),
            }
        )
        values = {
            "active_months": [str(v) for v in room.get("active_months", range(1, 13))],
            "active_weekdays": [str(v) for v in room.get("active_weekdays", range(7))],
            **room,
        }
        return self.async_show_form(
            step_id="compact_schedule_custom",
            data_schema=self.add_suggested_values_to_schema(schema, values),
            errors=errors,
        )

    async def async_step_compact_sector(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            direction = user_input.get("direction", "south")
            defaults = self._direction_defaults(direction)
            name = str(user_input.get("name") or defaults["name"]).strip()
            short = str(user_input.get("short") or defaults["short"]).strip().upper()
            self._pending_sector = finalize_sector_identity(
                {**defaults, **user_input},
                name=name,
                short=short,
                id_factory=_new_id,
            )
            preset = str(self._pending_sector.get("sun_preset", PRESET_MEDIUM))
            if needs_custom_sun_settings(
                preset=preset, lux_sensor=self._pending_sector.get("lux_sensor")
            ):
                return await self.async_step_compact_sun_custom()
            if preset in SUN_PRESETS:
                self._pending_sector.update(SUN_PRESETS[preset])
            self._append_pending_sector()
            return await self.async_step_compact_layer()
        name, short = _direction_name("south", getattr(self.hass.config, "language", "en") or "en")
        schema = vol.Schema(
            {
                vol.Required("direction", default="south"): self._choice(DIRECTION_OPTIONS, "direction_preset"),
                vol.Optional("name", default=name): selector.TextSelector(),
                vol.Optional("short", default=short): selector.TextSelector(),
                vol.Optional("lux_sensor"): _entity("sensor"),
                vol.Required("sun_preset", default=PRESET_MEDIUM): self._choice(SUN_PRESET_OPTIONS, "sun_preset"),
            }
        )
        return self.async_show_form(step_id="compact_sector", data_schema=schema)

    async def async_step_compact_sun_custom(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._pending_sector is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            if float(user_input["sun_on_lux"]) <= float(user_input["sun_off_lux"]):
                errors["base"] = "lux_hysteresis"
            else:
                self._pending_sector.update(user_input)
                self._append_pending_sector()
                return await self.async_step_compact_layer()
        defaults = {**SUN_PRESETS[PRESET_MEDIUM], **self._pending_sector}
        schema = vol.Schema(
            {
                vol.Required("sun_on_lux"): _number(0, 200000, 500, "lx"),
                vol.Required("sun_off_lux"): _number(0, 200000, 500, "lx"),
                vol.Required("sun_on_delay"): _number(0, 60, 0.5, "min"),
                vol.Required("sun_off_delay"): _number(0, 120, 0.5, "min"),
            }
        )
        return self.async_show_form(
            step_id="compact_sun_custom",
            data_schema=self.add_suggested_values_to_schema(schema, defaults),
            errors=errors,
        )

    async def async_step_compact_layer(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            entities = list(user_input.get("cover_entities", []))
            duplicates = sorted(set(entities) & self.all_cover_entities())
            if duplicates:
                errors["base"] = "cover_already_assigned"
            elif not entities:
                errors["base"] = "select_at_least_one"
            else:
                profile = user_input.get("profile", DEVICE_VENETIAN)
                name = str(user_input.get("name") or ("Behanggruppe" if self._is_german() else "Cover group"))
                self._pending_layer = self._new_layer(name, profile)
                if profile in {DEVICE_VENETIAN, DEVICE_VERTICAL}:
                    preset = user_input.get("tilt_preset", TILT_PRESET_BALANCED)
                    self._pending_layer["tilt_preset"] = preset
                    if preset == TILT_PRESET_CUSTOM:
                        self._pending_cover_entities = entities
                        return await self.async_step_compact_tilt_custom()
                    self._pending_layer["tilt_curve"] = deepcopy(TILT_CURVE_PRESETS[preset])
                self._append_pending_layer()
                self._pending_cover_entities = entities
                self._pending_cover_index = 0
                return await self.async_step_compact_cover_details()
        schema = vol.Schema(
            {
                vol.Required("name", default="Behanggruppe" if self._is_german() else "Cover group"): selector.TextSelector(),
                vol.Required("profile", default=DEVICE_VENETIAN): self._choice(DEVICE_TYPES, "device_type"),
                vol.Required("tilt_preset", default=TILT_PRESET_BALANCED): self._choice(TILT_PRESET_OPTIONS, "tilt_preset"),
                vol.Required("cover_entities"): _entity("cover", multiple=True),
            }
        )
        return self.async_show_form(step_id="compact_layer", data_schema=schema, errors=errors)

    async def async_step_compact_tilt_custom(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._pending_layer is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            elevations = [float(user_input[f"elevation_{i}"]) for i in range(1, 5)]
            if elevations != sorted(elevations) or len(set(elevations)) != 4:
                errors["base"] = "elevation_order"
            else:
                self._pending_layer["tilt_curve"] = [
                    {"elevation": user_input[f"elevation_{i}"], "tilt": user_input[f"tilt_{i}"]}
                    for i in range(1, 5)
                ]
                self._append_pending_layer()
                self._pending_cover_index = 0
                return await self.async_step_compact_cover_details()
        points = deepcopy(TILT_CURVE_PRESETS[TILT_PRESET_BALANCED])
        fields: dict[Any, Any] = {}
        for index, point in enumerate(points, start=1):
            fields[vol.Required(f"elevation_{index}", default=point["elevation"])] = _number(-10, 90, 1, "°")
            fields[vol.Required(f"tilt_{index}", default=point["tilt"])] = _number(0, 100, 1, "%")
        return self.async_show_form(step_id="compact_tilt_custom", data_schema=vol.Schema(fields), errors=errors)

    async def async_step_compact_cover_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entities = list(getattr(self, "_pending_cover_entities", []))
        index = int(getattr(self, "_pending_cover_index", 0))
        if not entities or index >= len(entities):
            self._pending_cover_entities = []
            self._pending_cover_index = 0
            return await self.async_step_after_room()
        entity_id = entities[index]
        fallback = f"{'Behang' if self._is_german() else 'Cover'} {index + 1}"
        suggested_name = self._friendly_name(entity_id, fallback)
        suggested_short = self._cover_short(index)
        if user_input is not None:
            cover = _default_cover(
                entity_id,
                str(user_input.get("name") or suggested_name).strip(),
                str(user_input.get("short") or suggested_short).strip().upper(),
            )
            cover.update({
                "lock": user_input.get("lock", ""),
                "window": user_input.get("window", ""),
                "window_safe_state": user_input.get("window_safe_state", "on"),
                "window_policy": user_input.get("window_policy", "block_closing"),
                CONF_WINDOW_RETURNS_TO_AUTOMATION: user_input.get(
                    CONF_WINDOW_RETURNS_TO_AUTOMATION,
                    DEFAULT_WINDOW_RETURNS_TO_AUTOMATION,
                ),
            })
            self.layer().setdefault("covers", []).append(cover)
            self._pending_cover_index = index + 1
            return await self.async_step_compact_cover_details()
        schema = vol.Schema(
            {
                vol.Required("name"): selector.TextSelector(),
                vol.Required("short"): selector.TextSelector(),
                vol.Optional("lock"): _entity(["switch", "input_boolean"]),
                vol.Optional("window"): _entity("binary_sensor"),
                vol.Required("window_safe_state", default="on"): self._choice(["on", "off"], "safe_state"),
                vol.Required("window_policy", default="block_closing"): self._choice(WINDOW_POLICIES, "window_policy"),
                vol.Required(
                    CONF_WINDOW_RETURNS_TO_AUTOMATION,
                    default=DEFAULT_WINDOW_RETURNS_TO_AUTOMATION,
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="compact_cover_details",
            data_schema=self.add_suggested_values_to_schema(schema, {"name": suggested_name, "short": suggested_short}),
            description_placeholders={"entity_name": suggested_name, "current": str(index + 1), "count": str(len(entities))},
        )

    async def async_step_finish(self, user_input=None) -> ConfigFlowResult:
        if not self._working.get(CONF_ROOMS):
            return await self.async_step_compact_room()
        return self.async_create_entry(
            title=self._working[CONF_HOUSE_NAME], data=self._working
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SmartShadingOptionsFlow()


class SmartShadingOptionsFlow(_SmartShadingWizardMixin, OptionsFlowWithReload):
    """Manage an existing house. Saving reloads the entry once."""

    def __getattr__(self, name: str):
        """Resolve one dynamic options route to its fixed customer step."""
        prefix = "async_step_manage_"
        if name.startswith(prefix):
            token = name[len(prefix):]

            async def _managed_step(user_input=None):
                route = getattr(self, "_option_routes", {}).get(token)
                if route is None:
                    return self.async_abort(reason="no_rooms")
                self._room_id = route.get("room_id")
                self._sector_id = route.get("sector_id")
                self._layer_id = route.get("layer_id")
                self._cover_index = route.get("cover_index")
                handler = getattr(self, f"async_step_{route['action']}")
                return await handler(user_input)

            return _managed_step
        raise AttributeError(name)

    def _add_option_route(
        self,
        menu: dict[str, str],
        label: str,
        action: str,
        **context: Any,
    ) -> None:
        token = str(len(self._option_routes))
        self._option_routes[token] = {"action": action, **context}
        menu[f"manage_{token}"] = label

    def _option_placeholders(self) -> dict[str, str]:
        """Return customer names for the currently selected options object."""
        german = self._is_german()
        room = self.room()
        placeholders = {
            "room_name": str(room.get("name") or ("Raum" if german else "Room"))
        }
        if self._sector_id is None:
            return placeholders
        sector = self.sector()
        placeholders["sector_name"] = str(
            sector.get("name") or ("Sonnensektor" if german else "Sun sector")
        )
        if self._layer_id is None:
            return placeholders
        layer = self.layer()
        placeholders["group_name"] = str(
            layer.get("name") or ("Behanggruppe" if german else "Cover group")
        )
        if self._cover_index is None:
            return placeholders
        covers = layer.get("covers", [])
        if 0 <= self._cover_index < len(covers):
            cover = covers[self._cover_index]
            placeholders["cover_name"] = str(
                cover.get("name")
                or self._friendly_name(
                    cover.get("entity", ""), "Behang" if german else "Cover"
                )
            )
        return placeholders

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if not hasattr(self, "_working") or not self._working:
            self._working = deepcopy(
                {**self.config_entry.data, **self.config_entry.options}
            )
            self._working.setdefault(CONF_ROOMS, [])
            self._working.setdefault(CONF_ADVANCED_MODE, False)
            self._working.setdefault(
                CONF_DIAGNOSTIC_LEVEL,
                "events" if self._working.get(CONF_TEST_MODE, False) else "off",
            )
            self._room_id = None
            self._sector_id = None
            self._layer_id = None
            self._cover_index = None
            self._pending_sector = None
            self._pending_layer = None
            self._pending_cover_entities = []
            self._pending_cover_index = 0
        labels = self._menu(["add_room", "global_settings", "finish"])
        menu_options: dict[str, str] = {"add_room": labels["add_room"]}
        self._option_routes: dict[str, dict[str, Any]] = {}
        for route in build_main_room_routes(
            self.rooms, german=self._is_german()
        ):
            self._add_option_route(
                menu_options,
                str(route["label"]),
                str(route["action"]),
                room_id=route["room_id"],
            )
        menu_options["global_settings"] = labels["global_settings"]
        menu_options["finish"] = labels["finish"]
        return self.async_show_menu(step_id="init", menu_options=menu_options)

    async def async_step_room_hub(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show every action for the selected room in one scoped submenu."""
        room = self.room()
        self._sector_id = None
        self._layer_id = None
        self._cover_index = None
        self._option_routes = {}
        menu_options: dict[str, str] = {}
        for route in build_room_routes(room, german=self._is_german()):
            context = {
                key: route[key]
                for key in ("room_id", "sector_id", "layer_id", "cover_index")
                if key in route
            }
            self._add_option_route(
                menu_options,
                str(route["label"]),
                str(route["action"]),
                **context,
            )
        menu_options["back_to_overview"] = self._menu(
            ["back_to_overview"]
        )["back_to_overview"]
        return self.async_show_menu(
            step_id="room_hub",
            menu_options=menu_options,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_manage_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit one room on a single, sectioned form."""
        room = self.room()
        errors: dict[str, str] = {}
        if user_input is not None:
            values = _flatten_sections(user_input)
            if values.get("delete_room", False):
                if len(self.rooms) <= 1:
                    errors["base"] = "cannot_delete_last_room"
                else:
                    self._working[CONF_ROOMS] = [
                        item for item in self.rooms if item["id"] != room["id"]
                    ]
                    return await self.async_step_init()

            if self.advanced_mode:
                night_enabled = bool(
                    values.get("night_enabled", room.get("night_enabled", False))
                )
                night_source = str(
                    values.get("night_source", room.get("night_source", "entity"))
                )
                if (
                    night_enabled
                    and night_source == "entity"
                    and not values.get("night_entity")
                ):
                    errors["base"] = "night_entity_required"
                elif (
                    not night_enabled
                    and values.get("default_pause_mode") == PAUSE_NEXT_NIGHT_END
                ):
                    errors["base"] = "pause_requires_night"
                heat = float(values.get("heat_temperature", room.get("heat_temperature", 27.0)))
                release = float(values.get("heat_release_temperature", room.get("heat_release_temperature", 26.0)))
                reopen = float(values.get("reopen_temperature", room.get("reopen_temperature", 22.0)))
                if self._venetian_only(room):
                    normal = float(values.get("normal_shading_temperature", room.get("normal_shading_temperature", 23.5)))
                    if not reopen < normal < heat:
                        errors["base"] = "normal_temperature_order"
                    elif not reopen < release < heat:
                        errors["base"] = "release_order"
                else:
                    comfort = float(values.get("comfort_temperature", room.get("comfort_temperature", 23.5)))
                    solar = float(values.get("solar_temperature", room.get("solar_temperature", 25.5)))
                    if not comfort < solar < heat:
                        errors["base"] = "temperature_order"
                    elif not reopen < release < heat:
                        errors["base"] = "release_order"
                if values.get("schedule_profile") == SCHEDULE_CUSTOM and (
                    not values.get("active_months")
                    or not values.get("active_weekdays")
                ):
                    errors["base"] = "select_at_least_one"

            if not errors:
                room["name"] = str(values.get("name") or room["name"])
                if not self.advanced_mode:
                    room[CONF_EXTERNAL_MOVEMENT_DETECTION] = False
                    room[CONF_EASY_TEMPERATURE_GATE] = bool(
                        values.get(CONF_EASY_TEMPERATURE_GATE, False)
                    )
                    room["outdoor_temperature"] = values.get(
                        "outdoor_temperature", ""
                    )
                    room["outdoor_minimum"] = float(
                        values.get("outdoor_minimum", room.get("outdoor_minimum", 18.0))
                    )
                    return await self.async_step_room_hub()

                optional_lists = {"safety_blockers"}
                optional_entities = {
                    "indoor_temperature", "outdoor_temperature", "night_entity",
                    "irradiance_sensor", "cloud_cover_sensor", "weather_permission",
                    "glare_sensor", "occupancy_sensor",
                }
                for key in optional_entities:
                    room[key] = values.get(key, "")
                for key in optional_lists:
                    room[key] = list(values.get(key, []))
                for key in (
                    "outdoor_minimum", "schedule_profile", "active_months",
                    "active_weekdays", "day_window", "start_time", "end_time",
                    "outside_schedule_behavior", "heat_outside_schedule",
                    "default_pause_mode", "pause_sun_offset_minutes",
                    "pause_duration_hours", "heat_during_pause",
                    CONF_EXTERNAL_MOVEMENT_DETECTION, "night_enabled", "night_source",
                    "night_start_offset_minutes", "night_end_offset_minutes",
                    "night_morning_transition_minutes", "night_evening_transition_minutes",
                    "normal_shading_temperature", "comfort_temperature",
                    "solar_temperature", "heat_temperature",
                    "heat_release_temperature", "reopen_temperature",
                    "irradiance_minimum", "cloud_cover_maximum", "weather_logic",
                    "heat_ignores_weather", "heat_fail_safe", "heat_requires_sun",
                    "comfort_requires_occupancy", "safety_behavior",
                ):
                    if key in values:
                        room[key] = values[key]
                if self._venetian_only(room):
                    room["comfort_temperature"] = room["normal_shading_temperature"]
                    room["solar_temperature"] = room["normal_shading_temperature"]
                profile = room.get("schedule_profile", "year_round")
                if profile == SCHEDULE_SUMMER:
                    room["active_months"] = [5, 6, 7, 8, 9]
                    room["active_weekdays"] = list(range(7))
                elif profile != SCHEDULE_CUSTOM:
                    room["active_months"] = list(range(1, 13))
                    room["active_weekdays"] = list(range(7))
                return await self.async_step_room_hub()

        basics: dict[Any, Any] = {
            vol.Required("name", default=room.get("name", "")): selector.TextSelector(),
        }
        if self.advanced_mode:
            basics.update({
                _optional_marker("indoor_temperature", room.get("indoor_temperature", "")): _temperature_entity(),
                _optional_marker("outdoor_temperature", room.get("outdoor_temperature", "")): _temperature_entity(),
                vol.Required("outdoor_minimum", default=room.get("outdoor_minimum", 18.0)): _number(-20, 40, 0.5, "°C"),
                _optional_marker("safety_blockers", room.get("safety_blockers", [])): _entity("binary_sensor", multiple=True),
            })
        else:
            basics.update({
                vol.Required(CONF_EASY_TEMPERATURE_GATE, default=room.get(CONF_EASY_TEMPERATURE_GATE, False)): selector.BooleanSelector(),
                _optional_marker("outdoor_temperature", room.get("outdoor_temperature", "")): _temperature_entity(),
                vol.Required("outdoor_minimum", default=room.get("outdoor_minimum", 18.0)): _number(-20, 40, 0.5, "°C"),
            })

        sections: dict[Any, Any] = {
            vol.Required("room_basics"): section(vol.Schema(basics), {"collapsed": False}),
        }
        if self.advanced_mode:
            pause_modes = [
                PAUSE_NEXT_SUNRISE,
                PAUSE_NEXT_SUNSET,
                PAUSE_NEXT_NIGHT_END,
                PAUSE_TIMED,
                PAUSE_MANUAL,
            ]
            pause_default = str(
                room.get("default_pause_mode", PAUSE_NEXT_SUNRISE)
            )
            if pause_default not in pause_modes:
                pause_default = PAUSE_MANUAL
            schedule = {
                vol.Required("schedule_profile", default=room.get("schedule_profile", SCHEDULE_YEAR_ROUND)): self._choice(SCHEDULE_OPTIONS, "schedule_profile"),
                vol.Required("active_months", default=[str(value) for value in room.get("active_months", range(1, 13))]): self._choice([str(value) for value in range(1, 13)], "months", multiple=True),
                vol.Required("active_weekdays", default=[str(value) for value in room.get("active_weekdays", range(7))]): self._choice([str(value) for value in range(7)], "weekdays", multiple=True),
                vol.Required("day_window", default=room.get("day_window", "sector_sun")): self._choice(DAY_WINDOW_OPTIONS, "day_window"),
                vol.Required("start_time", default=room.get("start_time", "00:00:00")): selector.TimeSelector(),
                vol.Required("end_time", default=room.get("end_time", "23:59:59")): selector.TimeSelector(),
                vol.Required("outside_schedule_behavior", default=room.get("outside_schedule_behavior", OUTSIDE_OPEN)): self._choice(OUTSIDE_OPTIONS, "outside_schedule_behavior"),
                vol.Required("heat_outside_schedule", default=room.get("heat_outside_schedule", True)): selector.BooleanSelector(),
            }
            pause = {
                vol.Required("default_pause_mode", default=pause_default): self._choice(pause_modes, "pause_mode"),
                vol.Required("pause_sun_offset_minutes", default=room.get("pause_sun_offset_minutes", -60)): _number(-120, 240, 5, "min"),
                vol.Required("pause_duration_hours", default=room.get("pause_duration_hours", 2.0)): _number(0.5, 72, 0.5, "h"),
                vol.Required("heat_during_pause", default=room.get("heat_during_pause", False)): selector.BooleanSelector(),
                vol.Required(CONF_EXTERNAL_MOVEMENT_DETECTION, default=room.get(CONF_EXTERNAL_MOVEMENT_DETECTION, DEFAULT_EXTERNAL_MOVEMENT_DETECTION)): selector.BooleanSelector(),
            }
            night = {
                vol.Required("night_enabled", default=room.get("night_enabled", False)): selector.BooleanSelector(),
                vol.Required("night_source", default=room.get("night_source", "entity")): self._choice(["entity", "sun"], "night_source"),
                _optional_marker("night_entity", room.get("night_entity", "")): _entity(["schedule", "input_boolean", "binary_sensor", "switch"]),
                vol.Required("night_start_offset_minutes", default=room.get("night_start_offset_minutes", 0)): _number(-240, 240, 5, "min"),
                vol.Required("night_end_offset_minutes", default=room.get("night_end_offset_minutes", 0)): _number(-240, 240, 5, "min"),
                vol.Required("night_morning_transition_minutes", default=room.get("night_morning_transition_minutes", 0)): _number(0, 120, 5, "min"),
                vol.Required("night_evening_transition_minutes", default=room.get("night_evening_transition_minutes", 0)): _number(0, 120, 5, "min"),
            }
            temperatures: dict[Any, Any] = {
                vol.Required("heat_temperature", default=room.get("heat_temperature", 27.0)): _number(5, 45, 0.1, "°C"),
                vol.Required("heat_release_temperature", default=room.get("heat_release_temperature", 26.0)): _number(5, 45, 0.1, "°C"),
                vol.Required("reopen_temperature", default=room.get("reopen_temperature", 22.0)): _number(5, 35, 0.1, "°C"),
            }
            if self._venetian_only(room):
                temperatures[vol.Required("normal_shading_temperature", default=room.get("normal_shading_temperature", 23.5))] = _number(5, 40, 0.1, "°C")
            else:
                temperatures[vol.Required("comfort_temperature", default=room.get("comfort_temperature", 23.5))] = _number(5, 40, 0.1, "°C")
                temperatures[vol.Required("solar_temperature", default=room.get("solar_temperature", 25.5))] = _number(5, 40, 0.1, "°C")
            conditions = {
                _optional_marker("irradiance_sensor", room.get("irradiance_sensor", "")): _entity("sensor"),
                vol.Required("irradiance_minimum", default=room.get("irradiance_minimum", 150.0)): _number(0, 2000, 10, "W/m²"),
                _optional_marker("cloud_cover_sensor", room.get("cloud_cover_sensor", "")): _entity("sensor"),
                vol.Required("cloud_cover_maximum", default=room.get("cloud_cover_maximum", 85.0)): _number(0, 100, 1, "%"),
                _optional_marker("weather_permission", room.get("weather_permission", "")): _entity("binary_sensor"),
                _optional_marker("glare_sensor", room.get("glare_sensor", "")): _entity("binary_sensor"),
                _optional_marker("occupancy_sensor", room.get("occupancy_sensor", "")): _entity("binary_sensor"),
                vol.Required("weather_logic", default=room.get("weather_logic", "all")): self._choice(["all", "any"], "weather_logic"),
                vol.Required("heat_ignores_weather", default=room.get("heat_ignores_weather", True)): selector.BooleanSelector(),
                vol.Required("heat_fail_safe", default=room.get("heat_fail_safe", True)): selector.BooleanSelector(),
                vol.Required("heat_requires_sun", default=room.get("heat_requires_sun", True)): selector.BooleanSelector(),
                vol.Required("comfort_requires_occupancy", default=room.get("comfort_requires_occupancy", False)): selector.BooleanSelector(),
                vol.Required("safety_behavior", default=room.get("safety_behavior", "move_safe")): self._choice(["move_safe", "block"], "safety_behavior"),
            }
            sections.update({
                vol.Required("schedule_settings"): section(vol.Schema(schedule), {"collapsed": True}),
                vol.Required("pause_settings"): section(vol.Schema(pause), {"collapsed": True}),
                vol.Required("night_settings"): section(vol.Schema(night), {"collapsed": True}),
                vol.Required("temperature_settings"): section(vol.Schema(temperatures), {"collapsed": True}),
                vol.Required("condition_settings"): section(vol.Schema(conditions), {"collapsed": True}),
            })
        sections[vol.Required("room_maintenance")] = section(
            vol.Schema({vol.Required("delete_room", default=False): selector.BooleanSelector()}),
            {"collapsed": True},
        )
        return self.async_show_form(
            step_id="manage_room",
            data_schema=vol.Schema(sections),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_manage_sector(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit one sun sector without navigating through submenus."""
        sector = self.sector()
        errors: dict[str, str] = {}
        if user_input is not None:
            values = _flatten_sections(user_input)
            if values.get("delete_sector", False):
                if len(self.room().get("sectors", [])) <= 1:
                    errors["base"] = "cannot_delete_last_sector"
                else:
                    self.room()["sectors"] = [
                        item for item in self.room().get("sectors", [])
                        if item["id"] != sector["id"]
                    ]
                    return await self.async_step_room_hub()
            if (
                not self.advanced_mode
                and values.get("lux_sensor")
                and values.get(CONF_SUN_PRESENCE_ENTITY)
            ):
                errors["base"] = "choose_one_sun_confirmation"
            if (
                values.get("lux_sensor")
                and values.get("sun_preset") == PRESET_CUSTOM
                and float(values.get("sun_on_lux", sector.get("sun_on_lux", 30000)))
                <= float(values.get("sun_off_lux", sector.get("sun_off_lux", 18000)))
            ):
                errors["base"] = "lux_hysteresis"
            if not errors:
                direction = str(values.get("direction", sector.get("direction", "custom")))
                if direction != DIRECTION_CUSTOM:
                    defaults = self._direction_defaults(direction)
                    for key in ("azimuth_start", "azimuth_end", "elevation_min"):
                        sector[key] = defaults[key]
                sector.update({
                    "direction": direction,
                    "name": str(values.get("name") or sector.get("name", "Sun sector")),
                    "short": str(values.get("short") or sector.get("short", "S")).upper(),
                    "lux_sensor": values.get("lux_sensor", ""),
                    CONF_SUN_PRESENCE_ENTITY: (
                        values.get(CONF_SUN_PRESENCE_ENTITY, "")
                        if not self.advanced_mode
                        else ""
                    ),
                    "sun_preset": values.get("sun_preset", PRESET_MEDIUM),
                })
                if self.advanced_mode and direction == DIRECTION_CUSTOM:
                    for key in ("azimuth_start", "azimuth_end", "elevation_min"):
                        if key in values:
                            sector[key] = values[key]
                preset = str(sector.get("sun_preset", PRESET_MEDIUM))
                if preset in SUN_PRESETS:
                    sector.update(SUN_PRESETS[preset])
                elif preset == PRESET_CUSTOM and sector.get("lux_sensor"):
                    for key in ("sun_on_lux", "sun_off_lux", "sun_on_delay", "sun_off_delay"):
                        if key in values:
                            sector[key] = values[key]
                return await self.async_step_room_hub()

        identity: dict[Any, Any] = {
            vol.Required("name", default=sector.get("name", "")): selector.TextSelector(),
            vol.Required("short", default=sector.get("short", "")): selector.TextSelector(),
            vol.Required("direction", default=sector.get("direction", "custom")): self._choice(
                DIRECTION_OPTIONS
                if self.advanced_mode or sector.get("direction") == DIRECTION_CUSTOM
                else [item for item in DIRECTION_OPTIONS if item != DIRECTION_CUSTOM],
                "direction_preset",
            ),
        }
        if self.advanced_mode:
            identity.update({
                vol.Required("azimuth_start", default=sector.get("azimuth_start", 0)): _number(0, 359, 1, "°"),
                vol.Required("azimuth_end", default=sector.get("azimuth_end", 359)): _number(0, 359, 1, "°"),
                vol.Required("elevation_min", default=sector.get("elevation_min", 0)): _number(-10, 90, 1, "°"),
            })
        confirmation: dict[Any, Any] = {
            _optional_marker("lux_sensor", sector.get("lux_sensor", "")): _entity("sensor"),
            vol.Required("sun_preset", default=sector.get("sun_preset", PRESET_MEDIUM)): self._choice(
                SUN_PRESET_OPTIONS
                if self.advanced_mode or sector.get("sun_preset") == PRESET_CUSTOM
                else ["low", "medium", "high"],
                "sun_preset",
            ),
        }
        if self.advanced_mode:
            confirmation.update({
                vol.Required("sun_on_lux", default=sector.get("sun_on_lux", SUN_PRESETS[PRESET_MEDIUM]["sun_on_lux"])): _number(0, 200000, 500, "lx"),
                vol.Required("sun_off_lux", default=sector.get("sun_off_lux", SUN_PRESETS[PRESET_MEDIUM]["sun_off_lux"])): _number(0, 200000, 500, "lx"),
                vol.Required("sun_on_delay", default=sector.get("sun_on_delay", SUN_PRESETS[PRESET_MEDIUM]["sun_on_delay"])): _number(0, 60, 0.5, "min"),
                vol.Required("sun_off_delay", default=sector.get("sun_off_delay", SUN_PRESETS[PRESET_MEDIUM]["sun_off_delay"])): _number(0, 120, 0.5, "min"),
            })
        else:
            confirmation[_optional_marker(
                CONF_SUN_PRESENCE_ENTITY,
                sector.get(CONF_SUN_PRESENCE_ENTITY, ""),
            )] = _entity(["binary_sensor", "input_boolean", "switch"])
        schema = vol.Schema({
            vol.Required("sector_identity"): section(vol.Schema(identity), {"collapsed": False}),
            vol.Required("sun_confirmation"): section(vol.Schema(confirmation), {"collapsed": True}),
            vol.Required("sector_maintenance"): section(vol.Schema({vol.Required("delete_sector", default=False): selector.BooleanSelector()}), {"collapsed": True}),
        })
        return self.async_show_form(
            step_id="manage_sector",
            data_schema=schema,
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_add_sector_flat(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a usable sector, group and covers in one direct form."""
        errors: dict[str, str] = {}
        if user_input is not None:
            values = _flatten_sections(user_input)
            entities = list(values.get("cover_entities", []))
            duplicates = sorted(set(entities) & self.all_cover_entities())
            if duplicates:
                errors["base"] = "cover_already_assigned"
            elif not entities:
                errors["base"] = "select_at_least_one"
            elif (
                not self.advanced_mode
                and values.get("lux_sensor")
                and values.get(CONF_SUN_PRESENCE_ENTITY)
            ):
                errors["base"] = "choose_one_sun_confirmation"
            else:
                direction = str(values.get("direction", "south"))
                sector = self._direction_defaults(direction)
                sector.update({
                    "id": _new_id(sector["name"]),
                    "direction": direction,
                    "lux_sensor": values.get("lux_sensor", ""),
                    CONF_SUN_PRESENCE_ENTITY: (
                        values.get(CONF_SUN_PRESENCE_ENTITY, "")
                        if not self.advanced_mode
                        else ""
                    ),
                    "sun_preset": values.get("sun_preset", PRESET_MEDIUM),
                })
                if self.advanced_mode and direction == DIRECTION_CUSTOM:
                    for key in ("azimuth_start", "azimuth_end", "elevation_min"):
                        if key in values:
                            sector[key] = values[key]
                preset = str(sector.get("sun_preset", PRESET_MEDIUM))
                if preset in SUN_PRESETS:
                    sector.update(SUN_PRESETS[preset])
                profile = str(values.get("profile", DEVICE_VENETIAN))
                default_group_name = "Behanggruppe" if self._is_german() else "Cover group"
                layer = self._new_layer(
                    str(values.get("group_name") or default_group_name), profile
                )
                if profile in {DEVICE_VENETIAN, DEVICE_VERTICAL}:
                    tilt_preset = str(values.get("tilt_preset", TILT_PRESET_BALANCED))
                    layer["tilt_preset"] = tilt_preset
                    layer["tilt_curve"] = deepcopy(TILT_CURVE_PRESETS.get(tilt_preset, TILT_CURVE_PRESETS[TILT_PRESET_BALANCED]))
                layer["covers"] = [
                    _default_cover(
                        entity_id,
                        self._friendly_name(
                            entity_id,
                            f"{'Behang' if self._is_german() else 'Cover'} {index + 1}",
                        ),
                        self._cover_short(index),
                    )
                    for index, entity_id in enumerate(entities)
                ]
                sector["layers"] = [layer]
                self.room().setdefault("sectors", []).append(sector)
                return await self.async_step_room_hub()
        sector_fields: dict[Any, Any] = {
            vol.Required("direction", default="south"): self._choice(
                DIRECTION_OPTIONS
                if self.advanced_mode
                else [item for item in DIRECTION_OPTIONS if item != DIRECTION_CUSTOM],
                "direction_preset",
            ),
            vol.Optional("lux_sensor"): _entity("sensor"),
            vol.Required("sun_preset", default=PRESET_MEDIUM): self._choice(
                ["low", "medium", "high"], "sun_preset"
            ),
        }
        if not self.advanced_mode:
            sector_fields[vol.Optional(CONF_SUN_PRESENCE_ENTITY)] = _entity(
                ["binary_sensor", "input_boolean", "switch"]
            )
        if self.advanced_mode:
            defaults = DIRECTION_PRESETS["south"]
            sector_fields.update({
                vol.Required("azimuth_start", default=defaults["azimuth_start"]): _number(0, 359, 1, "°"),
                vol.Required("azimuth_end", default=defaults["azimuth_end"]): _number(0, 359, 1, "°"),
                vol.Required("elevation_min", default=defaults["elevation_min"]): _number(-10, 90, 1, "°"),
            })
        group_fields: dict[Any, Any] = {
            vol.Required(
                "group_name",
                default="Behanggruppe" if self._is_german() else "Cover group",
            ): selector.TextSelector(),
            vol.Required("profile", default=DEVICE_VENETIAN): self._choice(DEVICE_TYPES, "device_type"),
            vol.Required("cover_entities"): _entity("cover", multiple=True),
        }
        return self.async_show_form(
            step_id="add_sector_flat",
            data_schema=vol.Schema({
                vol.Required("sector_identity"): section(vol.Schema(sector_fields), {"collapsed": False}),
                vol.Required("cover_group"): section(vol.Schema(group_fields), {"collapsed": False}),
            }),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_manage_layer(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit one cover group on one form."""
        layer = self.layer()
        errors: dict[str, str] = {}
        if user_input is not None:
            values = _flatten_sections(user_input)
            if values.get("delete_layer", False):
                if len(self.sector().get("layers", [])) <= 1:
                    errors["base"] = "cannot_delete_last_layer"
                else:
                    self.sector()["layers"] = [
                        item for item in self.sector().get("layers", [])
                        if item["id"] != layer["id"]
                    ]
                    return await self.async_step_room_hub()
            requested_profile = str(
                values.get("profile", layer.get("profile", DEVICE_VENETIAN))
            )
            if (
                self.advanced_mode
                and requested_profile in {DEVICE_VENETIAN, DEVICE_VERTICAL}
                and values.get("tilt_preset") == TILT_PRESET_CUSTOM
            ):
                elevations = [
                    float(values.get(f"elevation_{index}", 0))
                    for index in range(1, 5)
                ]
                if any(
                    elevations[index] >= elevations[index + 1]
                    for index in range(3)
                ):
                    errors["base"] = "elevation_order"
            if not errors:
                old_profile = str(layer.get("profile", DEVICE_VENETIAN))
                profile = str(values.get("profile", old_profile))
                profile_changed = profile != old_profile
                if profile_changed:
                    covers = layer.get("covers", [])
                    layer_id = layer["id"]
                    layer.clear()
                    layer.update(deepcopy(PROFILE_DEFAULTS[profile]))
                    layer.update({"id": layer_id, "profile": profile, "covers": covers})
                layer["name"] = str(values.get("name") or layer.get("name", "Cover group"))
                if profile in {DEVICE_VENETIAN, DEVICE_VERTICAL}:
                    preset = str(values.get("tilt_preset", layer.get("tilt_preset", TILT_PRESET_BALANCED)))
                    layer["tilt_preset"] = preset
                    if preset in TILT_CURVE_PRESETS:
                        layer["tilt_curve"] = deepcopy(TILT_CURVE_PRESETS[preset])
                    elif self.advanced_mode and preset == TILT_PRESET_CUSTOM:
                        layer["tilt_curve"] = [
                            {
                                "elevation": float(values[f"elevation_{index}"]),
                                "tilt": float(values[f"tilt_{index}"]),
                            }
                            for index in range(1, 5)
                        ]
                if self.advanced_mode and not profile_changed:
                    for key in (
                        "open_position", "open_tilt", "comfort_position", "comfort_tilt",
                        "solar_position", "solar_tilt", "heat_position", "heat_tilt",
                        "night_position", "night_tilt", "safety_position", "safety_tilt",
                    ):
                        if key in values:
                            layer[key] = values[key]
                return await self.async_step_room_hub()
        identity: dict[Any, Any] = {
            vol.Required("name", default=layer.get("name", "")): selector.TextSelector(),
            vol.Required("profile", default=layer.get("profile", DEVICE_VENETIAN)): self._choice(DEVICE_TYPES, "device_type"),
        }
        if (
            self.advanced_mode
            and layer.get("profile") in {DEVICE_VENETIAN, DEVICE_VERTICAL}
        ):
            identity[vol.Required("tilt_preset", default=layer.get("tilt_preset", TILT_PRESET_BALANCED))] = self._choice(TILT_PRESET_OPTIONS, "tilt_preset")
        sections: dict[Any, Any] = {
            vol.Required("group_identity"): section(vol.Schema(identity), {"collapsed": False}),
        }
        if self.advanced_mode:
            profile = str(layer.get("profile", DEVICE_VENETIAN))
            if profile in {DEVICE_VENETIAN, DEVICE_VERTICAL}:
                curve = list(
                    layer.get("tilt_curve")
                    or TILT_CURVE_PRESETS[TILT_PRESET_BALANCED]
                )
                if len(curve) != 4:
                    curve = deepcopy(TILT_CURVE_PRESETS[TILT_PRESET_BALANCED])
                curve_fields: dict[Any, Any] = {}
                for index, point in enumerate(curve, start=1):
                    curve_fields[vol.Required(
                        f"elevation_{index}", default=point["elevation"]
                    )] = _number(-10, 90, 1, "°")
                    curve_fields[vol.Required(
                        f"tilt_{index}", default=point["tilt"]
                    )] = _number(0, 100, 1, "%")
                sections[vol.Required("slat_curve")] = section(
                    vol.Schema(curve_fields), {"collapsed": True}
                )
            target_keys = {
                DEVICE_VENETIAN: ("open_position", "open_tilt", "heat_position", "heat_tilt", "night_position", "night_tilt", "safety_position", "safety_tilt"),
                DEVICE_VERTICAL: ("open_position", "open_tilt", "comfort_tilt", "solar_tilt", "heat_tilt", "night_position", "night_tilt", "safety_position", "safety_tilt"),
            }.get(profile, ("open_position", "comfort_position", "solar_position", "heat_position", "night_position", "safety_position"))
            targets = {
                vol.Required(key, default=layer.get(key, PROFILE_DEFAULTS[profile].get(key, 0.0))): _number(0, 100, 1, "%")
                for key in target_keys
            }
            sections[vol.Required("target_positions")] = section(vol.Schema(targets), {"collapsed": True})
        sections[vol.Required("group_maintenance")] = section(vol.Schema({vol.Required("delete_layer", default=False): selector.BooleanSelector()}), {"collapsed": True})
        return self.async_show_form(
            step_id="manage_layer",
            data_schema=vol.Schema(sections),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_add_layer_flat(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            values = _flatten_sections(user_input)
            entities = list(values.get("cover_entities", []))
            duplicates = sorted(set(entities) & self.all_cover_entities())
            if duplicates:
                errors["base"] = "cover_already_assigned"
            elif not entities:
                errors["base"] = "select_at_least_one"
            else:
                profile = str(values.get("profile", DEVICE_VENETIAN))
                default_name = "Behanggruppe" if self._is_german() else "Cover group"
                layer = self._new_layer(
                    str(values.get("name") or default_name), profile
                )
                if profile in {DEVICE_VENETIAN, DEVICE_VERTICAL}:
                    preset = str(values.get("tilt_preset", TILT_PRESET_BALANCED))
                    layer["tilt_preset"] = preset
                    layer["tilt_curve"] = deepcopy(TILT_CURVE_PRESETS.get(preset, TILT_CURVE_PRESETS[TILT_PRESET_BALANCED]))
                layer["covers"] = [
                    _default_cover(
                        entity_id,
                        self._friendly_name(
                            entity_id,
                            f"{'Behang' if self._is_german() else 'Cover'} {index + 1}",
                        ),
                        self._cover_short(index),
                    )
                    for index, entity_id in enumerate(entities)
                ]
                self.sector().setdefault("layers", []).append(layer)
                return await self.async_step_room_hub()
        fields: dict[Any, Any] = {
            vol.Required(
                "name", default="Behanggruppe" if self._is_german() else "Cover group"
            ): selector.TextSelector(),
            vol.Required("profile", default=DEVICE_VENETIAN): self._choice(DEVICE_TYPES, "device_type"),
            vol.Required("cover_entities"): _entity("cover", multiple=True),
        }
        return self.async_show_form(
            step_id="add_layer_flat",
            data_schema=vol.Schema(fields),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_manage_cover(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit one cover with Easy/Advanced-specific fields."""
        covers = self.layer().get("covers", [])
        cover = covers[self._cover_index]
        errors: dict[str, str] = {}
        if user_input is not None:
            values = _flatten_sections(user_input)
            if values.get("remove_cover", False):
                if len(covers) <= 1:
                    errors["base"] = "cannot_delete_last_cover"
                else:
                    self.layer()["covers"] = [
                        item for index, item in enumerate(covers)
                        if index != self._cover_index
                    ]
                    return await self.async_step_room_hub()
            if not errors:
                cover["name"] = str(values.get("name") or cover.get("name", "Cover"))
                cover["short"] = str(values.get("short") or cover.get("short", ""))
                if self.advanced_mode:
                    cover["lock"] = values.get("lock", "")
                    cover["window"] = values.get("window", "")
                    for key in (
                        "window_safe_state", "window_policy",
                        CONF_WINDOW_RETURNS_TO_AUTOMATION, "max_open_position",
                        "invert_position", "invert_tilt",
                    ):
                        if key in values:
                            cover[key] = values[key]
                return await self.async_step_room_hub()
        identity: dict[Any, Any] = {
            vol.Required("name", default=cover.get("name", "")): selector.TextSelector(),
            vol.Required("short", default=cover.get("short", "")): selector.TextSelector(),
        }
        sections: dict[Any, Any] = {
            vol.Required("cover_identity"): section(vol.Schema(identity), {"collapsed": False}),
        }
        if self.advanced_mode:
            automation = {
                _optional_marker("lock", cover.get("lock", "")): _entity(["switch", "input_boolean"]),
                _optional_marker("window", cover.get("window", "")): _entity("binary_sensor"),
                vol.Required("window_safe_state", default=cover.get("window_safe_state", "on")): self._choice(["on", "off"], "safe_state"),
                vol.Required("window_policy", default=cover.get("window_policy", "block_closing")): self._choice(WINDOW_POLICIES, "window_policy"),
                vol.Required(CONF_WINDOW_RETURNS_TO_AUTOMATION, default=cover.get(CONF_WINDOW_RETURNS_TO_AUTOMATION, DEFAULT_WINDOW_RETURNS_TO_AUTOMATION)): selector.BooleanSelector(),
                vol.Required("max_open_position", default=cover.get("max_open_position", 100)): _number(0, 100, 1, "%"),
                vol.Required("invert_position", default=cover.get("invert_position", False)): selector.BooleanSelector(),
                vol.Required("invert_tilt", default=cover.get("invert_tilt", False)): selector.BooleanSelector(),
            }
            sections[vol.Required("cover_automation")] = section(vol.Schema(automation), {"collapsed": True})
        sections[vol.Required("cover_maintenance")] = section(vol.Schema({vol.Required("remove_cover", default=False): selector.BooleanSelector()}), {"collapsed": True})
        return self.async_show_form(
            step_id="manage_cover",
            data_schema=vol.Schema(sections),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_add_covers_flat(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            entities = list(user_input.get("cover_entities", []))
            duplicates = sorted(set(entities) & self.all_cover_entities())
            if duplicates:
                errors["base"] = "cover_already_assigned"
            elif not entities:
                errors["base"] = "select_at_least_one"
            else:
                covers = self.layer().setdefault("covers", [])
                start = len(covers)
                covers.extend(
                    _default_cover(
                        entity_id,
                        self._friendly_name(
                            entity_id,
                            f"{'Behang' if self._is_german() else 'Cover'} {start + index + 1}",
                        ),
                        self._cover_short(start + index),
                    )
                    for index, entity_id in enumerate(entities)
                )
                return await self.async_step_room_hub()
        return self.async_show_form(
            step_id="add_covers_flat",
            data_schema=vol.Schema({vol.Required("cover_entities"): _entity("cover", multiple=True)}),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_add_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a complete room from one options page."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = _flatten_sections(user_input)
            entities = list(user_input.get("cover_entities", []))
            duplicates = sorted(set(entities) & self.all_cover_entities())
            if duplicates:
                errors["base"] = "cover_already_assigned"
            elif not entities:
                errors["base"] = "select_at_least_one"
            elif not self.advanced_mode and user_input.get("lux_sensor") and user_input.get(
                CONF_SUN_PRESENCE_ENTITY
            ):
                errors["base"] = "choose_one_sun_confirmation"
            else:
                direction = str(user_input.get("direction", "south"))
                sector = self._direction_defaults(direction)
                sector["id"] = _new_id(sector["name"])
                sector["direction"] = direction
                sector["lux_sensor"] = user_input.get("lux_sensor", "")
                sector[CONF_SUN_PRESENCE_ENTITY] = (
                    user_input.get(CONF_SUN_PRESENCE_ENTITY, "")
                    if not self.advanced_mode
                    else ""
                )
                sector["sun_preset"] = user_input.get(
                    "sun_preset", PRESET_MEDIUM
                )
                if self.advanced_mode and direction == DIRECTION_CUSTOM:
                    for key in ("azimuth_start", "azimuth_end", "elevation_min"):
                        sector[key] = float(user_input[key])
                profile = str(user_input.get("profile", DEVICE_VENETIAN))
                default_group_name = "Behanggruppe" if self._is_german() else "Cover group"
                layer = self._new_layer(
                    str(user_input.get("group_name") or default_group_name), profile
                )
                layer["covers"] = [
                    _default_cover(
                        entity_id,
                        self._friendly_name(
                            entity_id,
                            f"{'Behang' if self._is_german() else 'Cover'} {index + 1}",
                        ),
                        self._cover_short(index),
                    )
                    for index, entity_id in enumerate(entities)
                ]
                sector["layers"] = [layer]
                room = deepcopy(ROOM_DEFAULTS)
                room.update({
                    "id": _new_id(str(user_input["name"])),
                    "name": str(user_input["name"]),
                    "sectors": [sector],
                    "outdoor_temperature": user_input.get(
                        "outdoor_temperature", ""
                    ),
                    "outdoor_minimum": float(
                        user_input.get("outdoor_minimum", 18.0)
                    ),
                    CONF_EASY_TEMPERATURE_GATE: bool(
                        user_input.get(CONF_EASY_TEMPERATURE_GATE, False)
                    ) if not self.advanced_mode else False,
                    CONF_EXTERNAL_MOVEMENT_DETECTION: bool(
                        user_input.get(
                            CONF_EXTERNAL_MOVEMENT_DETECTION,
                            DEFAULT_EXTERNAL_MOVEMENT_DETECTION,
                        )
                    ) if self.advanced_mode else False,
                })
                if self.advanced_mode:
                    room.update({
                        "indoor_temperature": user_input.get("indoor_temperature", ""),
                        "safety_blockers": list(user_input.get("safety_blockers", [])),
                    })
                self.rooms.append(room)
                return await self.async_step_init()

        room_fields: dict[Any, Any] = {
            vol.Required("name"): selector.TextSelector(),
            vol.Required("direction", default="south"): self._choice(
                DIRECTION_OPTIONS
                if self.advanced_mode
                else [item for item in DIRECTION_OPTIONS if item != DIRECTION_CUSTOM],
                "direction_preset",
            ),
            vol.Required(
                "group_name",
                default="Behanggruppe" if self._is_german() else "Cover group",
            ): selector.TextSelector(),
            vol.Required("profile", default=DEVICE_VENETIAN): self._choice(DEVICE_TYPES, "device_type"),
            vol.Required("cover_entities"): _entity("cover", multiple=True),
        }
        sun_fields: dict[Any, Any] = {
            vol.Optional("lux_sensor"): _entity("sensor"),
            vol.Required("sun_preset", default=PRESET_MEDIUM): self._choice(
                ["low", "medium", "high"], "sun_preset"
            ),
        }
        if not self.advanced_mode:
            sun_fields[vol.Optional(CONF_SUN_PRESENCE_ENTITY)] = _entity(
                ["binary_sensor", "input_boolean", "switch"]
            )
        optional_fields: dict[Any, Any] = {
            vol.Required(
                CONF_EASY_TEMPERATURE_GATE, default=False
            ): selector.BooleanSelector(),
            vol.Optional("outdoor_temperature"): _temperature_entity(),
            vol.Required("outdoor_minimum", default=18.0): _number(
                -20, 40, 0.5, "°C"
            ),
        }
        if self.advanced_mode:
            defaults = DIRECTION_PRESETS["south"]
            sun_fields.update({
                vol.Required(
                    "azimuth_start", default=defaults["azimuth_start"]
                ): _number(0, 359, 1, "°"),
                vol.Required(
                    "azimuth_end", default=defaults["azimuth_end"]
                ): _number(0, 359, 1, "°"),
                vol.Required(
                    "elevation_min", default=defaults["elevation_min"]
                ): _number(-10, 90, 1, "°"),
            })
            advanced_fields: dict[Any, Any] = {
                vol.Optional("indoor_temperature"): _temperature_entity(),
                vol.Optional("outdoor_temperature"): _temperature_entity(),
                vol.Required("outdoor_minimum", default=18.0): _number(
                    -20, 40, 0.5, "°C"
                ),
                vol.Optional("safety_blockers"): _entity("binary_sensor", multiple=True),
                vol.Required(CONF_EXTERNAL_MOVEMENT_DETECTION, default=DEFAULT_EXTERNAL_MOVEMENT_DETECTION): selector.BooleanSelector(),
            }
        form_fields: dict[Any, Any] = {
            vol.Required("room_and_covers"): section(
                vol.Schema(room_fields), {"collapsed": False}
            ),
            vol.Required("sun_control"): section(
                vol.Schema(sun_fields), {"collapsed": False}
            ),
        }
        if self.advanced_mode:
            form_fields[vol.Required("advanced_conditions")] = section(
                vol.Schema(advanced_fields), {"collapsed": True}
            )
        else:
            form_fields[vol.Required("optional_improvements")] = section(
                vol.Schema(optional_fields), {"collapsed": True}
            )
        return self.async_show_form(
            step_id="add_room", data_schema=vol.Schema(form_fields), errors=errors
        )

    async def async_step_finish(self, user_input=None) -> ConfigFlowResult:
        if not self.rooms:
            return self.async_abort(reason="no_rooms")
        return self.async_create_entry(title="", data=self._working)
