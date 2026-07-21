from __future__ import annotations

from copy import deepcopy
import hashlib
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
    CONF_EVALUATION_INTERVAL,
    CONF_EXTERNAL_MOVEMENT_DETECTION,
    CONF_HOUSE_NAME,
    CONF_ROOMS,
    CONF_SUN_PRESENCE_ENTITY,
    CONF_SUN_ENTITY,
    CONF_TEST_MODE,
    CONF_WINDOW_RETURNS_TO_AUTOMATION,
    DAY_WINDOW_ALL_DAY,
    DAY_WINDOW_FIXED,
    DAY_WINDOW_OPTIONS,
    DEFAULT_EVALUATION_INTERVAL,
    DEFAULT_EXTERNAL_MOVEMENT_DETECTION,
    DEFAULT_EVENING_RELEASE_TIME,
    DEFAULT_POSITION_TOLERANCE,
    DEFAULT_SUNSET_OFFSET_MINUTES,
    DEFAULT_TILT_TOLERANCE,
    DEFAULT_WINDOW_RETURNS_TO_AUTOMATION,
    DIAGNOSTIC_OPTIONS,
    DEVICE_BINARY,
    DEVICE_TYPES,
    DEVICE_VERTICAL,
    DEVICE_VENETIAN,
    DIRECTION_CUSTOM,
    DIRECTION_OPTIONS,
    DIRECTION_PRESETS,
    DOMAIN,
    OUTSIDE_OPEN,
    OUTSIDE_OPTIONS,
    OUTDOOR_MINIMUM_MAX_C,
    OUTDOOR_MINIMUM_MIN_C,
    OUTDOOR_MINIMUM_STEP_C,
    PAUSE_NEXT_NIGHT_END,
    PAUSE_NEXT_SUNRISE,
    PAUSE_DURATION_MAX_HOURS,
    PAUSE_DURATION_MIN_HOURS,
    PAUSE_DURATION_STEP_HOURS,
    PRESET_CUSTOM,
    PRESET_MEDIUM,
    PROFILE_DEFAULTS,
    profile_supports_position,
    profile_supports_tilt,
    profile_target_keys,
    profile_uses_exterior_safety,
    IRRADIANCE_MINIMUM_MAX,
    IRRADIANCE_MINIMUM_MIN,
    IRRADIANCE_MINIMUM_STEP,
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


from .flow_contract import (
    SETUP_EASY,
    SETUP_TYPES,
    config_with_runtime_overrides,
    editable_options,
    locked_advanced_mode,
    setup_is_advanced,
    sun_source_for_sector,
    working_config,
)
from .options_navigation import (
    build_cover_routes,
    build_group_routes,
    build_main_room_routes,
    build_room_routes,
    build_sector_routes,
    build_structure_routes,
    pause_modes_for_room,
)


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
        "enforce_max_open_position": False,
    }


SELECT_LABELS_DE: dict[str, dict[str, str]] = {
    "direction_preset": {
        "north": "Nord (N)", "northeast": "Nordost (NO)", "east": "Ost (O)",
        "southeast": "Südost (SO)", "south": "Süd (S)", "southwest": "Südwest (SW)",
        "west": "West (W)", "northwest": "Nordwest (NW)", "custom": "Benutzerdefiniert",
        "keep_current": "Bestehende Ausrichtung beibehalten",
    },
    "sun_preset": {"low": "Weniger empfindlich", "medium": "Ausgewogen", "high": "Empfindlich", "custom": "Benutzerdefiniert", "keep_current": "Bestehende Empfindlichkeit beibehalten"},
    "sun_source": {"geometry": "Nur Sonnenstand", "lux": "Lokaler Lux-Sensor (empfohlen)", "external": "Externer Ein/Aus-Sensor"},
    "tilt_preset": {"glare": "Mehr Blendschutz", "balanced": "Ausgewogen", "daylight": "Mehr Tageslicht", "custom": "Benutzerdefiniert"},
    "device_type": {
        "venetian": "Außenjalousie mit Lamellen", "roller_shutter": "Rollladen",
        "exterior_screen": "Außenscreen / Zip-Screen", "curtain": "Innenvorhang",
        "vertical_blind": "Vertikale Innenjalousie", "awning": "Markise",
        "binary_cover": "Einfacher Auf/Zu-Behang",
    },
    "schedule_profile": {"year_round": "Ganzjährig automatisch", "summer": "Sommersaison (Mai–September)", "custom": "Benutzerdefinierter Zeitplan"},
    "day_window": {"fixed_time": "Feste Uhrzeit", "all_day": "Ganztägig"},
    "outside_schedule_behavior": {"open": "In Ruheposition fahren", "hold": "Position unverändert lassen"},
    "feedback_policy": {"send": "Befehl senden", "skip": "Ohne Rückmeldung nicht senden"},
    "weather_logic": {"all": "Alle Bedingungen müssen passen", "any": "Eine Bedingung genügt"},
    "safety_behavior": {"move_safe": "In sichere Position fahren", "block": "Normale Automatik nur blockieren"},
    "safe_state": {"on": "Ein / ON ist sicher", "off": "Aus / OFF ist sicher"},
    "window_policy": {"block_all": "Alle Automatikfahrten blockieren", "block_closing": "Nur Schließen blockieren", "ignore": "Fensterkontakt ignorieren"},
    "diagnostic_level": {"off": "Aus", "events": "Ereignisse", "full": "Vollständig"},
    "pause_mode": {"next_sunrise": "Bis zum nächsten Morgen", "next_sunset": "Bis zum nächsten Sonnenuntergang", "next_night_end": "Bis zum Ende der nächsten Nacht", "timed": "Für eine feste Dauer", "manual": "Bis manuell fortgesetzt", "auto": "Nicht pausiert"},
    "night_source": {"entity": "Entität / Zeitplan", "sun": "Sonnenuntergang und Sonnenaufgang"},
    "setup_type": {"simple": "Easy", "complete": "Advanced"},
    "months": {str(i): name for i, name in enumerate(("", "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember")) if i},
    "weekdays": {str(i): name for i, name in enumerate(("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"))},
}
SELECT_LABELS_EN: dict[str, dict[str, str]] = {
    "direction_preset": {"north": "North (N)", "northeast": "Northeast (NE)", "east": "East (E)", "southeast": "Southeast (SE)", "south": "South (S)", "southwest": "Southwest (SW)", "west": "West (W)", "northwest": "Northwest (NW)", "custom": "Custom", "keep_current": "Keep existing direction"},
    "sun_preset": {"low": "Less sensitive", "medium": "Balanced", "high": "Sensitive", "custom": "Custom", "keep_current": "Keep existing sensitivity"},
    "sun_source": {"geometry": "Sun position only", "lux": "Local Lux sensor (recommended)", "external": "External on/off sensor"},
    "tilt_preset": {"glare": "More glare protection", "balanced": "Balanced", "daylight": "More daylight", "custom": "Custom"},
    "device_type": {"venetian": "Exterior venetian blind", "roller_shutter": "Roller shutter", "exterior_screen": "Exterior / zip screen", "curtain": "Interior curtain", "vertical_blind": "Vertical blind", "awning": "Awning", "binary_cover": "Simple open/close cover"},
    "schedule_profile": {"year_round": "Automatic all year", "summer": "Summer season (May–September)", "custom": "Custom schedule"},
    "day_window": {"fixed_time": "Fixed time", "all_day": "All day"},
    "outside_schedule_behavior": {"open": "Move to neutral/open position", "hold": "Keep current position"},
    "feedback_policy": {"send": "Send command", "skip": "Do not send without feedback"},
    "weather_logic": {"all": "All conditions must pass", "any": "Any condition may pass"},
    "safety_behavior": {"move_safe": "Move to the safe position", "block": "Only block normal automation"},
    "safe_state": {"on": "On is safe", "off": "Off is safe"},
    "window_policy": {"block_all": "Block every automatic move", "block_closing": "Only block closing", "ignore": "Ignore window contact"},
    "diagnostic_level": {"off": "Off", "events": "Events", "full": "Full"},
    "pause_mode": {"next_sunrise": "Until next morning", "next_sunset": "Until next sunset", "next_night_end": "Until the end of the next Night", "timed": "For a fixed duration", "manual": "Until manually resumed", "auto": "Not paused"},
    "night_source": {"entity": "Entity / schedule", "sun": "Sunset and sunrise"},
    "setup_type": {"simple": "Easy", "complete": "Advanced"},
    "months": {str(i): name for i, name in enumerate(("", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")) if i},
    "weekdays": {str(i): name for i, name in enumerate(("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"))},
}


MENU_LABELS_DE: dict[str, str] = {
    "finish": "Speichern und Smart Shading starten",
    "save_changes": "Änderungen speichern",
    "add_room": "Raum hinzufügen",
    "global_settings": "Hauseinstellungen",
    "diagnostics_settings": "Diagnose und Support",
    "back_to_overview": "Zur Übersicht",
    "back_to_room": "Zurück zum Raum",
    "back_to_structure": "Zurück zur Beschattungsstruktur",
    "back_to_sector": "Zurück zum Sonnensektor",
    "back_to_group": "Zurück zur Behanggruppe",
}
MENU_LABELS_EN: dict[str, str] = {
    "finish": "Save and start Smart Shading",
    "save_changes": "Save changes",
    "add_room": "Add room",
    "global_settings": "House settings",
    "diagnostics_settings": "Diagnostics and support",
    "back_to_overview": "Back to overview",
    "back_to_room": "Back to room",
    "back_to_structure": "Back to shading structure",
    "back_to_sector": "Back to sun sector",
    "back_to_group": "Back to cover group",
}


class _SmartShadingWizardMixin:
    """Customer-first wizard and explicit advanced editing."""

    def __getattr__(self, name: str):
        """Resolve a stable task route for both setup and later editing."""
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
                try:
                    expected_cover = str(route.get("cover_entity") or "")
                    if expected_cover and self._cover_index is not None:
                        covers = self.layer().get("covers", [])
                        if str(covers[self._cover_index].get("entity") or "") != expected_cover:
                            raise IndexError("stale cover route")
                    handler = getattr(self, f"async_step_{route['action']}")
                    return await handler(user_input)
                except (IndexError, KeyError, StopIteration):
                    # An open browser tab may outlive an edited object. Never
                    # redirect its old token to a different room or cover.
                    self._room_id = None
                    self._sector_id = None
                    self._layer_id = None
                    self._cover_index = None
                    return await self.async_step_init()

            return _managed_step
        raise AttributeError(name)

    def _add_option_route(
        self,
        menu: dict[str, str],
        label: str,
        action: str,
        **context: Any,
    ) -> None:
        """Add a route whose token can never be reassigned by another menu."""
        route = {"action": action, **context}
        identity = "\x1f".join(
            str(route.get(key, ""))
            for key in (
                "action",
                "room_id",
                "sector_id",
                "layer_id",
                "cover_index",
                "cover_entity",
                "placement",
            )
        )
        token = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        previous = self._option_routes.get(token)
        if previous is not None and previous != route:
            raise RuntimeError("Task route token collision")
        self._option_routes[token] = route
        menu[f"manage_{token}"] = label

    def _option_placeholders(self) -> dict[str, str]:
        """Return customer names for the currently selected object."""
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


    def _is_german(self) -> bool:
        return (getattr(self.hass.config, "language", "en") or "en").lower().startswith("de")

    def _menu(self, options: list[str]) -> dict[str, str]:
        labels = MENU_LABELS_DE if self._is_german() else MENU_LABELS_EN
        return {option: labels.get(option, option.replace("_", " ").title()) for option in options}

    def _choice(self, options: list[str], key: str, *, multiple: bool = False):
        return _select(options, key, multiple=multiple)

    def _form_schema(
        self,
        schema: vol.Schema,
        user_input: dict[str, Any] | None,
        errors: dict[str, str],
    ) -> vol.Schema:
        """Keep every submitted value visible when a form reports an error."""
        if user_input is None or not errors:
            return schema
        return self.add_suggested_values_to_schema(schema, user_input)

    def _friendly_name(self, entity_id: str, fallback: str) -> str:
        state = self.hass.states.get(entity_id)
        friendly = state.attributes.get("friendly_name") if state else None
        return str(friendly or fallback)

    @property
    def advanced_mode(self) -> bool:
        if hasattr(self, "_fixed_advanced_mode"):
            return bool(self._fixed_advanced_mode)
        return bool(self._working.get(CONF_ADVANCED_MODE, False))

    @property
    def rooms(self) -> list[dict[str, Any]]:
        return self._working.setdefault(CONF_ROOMS, [])

    def room(self) -> dict[str, Any]:
        return next(room for room in self.rooms if room["id"] == self._room_id)

    def sector(self) -> dict[str, Any]:
        pending = getattr(self, "_pending_sector", None)
        if pending is not None and pending.get("id") == self._sector_id:
            return pending
        return next(
            item
            for item in self.room().get("sectors", [])
            if item["id"] == self._sector_id
        )

    def layer(self) -> dict[str, Any]:
        pending = getattr(self, "_pending_layer", None)
        if pending is not None and pending.get("id") == self._layer_id:
            return pending
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

    def _uses_exterior_safety(
        self, room: dict[str, Any] | None = None
    ) -> bool:
        return any(profile_uses_exterior_safety(profile) for profile in self._room_profiles(room))

    @staticmethod
    def _normalize_covers_for_profile(
        covers: list[dict[str, Any]], profile: str
    ) -> None:
        """Remove per-cover settings unsupported by the selected profile."""
        for cover in covers:
            if not profile_supports_tilt(profile):
                cover["invert_tilt"] = False
            if not profile_supports_position(profile):
                cover["max_open_position"] = 100.0

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

    async def async_step_global_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            values = dict(user_input)
            # The setup variant belongs to entry data and is intentionally not
            # editable here.  Discarding a crafted/stale value is defense in
            # depth for beta entries and cached browser forms.
            values.pop(CONF_ADVANCED_MODE, None)
            if not errors:
                self._working.update(values)
                self._working[CONF_ADVANCED_MODE] = self.advanced_mode
                return await self.async_step_init()
        fields: dict[Any, Any] = {
            vol.Required(CONF_SUN_ENTITY): _entity("sun"),
        }
        suggested = dict(self._working)
        return self.async_show_form(
            step_id="global_settings",
            data_schema=self._form_schema(
                self.add_suggested_values_to_schema(
                    vol.Schema(fields), _nonempty_suggestions(suggested)
                ),
                user_input,
                errors,
            ),
            errors=errors,
            description_placeholders={"card_resource": CARD_RESOURCE},
        )

    async def async_step_diagnostics_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Keep support diagnostics separate from customer house behavior."""
        if not self.advanced_mode:
            return await self.async_step_init()
        if user_input is not None:
            self._working[CONF_DIAGNOSTIC_LEVEL] = str(
                user_input.get(CONF_DIAGNOSTIC_LEVEL, DIAGNOSTIC_OFF)
            )
            return await self.async_step_init()
        return self.async_show_form(
            step_id="diagnostics_settings",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DIAGNOSTIC_LEVEL,
                        default=self._working.get(
                            CONF_DIAGNOSTIC_LEVEL, DIAGNOSTIC_OFF
                        ),
                    ): self._choice(DIAGNOSTIC_OPTIONS, "diagnostic_level")
                }
            ),
        )

    async def async_step_back_to_overview(self, user_input=None):
        """Return to the single house overview in both setup phases."""
        return await self.async_step_init()

    async def async_step_room_hub(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show task categories, never the room's internal object tree."""
        room = self.room()
        self._sector_id = None
        self._layer_id = None
        self._cover_index = None
        menu_options: dict[str, str] = {}
        for route in build_room_routes(
            room, german=self._is_german(), full=self.advanced_mode
        ):
            context = {
                key: route[key]
                for key in (
                    "room_id",
                    "sector_id",
                    "layer_id",
                    "cover_index",
                    "cover_entity",
                    "placement",
                )
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
            step_id="room_hub", menu_options=menu_options
        )

    def _room_object_menu(
        self,
        routes: list[dict[str, Any]],
        *,
        step_id: str,
        back_action: str,
        back_label: str,
    ) -> ConfigFlowResult:
        """Render the shared add/edit list for one object category."""
        menu_options: dict[str, str] = {}
        for route in routes:
            context = {
                key: route[key]
                for key in (
                    "room_id",
                    "sector_id",
                    "layer_id",
                    "cover_index",
                    "cover_entity",
                    "placement",
                )
                if key in route
            }
            self._add_option_route(
                menu_options,
                str(route["label"]),
                str(route["action"]),
                **context,
            )
        menu_options[back_action] = self._menu([back_label])[back_label]
        return self.async_show_menu(
            step_id=step_id,
            menu_options=menu_options,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_structure_hub(self, user_input=None) -> ConfigFlowResult:
        """Show complete sector branches instead of parallel object lists."""
        self._sector_id = None
        self._layer_id = None
        self._cover_index = None
        return self._room_object_menu(
            build_structure_routes(self.room(), german=self._is_german()),
            step_id="structure_hub",
            back_action="back_to_room",
            back_label="back_to_room",
        )

    async def async_step_sector_hub(self, user_input=None) -> ConfigFlowResult:
        self._layer_id = None
        self._cover_index = None
        return self._room_object_menu(
            build_sector_routes(
                self.room(), self.sector(), german=self._is_german()
            ),
            step_id="sector_hub",
            back_action="back_to_structure",
            back_label="back_to_structure",
        )

    async def async_step_group_hub(self, user_input=None) -> ConfigFlowResult:
        self._cover_index = None
        return self._room_object_menu(
            build_group_routes(
                self.room(),
                self.sector(),
                self.layer(),
                german=self._is_german(),
            ),
            step_id="group_hub",
            back_action="back_to_sector",
            back_label="back_to_sector",
        )

    async def async_step_cover_hub(self, user_input=None) -> ConfigFlowResult:
        """Keep stale links safe while routing covers through their group."""
        return await self.async_step_group_hub()

    async def async_step_cover_settings_hub(
        self, user_input=None
    ) -> ConfigFlowResult:
        """Separate ordinary cover settings from optional special functions."""
        labels = (
            {
                "details": "Behangeinstellungen",
                "special": "Sonderfunktionen",
                "back": "Zurück zur Behanggruppe",
            }
            if self._is_german()
            else {
                "details": "Cover settings",
                "special": "Special functions",
                "back": "Back to cover group",
            }
        )
        return self.async_show_menu(
            step_id="cover_settings_hub",
            menu_options={
                "manage_cover": labels["details"],
                "manage_cover_special": labels["special"],
                "back_to_group": labels["back"],
            },
        )

    async def async_step_back_to_room(self, user_input=None) -> ConfigFlowResult:
        return await self.async_step_room_hub()

    async def async_step_back_to_structure(
        self, user_input=None
    ) -> ConfigFlowResult:
        return await self.async_step_structure_hub()

    async def async_step_back_to_sector(
        self, user_input=None
    ) -> ConfigFlowResult:
        return await self.async_step_sector_hub()

    async def async_step_back_to_group(
        self, user_input=None
    ) -> ConfigFlowResult:
        return await self.async_step_group_hub()

    async def _go_to_saved_step(
        self, attribute: str, *, fallback: str
    ) -> ConfigFlowResult:
        """Consume one explicit continuation without re-rendering a long form."""
        step = str(getattr(self, attribute, None) or fallback)
        setattr(self, attribute, None)
        return await getattr(self, f"async_step_{step}")()

    async def async_step_configure_outdoor_temperature(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure the temperature threshold on its own focused page."""
        room = self.room()
        if not str(room.get("outdoor_temperature") or "").strip():
            return await self._go_to_saved_step(
                "_after_outdoor_step", fallback="room_hub"
            )
        errors: dict[str, str] = {}
        if user_input is not None:
            room["outdoor_minimum"] = float(
                user_input.get(
                    "outdoor_minimum", room.get("outdoor_minimum", 18.0)
                )
            )
            return await self._go_to_saved_step(
                "_after_outdoor_step", fallback="room_hub"
            )
        return self.async_show_form(
            step_id="configure_outdoor_temperature",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "outdoor_minimum",
                        default=room.get("outdoor_minimum", 18.0),
                    ): _number(
                        OUTDOOR_MINIMUM_MIN_C,
                        OUTDOOR_MINIMUM_MAX_C,
                        OUTDOOR_MINIMUM_STEP_C,
                        "°C",
                    )
                }
            ),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_continue_initial_room(
        self, user_input=None
    ) -> ConfigFlowResult:
        """Continue a new room through a focused sun-source page when needed."""
        if (
            str(self.sector().get("direction", "south")) == DIRECTION_CUSTOM
            and not bool(getattr(self, "_initial_geometry_ready", False))
        ):
            self._initial_geometry_ready = True
            self._after_source_step = "continue_initial_room"
            return await self.async_step_manage_sector_geometry()
        next_step = str(
            getattr(self, "_after_sector_step", None)
            or "compact_cover_details"
        )
        self._after_sector_step = None
        self._initial_geometry_ready = False
        if str(self.sector().get("sun_source", "geometry")) == "geometry":
            return await getattr(self, f"async_step_{next_step}")()
        self._after_source_step = next_step
        return await self.async_step_configure_sector_source()

    async def async_step_choose_sector_for_group(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        sectors = list(self.room().get("sectors", []))
        if not sectors:
            return await self.async_step_add_sector_flat()
        if user_input is not None:
            self._sector_id = str(user_input["sector_id"])
            return await self.async_step_add_layer_flat()
        if len(sectors) == 1:
            self._sector_id = str(sectors[0]["id"])
            return await self.async_step_add_layer_flat()
        return self.async_show_form(
            step_id="choose_sector_for_group",
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
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_choose_group_for_covers(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        groups = [
            (sector, layer)
            for sector in self.room().get("sectors", [])
            for layer in sector.get("layers", [])
        ]
        if not groups:
            return await self.async_step_choose_sector_for_group()
        if user_input is not None:
            sector_id, layer_id = str(user_input["group_id"]).split("|", 1)
            self._sector_id = sector_id
            self._layer_id = layer_id
            return await self.async_step_add_covers_flat()
        if len(groups) == 1:
            self._sector_id = str(groups[0][0]["id"])
            self._layer_id = str(groups[0][1]["id"])
            return await self.async_step_add_covers_flat()
        return self.async_show_form(
            step_id="choose_group_for_covers",
            data_schema=vol.Schema(
                {
                    vol.Required("group_id"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {
                                    "value": f"{sector['id']}|{layer['id']}",
                                    "label": f"{layer['name']} · {sector['name']}",
                                }
                                for sector, layer in groups
                            ],
                            mode="dropdown",
                        )
                    )
                }
            ),
            description_placeholders=self._option_placeholders(),
        )

class SmartShadingConfigFlow(
    _SmartShadingWizardMixin, config_entries.ConfigFlow, domain=DOMAIN
):
    """Initial customer setup. The entry is created after a complete first room."""

    VERSION = 15

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
                advanced = setup_is_advanced(str(user_input["setup_type"]))
                await self.async_set_unique_id(_slug(user_input[CONF_HOUSE_NAME]))
                self._abort_if_unique_id_configured()
                self._fixed_advanced_mode = advanced
                self._working = {
                    CONF_HOUSE_NAME: user_input[CONF_HOUSE_NAME],
                    CONF_SUN_ENTITY: "sun.sun",
                    CONF_DIAGNOSTIC_LEVEL: "off",
                    CONF_ADVANCED_MODE: advanced,
                    CONF_EVALUATION_INTERVAL: DEFAULT_EVALUATION_INTERVAL,
                    CONF_ROOMS: [],
                }
                self._room_id = None
                self._sector_id = None
                self._layer_id = None
                self._cover_index = None
                self._pending_cover_entities = []
                self._pending_cover_index = 0
                self._pending_cover_return_step = None
                self._pending_cover_short_offset = 0
                self._continue_cover_setup = False
                self._after_sector_step = None
                self._after_source_step = None
                self._after_lux_step = None
                self._after_outdoor_step = None
                self._after_layer_profile_step = None
                self._special_return_step = None
                self._initial_special_cover_index = 0
                self._initial_function_layer_index = 0
                self._pending_sector = None
                self._pending_layer = None
                self._initial_setup = True
                return await self.async_step_global_settings()
        current_sun_state = "missing" if sun_state is None else sun_state.state
        return self.async_show_form(
            step_id="user",
            data_schema=self._form_schema(vol.Schema(
                {
                    vol.Required(CONF_HOUSE_NAME): selector.TextSelector(),
                    vol.Required("setup_type", default=SETUP_EASY): self._choice(
                        list(SETUP_TYPES), "setup_type"
                    ),
                }
            ), user_input, errors),
            errors=errors,
            description_placeholders={"sun_state": current_sun_state},
        )

    async def async_step_easy_room_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Run the permanently selected Easy setup route."""
        if self.advanced_mode:
            return await self.async_step_init()
        return await self._async_step_room_setup(user_input)

    async def async_step_advanced_room_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Run the permanently selected full setup route."""
        if not self.advanced_mode:
            return await self.async_step_init()
        return await self._async_step_room_setup(user_input)

    async def _async_step_room_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create only the room shell before the guided structure chain."""
        errors: dict[str, str] = {}
        first_room = not self.rooms
        if user_input is not None:
            values = _flatten_sections(user_input)
            outdoor_temperature = str(
                values.get("outdoor_temperature") or ""
            ).strip()
            room = deepcopy(ROOM_DEFAULTS)
            room.update(
                {
                    "id": _new_id(str(values["name"])),
                    "name": str(values["name"]),
                    "outdoor_temperature": outdoor_temperature,
                    "sectors": [],
                    CONF_EXTERNAL_MOVEMENT_DETECTION: False,
                }
            )
            if self.advanced_mode:
                room["indoor_temperature"] = str(
                    values.get("indoor_temperature") or ""
                ).strip()
            self.rooms.append(room)
            self._room_id = str(room["id"])
            self._sector_id = None
            self._layer_id = None
            self._pending_sector = None
            self._pending_layer = None
            if outdoor_temperature:
                self._after_outdoor_step = "add_sector_flat"
                return await self.async_step_configure_outdoor_temperature()
            return await self.async_step_add_sector_flat()

        room_fields: dict[Any, Any] = {
            vol.Required("name"): selector.TextSelector(),
            vol.Optional("outdoor_temperature"): _temperature_entity(),
        }
        if self.advanced_mode:
            room_fields[vol.Optional("indoor_temperature")] = _temperature_entity()
        return self.async_show_form(
            step_id="room_setup" if first_room else "add_room",
            data_schema=self._form_schema(
                vol.Schema(
                    {
                        vol.Required("room_details"): section(
                            vol.Schema(room_fields), {"collapsed": False}
                        )
                    }
                ),
                user_input,
                errors,
            ),
            errors=errors,
        )

    async def async_step_room_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the first-room form rendered after house settings."""
        return await self._async_step_room_setup(user_input)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show one house overview throughout initial setup."""
        if not self.rooms:
            if self.advanced_mode:
                return await self.async_step_advanced_room_setup()
            return await self.async_step_easy_room_setup()
        if not hasattr(self, "_option_routes"):
            self._option_routes = {}
        labels = self._menu(
            ["add_room", "global_settings", "diagnostics_settings", "finish"]
        )
        menu_options: dict[str, str] = {"add_room": labels["add_room"]}
        for route in build_main_room_routes(self.rooms, german=self._is_german()):
            self._add_option_route(
                menu_options,
                str(route["label"]),
                str(route["action"]),
                room_id=route["room_id"],
            )
        menu_options["global_settings"] = labels["global_settings"]
        if self.advanced_mode:
            menu_options["diagnostics_settings"] = labels[
                "diagnostics_settings"
            ]
        menu_options["finish"] = labels["finish"]
        return self.async_show_menu(step_id="init", menu_options=menu_options)

    async def async_step_after_room(self, user_input=None) -> ConfigFlowResult:
        """Return every completed creation task to the same house overview."""
        self._initial_setup = False
        return await self.async_step_init()

    async def async_step_configure_current_room(self, user_input=None):
        """Open the task-based editor for the selected room."""
        return await self.async_step_room_hub()

    async def async_step_manage_room_details(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_manage_room_details(
            self, user_input
        )

    async def async_step_manage_room_maintenance(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_manage_room_maintenance(
            self, user_input
        )

    async def async_step_manage_automation(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_manage_automation(
            self, user_input
        )

    async def async_step_manage_night(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_manage_night(self, user_input)

    async def async_step_initial_night_targets(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_initial_night_targets(
            self, user_input
        )

    async def async_step_manage_pause(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_manage_pause(self, user_input)

    async def async_step_manage_conditions(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_manage_conditions(
            self, user_input
        )

    async def async_step_initial_safety_targets(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_initial_safety_targets(
            self, user_input
        )

    async def async_step_manage_sector(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_manage_sector(self, user_input)

    async def async_step_manage_sector_source(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_manage_sector_source(
            self, user_input
        )

    async def async_step_configure_sector_source(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_configure_sector_source(
            self, user_input
        )

    async def async_step_configure_lux_profile(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_configure_lux_profile(
            self, user_input
        )

    async def async_step_manage_sector_geometry(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_manage_sector_geometry(
            self, user_input
        )

    async def async_step_add_sector_flat(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_add_sector_flat(self, user_input)

    async def async_step_continue_pending_sector_source(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_continue_pending_sector_source(
            self, user_input
        )

    async def async_step_add_sector_group(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_add_sector_group(
            self, user_input
        )

    async def async_step_add_sector_covers(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_add_sector_covers(
            self, user_input
        )

    async def async_step_commit_pending_sector(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_commit_pending_sector(
            self, user_input
        )

    async def async_step_manage_layer(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_manage_layer(self, user_input)

    async def async_step_manage_layer_profile(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_manage_layer_profile(
            self, user_input
        )

    async def async_step_add_layer_flat(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_add_layer_flat(self, user_input)

    async def async_step_add_group_covers(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_add_group_covers(
            self, user_input
        )

    async def async_step_commit_pending_layer(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_commit_pending_layer(
            self, user_input
        )

    async def async_step_manage_cover(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_manage_cover(self, user_input)

    async def async_step_cover_settings_hub(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_cover_settings_hub(
            self, user_input
        )

    async def async_step_manage_cover_special(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_manage_cover_special(
            self, user_input
        )

    async def async_step_initial_cover_special_functions(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_initial_cover_special_functions(
            self, user_input
        )

    async def async_step_continue_initial_cover_special_functions(
        self, user_input=None
    ):
        return await SmartShadingOptionsFlow.async_step_continue_initial_cover_special_functions(
            self, user_input
        )

    async def async_step_add_covers_flat(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_add_covers_flat(self, user_input)

    async def async_step_add_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Use the same complete room setup for every additional room."""
        self._initial_setup = True
        if self.advanced_mode:
            return await self.async_step_advanced_room_setup(user_input)
        return await self.async_step_easy_room_setup(user_input)

    async def async_step_compact_cover_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entities = list(getattr(self, "_pending_cover_entities", []))
        index = int(getattr(self, "_pending_cover_index", 0))
        if not entities or index >= len(entities):
            self._pending_cover_entities = []
            self._pending_cover_index = 0
            return_step = getattr(self, "_pending_cover_return_step", None)
            self._pending_cover_return_step = None
            self._pending_cover_short_offset = 0
            if return_step:
                return await getattr(self, f"async_step_{return_step}")()
            if getattr(self, "_initial_setup", False) and self.advanced_mode:
                return await self.async_step_manage_automation()
            return await self.async_step_after_room()
        entity_id = entities[index]
        fallback = f"{'Behang' if self._is_german() else 'Cover'} {index + 1}"
        suggested_name = self._friendly_name(entity_id, fallback)
        suggested_short = self._cover_short(
            int(getattr(self, "_pending_cover_short_offset", 0)) + index
        )
        profile = str(self.layer().get("profile", DEVICE_VENETIAN))
        if user_input is not None:
            cover = _default_cover(
                entity_id,
                str(user_input.get("name") or suggested_name).strip(),
                str(user_input.get("short") or suggested_short).strip().upper(),
            )
            if self.advanced_mode:
                cover.update({
                    "lock": user_input.get("lock", ""),
                    "window": user_input.get("window", ""),
                    "window_safe_state": user_input.get("window_safe_state", "on"),
                    "window_policy": user_input.get("window_policy", "block_closing"),
                    CONF_WINDOW_RETURNS_TO_AUTOMATION: user_input.get(
                        CONF_WINDOW_RETURNS_TO_AUTOMATION,
                        DEFAULT_WINDOW_RETURNS_TO_AUTOMATION,
                    ),
                    "invert_position": user_input.get("invert_position", False),
                })
                cover["invert_tilt"] = (
                    user_input.get("invert_tilt", False)
                    if profile_supports_tilt(profile)
                    else False
                )
            self.layer().setdefault("covers", []).append(cover)
            self._pending_cover_index = index + 1
            return await self.async_step_compact_cover_details()
        fields: dict[Any, Any] = {
            vol.Required("name"): selector.TextSelector(),
            vol.Required("short"): selector.TextSelector(),
        }
        if self.advanced_mode:
            fields.update(
                {
                    vol.Optional("lock"): _entity(["switch", "input_boolean"]),
                    vol.Optional("window"): _entity("binary_sensor"),
                    vol.Required("window_safe_state", default="on"): self._choice(["on", "off"], "safe_state"),
                    vol.Required("window_policy", default="block_closing"): self._choice(WINDOW_POLICIES, "window_policy"),
                    vol.Required(
                        CONF_WINDOW_RETURNS_TO_AUTOMATION,
                        default=DEFAULT_WINDOW_RETURNS_TO_AUTOMATION,
                    ): selector.BooleanSelector(),
                    vol.Required("invert_position", default=False): selector.BooleanSelector(),
                }
            )
            if profile_supports_tilt(profile):
                fields[
                    vol.Required("invert_tilt", default=False)
                ] = selector.BooleanSelector()
        schema = vol.Schema(fields)
        return self.async_show_form(
            step_id="compact_cover_details",
            data_schema=self.add_suggested_values_to_schema(schema, {"name": suggested_name, "short": suggested_short}),
            description_placeholders={"entity_name": suggested_name, "current": str(index + 1), "count": str(len(entities))},
        )

    def _review_snapshot(self) -> tuple[dict[str, str], list[str]]:
        """Build the final customer summary and reject incomplete object trees."""
        german = self._is_german()
        sector_count = 0
        group_count = 0
        cover_count = 0
        source_counts = {"geometry": 0, "lux": 0, "external": 0}
        issues: list[str] = []
        assigned: set[str] = set()
        duplicate_entities: set[str] = set()

        for room in self.rooms:
            room_name = str(room.get("name") or ("Raum" if german else "Room"))
            sectors = list(room.get("sectors", []))
            if not sectors:
                issues.append(
                    f"{room_name}: kein Sonnensektor"
                    if german else f"{room_name}: no sun sector"
                )
            if (
                self.advanced_mode
                and room.get("night_enabled")
                and not night_is_configured(room)
            ):
                issues.append(
                    f"{room_name}: Nachtfunktion ohne gültige Quelle"
                    if german
                    else f"{room_name}: night function has no valid source"
                )
            elif (
                room.get("default_pause_mode") == PAUSE_NEXT_NIGHT_END
                and not night_is_configured(room)
            ):
                issues.append(
                    f"{room_name}: Pause bis Nachtende ohne gültige Nachtquelle"
                    if german
                    else f"{room_name}: pause until night end has no valid night source"
                )
            for sector in sectors:
                sector_count += 1
                source = sun_source_for_sector(
                    sector, advanced=self.advanced_mode
                )
                source_counts[source] += 1
                sector_name = str(
                    sector.get("name")
                    or ("Sonnensektor" if german else "Sun sector")
                )
                if source == "lux" and not str(
                    sector.get("lux_sensor", "")
                ).strip():
                    issues.append(
                        f"{room_name} / {sector_name}: Lux-Quelle ohne Sensor"
                        if german
                        else f"{room_name} / {sector_name}: Lux source has no sensor"
                    )
                if source == "external" and not str(
                    sector.get(CONF_SUN_PRESENCE_ENTITY, "")
                ).strip():
                    issues.append(
                        f"{room_name} / {sector_name}: externe Sonnenbestätigung ohne Entität"
                        if german
                        else f"{room_name} / {sector_name}: external sun confirmation has no entity"
                    )
                layers = list(sector.get("layers", []))
                if not layers:
                    issues.append(
                        f"{room_name} / {sector_name}: keine Behanggruppe"
                        if german
                        else f"{room_name} / {sector_name}: no cover group"
                    )
                for layer in layers:
                    group_count += 1
                    covers = list(layer.get("covers", []))
                    if not covers:
                        layer_name = str(
                            layer.get("name")
                            or ("Behanggruppe" if german else "Cover group")
                        )
                        issues.append(
                            f"{room_name} / {layer_name}: kein Behang"
                            if german
                            else f"{room_name} / {layer_name}: no cover"
                        )
                    for cover in covers:
                        cover_count += 1
                        entity_id = str(cover.get("entity", ""))
                        if entity_id in assigned:
                            duplicate_entities.add(entity_id)
                        assigned.add(entity_id)

        if duplicate_entities:
            names = ", ".join(sorted(duplicate_entities))
            issues.append(
                f"Behänge mehrfach zugeordnet: {names}"
                if german else f"Covers assigned more than once: {names}"
            )

        source_labels = {
            "geometry": "Sonnenstand" if german else "sun position",
            "lux": "Lux" if german else "Lux",
            "external": "externe Sonnenbestätigung" if german else "external sun confirmation",
        }
        sources = ", ".join(
            f"{source_labels[key]}: {value}"
            for key, value in source_counts.items()
            if value
        ) or ("Sonnenstand" if german else "sun position")
        if self.advanced_mode:
            night_rooms = sum(bool(room.get("night_enabled")) for room in self.rooms)
            temperature_rooms = sum(
                bool(str(room.get("indoor_temperature") or "").strip())
                for room in self.rooms
            )
            safety_sources = sum(
                len(room.get("safety_blockers", [])) for room in self.rooms
            )
            features = (
                f"Zeitpläne; Temperatursteuerung: {temperature_rooms} Räume; Nachtfunktion: {night_rooms}; "
                f"Gefahrensensoren: {safety_sources}"
                if german
                else f"Schedules; temperature control: {temperature_rooms} rooms; night function: {night_rooms}; "
                f"safety sensors: {safety_sources}"
            )
        else:
            temperature_rooms = sum(
                bool(str(room.get("outdoor_temperature") or "").strip())
                for room in self.rooms
            )
            features = (
                f"Sonnenstandssteuerung; Außentemperaturbedingung: {temperature_rooms} Räume"
                if german
                else f"Sun-position control; outdoor-temperature condition: {temperature_rooms} rooms"
            )
        warnings = (
            "; ".join(issues)
            if issues
            else ("Keine offenen Punkte." if german else "No open items.")
        )
        return (
            {
                "room_count": str(len(self.rooms)),
                "sector_count": str(sector_count),
                "group_count": str(group_count),
                "cover_count": str(cover_count),
                "sun_sources": sources,
                "active_functions": features,
                "review_warnings": warnings,
            },
            issues,
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if not self.rooms:
            if self.advanced_mode:
                return await self.async_step_advanced_room_setup()
            return await self.async_step_easy_room_setup()
        placeholders, issues = self._review_snapshot()
        errors: dict[str, str] = {}
        if issues:
            errors["base"] = "incomplete_configuration"
        elif user_input is not None:
            if not user_input.get("confirm_start", False):
                errors["base"] = "confirm_start_required"
            else:
                return self.async_create_entry(
                    title=self._working[CONF_HOUSE_NAME], data=self._working
                )
        return self.async_show_form(
            step_id="finish",
            data_schema=self._form_schema(vol.Schema(
                {
                    vol.Required(
                        "confirm_start", default=False
                    ): selector.BooleanSelector()
                }
            ), user_input, errors),
            errors=errors,
            description_placeholders=placeholders,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SmartShadingOptionsFlow()


class SmartShadingOptionsFlow(_SmartShadingWizardMixin, OptionsFlowWithReload):
    """Manage an existing house. Saving reloads the entry once."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if not hasattr(self, "_working") or not self._working:
            self._fixed_advanced_mode = locked_advanced_mode(
                self.config_entry.data, self.config_entry.options
            )
            self._working = working_config(
                self.config_entry.data, self.config_entry.options
            )
            engine = getattr(self.config_entry, "runtime_data", None)
            store = getattr(engine, "store", None)
            overrides = (
                getattr(store, "data", {}).get("overrides", {})
                if store is not None
                else {}
            )
            self._working = config_with_runtime_overrides(
                self._working, overrides
            )
            self._working.setdefault(CONF_ROOMS, [])
            self._working[CONF_ADVANCED_MODE] = self._fixed_advanced_mode
            self._working.setdefault(
                CONF_DIAGNOSTIC_LEVEL,
                "events" if self._working.get(CONF_TEST_MODE, False) else "off",
            )
            self._working.pop(CONF_TEST_MODE, None)
            self._room_id = None
            self._sector_id = None
            self._layer_id = None
            self._cover_index = None
            self._pending_cover_entities = []
            self._pending_cover_index = 0
            self._pending_cover_return_step = None
            self._pending_cover_short_offset = 0
            self._continue_cover_setup = False
            self._after_sector_step = None
            self._after_source_step = None
            self._after_lux_step = None
            self._after_outdoor_step = None
            self._after_layer_profile_step = None
            self._special_return_step = None
            self._initial_special_cover_index = 0
            self._initial_function_layer_index = 0
            self._pending_sector = None
            self._pending_layer = None
            self._option_routes = {}
            self._initial_setup = False
        labels = self._menu(
            [
                "add_room",
                "global_settings",
                "diagnostics_settings",
                "save_changes",
            ]
        )
        menu_options: dict[str, str] = {"add_room": labels["add_room"]}
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
        if self.advanced_mode:
            menu_options["diagnostics_settings"] = labels[
                "diagnostics_settings"
            ]
        menu_options["finish"] = labels["save_changes"]
        return self.async_show_menu(step_id="init", menu_options=menu_options)

    async def async_step_manage_room_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit only the room identity and its primary temperature source."""
        room = self.room()
        errors: dict[str, str] = {}
        if user_input is not None:
            values = _flatten_sections(user_input)
            rerender_custom_curve = False
            outdoor_temperature = str(
                values.get("outdoor_temperature") or ""
            ).strip()
            room["name"] = str(values.get("name") or room["name"])
            room["outdoor_temperature"] = outdoor_temperature
            if self.advanced_mode:
                room["indoor_temperature"] = values.get(
                    "indoor_temperature", ""
                )
            if outdoor_temperature:
                self._after_outdoor_step = "room_hub"
                return await self.async_step_configure_outdoor_temperature()
            return await self.async_step_room_hub()
        fields: dict[Any, Any] = {
            vol.Required("name", default=room.get("name", "")): selector.TextSelector(),
            _optional_marker(
                "outdoor_temperature",
                room.get("outdoor_temperature", ""),
            ): _temperature_entity(),
        }
        if self.advanced_mode:
            fields[_optional_marker(
                "indoor_temperature",
                room.get("indoor_temperature", ""),
            )] = _temperature_entity()
        return self.async_show_form(
            step_id="manage_room_details",
            data_schema=self._form_schema(
                vol.Schema(fields), user_input, errors
            ),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_manage_room_maintenance(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None and user_input.get("delete_room", False):
            if len(self.rooms) <= 1:
                errors["base"] = "cannot_delete_last_room"
            else:
                room_id = self.room()["id"]
                self._working[CONF_ROOMS] = [
                    item for item in self.rooms if item["id"] != room_id
                ]
                return await self.async_step_init()
        return self.async_show_form(
            step_id="manage_room_maintenance",
            data_schema=self._form_schema(vol.Schema(
                {vol.Required("delete_room", default=False): selector.BooleanSelector()}
            ), user_input, errors),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_manage_automation(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit schedule, temperature stages and Heat Protection together."""
        if not self.advanced_mode:
            return await self.async_step_room_hub()
        room = self.room()
        errors: dict[str, str] = {}
        submitted_values: dict[str, Any] = {}
        stored_profile = str(
            room.get("schedule_profile", SCHEDULE_YEAR_ROUND)
        )
        current_profile = (
            stored_profile
            if stored_profile in SCHEDULE_OPTIONS
            else SCHEDULE_YEAR_ROUND
        )
        stored_window = str(room.get("day_window", DAY_WINDOW_ALL_DAY))
        current_window = (
            stored_window
            if stored_window in DAY_WINDOW_OPTIONS
            else DAY_WINDOW_ALL_DAY
        )
        has_indoor_temperature = bool(
            str(room.get("indoor_temperature") or "").strip()
        )
        current_schedule_enabled = bool(room.get("schedule_enabled", False))
        if user_input is not None:
            values = _flatten_sections(user_input)
            selected_schedule_enabled = bool(
                values.get("schedule_enabled", False)
            )
            submitted_values = values
            selected_profile = str(
                values.get("schedule_profile", current_profile)
            )
            selected_window = str(values.get("day_window", current_window))
            if (
                selected_profile not in SCHEDULE_OPTIONS
                or selected_window not in DAY_WINDOW_OPTIONS
            ):
                errors["base"] = "option_not_available"
            selector_changed = (
                selected_schedule_enabled != current_schedule_enabled
                or (
                    selected_schedule_enabled
                    and (
                        selected_profile != current_profile
                        or selected_window != current_window
                    )
                )
            )
            if not errors and has_indoor_temperature:
                heat = float(
                    values.get(
                        "heat_temperature",
                        room.get("heat_temperature", 27.0),
                    )
                )
                if self._venetian_only(room):
                    reopen = float(
                        values.get(
                            "reopen_temperature",
                            room.get("reopen_temperature", 22.0),
                        )
                    )
                    normal = float(
                        values.get(
                            "normal_shading_temperature",
                            room.get("normal_shading_temperature", 23.5),
                        )
                    )
                    if not reopen < normal < heat:
                        errors["base"] = "normal_temperature_order"
                else:
                    comfort = float(
                        values.get(
                            "comfort_temperature",
                            room.get("comfort_temperature", 23.5),
                        )
                    )
                    solar = float(
                        values.get(
                            "solar_temperature",
                            room.get("solar_temperature", 25.5),
                        )
                    )
                    if not comfort < solar < heat:
                        errors["base"] = "temperature_order"
            if not errors and selector_changed:
                # Every field visible in this submission is already valid.
                # Keep it before rebuilding the same form with the newly
                # selected schedule fields so a selector change can never
                # silently discard another edit made in the same submit.
                room.update(values)
                room["schedule_enabled"] = selected_schedule_enabled
                room["schedule_profile"] = selected_profile
                room["day_window"] = selected_window
                if selected_profile == SCHEDULE_SUMMER:
                    room["active_months"] = [5, 6, 7, 8, 9]
                    room["active_weekdays"] = list(range(7))
                elif selected_profile == SCHEDULE_YEAR_ROUND:
                    room["active_months"] = list(range(1, 13))
                    room["active_weekdays"] = list(range(7))
                return await self.async_step_manage_automation()
            if not errors and selected_schedule_enabled and selected_profile == SCHEDULE_CUSTOM and (
                not values.get("active_months") or not values.get("active_weekdays")
            ):
                errors["base"] = "select_at_least_one"
            if not errors:
                for key, value in values.items():
                    room[key] = value
                profile = room.get("schedule_profile", SCHEDULE_YEAR_ROUND)
                if profile == SCHEDULE_SUMMER:
                    room["active_months"] = [5, 6, 7, 8, 9]
                    room["active_weekdays"] = list(range(7))
                elif profile != SCHEDULE_CUSTOM:
                    room["active_months"] = list(range(1, 13))
                    room["active_weekdays"] = list(range(7))
                if self._venetian_only(room):
                    room["comfort_temperature"] = room["normal_shading_temperature"]
                    room["solar_temperature"] = room["normal_shading_temperature"]
                if getattr(self, "_initial_setup", False):
                    return await self.async_step_manage_night()
                return await self.async_step_room_hub()

        schedule: dict[Any, Any] = {
            vol.Required(
                "schedule_enabled", default=current_schedule_enabled
            ): selector.BooleanSelector(),
        }
        if current_schedule_enabled:
            schedule.update(
                {
                    vol.Required(
                        "schedule_profile", default=current_profile
                    ): self._choice(SCHEDULE_OPTIONS, "schedule_profile"),
                    vol.Required(
                        "day_window", default=current_window
                    ): self._choice(DAY_WINDOW_OPTIONS, "day_window"),
                }
            )
        if current_schedule_enabled and current_profile == SCHEDULE_CUSTOM:
            schedule.update(
                {
                    vol.Required(
                        "active_months",
                        default=[
                            str(v)
                            for v in room.get("active_months", range(1, 13))
                        ],
                    ): self._choice(
                        [str(v) for v in range(1, 13)],
                        "months",
                        multiple=True,
                    ),
                    vol.Required(
                        "active_weekdays",
                        default=[
                            str(v)
                            for v in room.get("active_weekdays", range(7))
                        ],
                    ): self._choice(
                        [str(v) for v in range(7)],
                        "weekdays",
                        multiple=True,
                    ),
                }
            )
        if current_schedule_enabled and current_window == DAY_WINDOW_FIXED:
            schedule.update(
                {
                    vol.Required(
                        "start_time",
                        default=room.get("start_time", "00:00:00"),
                    ): selector.TimeSelector(),
                    vol.Required(
                        "end_time",
                        default=room.get("end_time", "23:59:59"),
                    ): selector.TimeSelector(),
                }
            )
        if (
            current_schedule_enabled
            and (
                current_profile != SCHEDULE_YEAR_ROUND
                or current_window == DAY_WINDOW_FIXED
            )
        ):
            schedule.update(
                {
                    vol.Required(
                        "outside_schedule_behavior",
                        default=room.get(
                            "outside_schedule_behavior", OUTSIDE_OPEN
                        ),
                    ): self._choice(
                        OUTSIDE_OPTIONS, "outside_schedule_behavior"
                    ),
                }
            )
            if has_indoor_temperature:
                schedule[
                    vol.Required(
                        "heat_outside_schedule",
                        default=room.get("heat_outside_schedule", True),
                    )
                ] = selector.BooleanSelector()
        sections: dict[Any, Any] = {
            vol.Required("schedule_settings"): section(
                self._form_schema(
                    vol.Schema(schedule), submitted_values, errors
                ),
                {"collapsed": False},
            )
        }
        if has_indoor_temperature:
            temperatures: dict[Any, Any] = {
                vol.Required(
                    "heat_temperature",
                    default=room.get("heat_temperature", 27.0),
                ): _number(5, 45, 0.1, "°C"),
                vol.Required(
                    "evening_release_time",
                    default=room.get(
                        "evening_release_time", DEFAULT_EVENING_RELEASE_TIME
                    ),
                ): selector.TimeSelector(),
                vol.Required(
                    "sunset_offset_minutes",
                    default=room.get(
                        "sunset_offset_minutes", DEFAULT_SUNSET_OFFSET_MINUTES
                    ),
                ): _number(-120, 120, 5, "min"),
            }
            if self._venetian_only(room):
                temperatures[
                    vol.Required(
                        "normal_shading_temperature",
                        default=room.get(
                            "normal_shading_temperature", 23.5
                        ),
                    )
                ] = _number(5, 40, 0.1, "°C")
                temperatures[
                    vol.Required(
                        "reopen_temperature",
                        default=room.get("reopen_temperature", 22.0),
                    )
                ] = _number(5, 35, 0.1, "°C")
            else:
                temperatures[
                    vol.Required(
                        "comfort_temperature",
                        default=room.get("comfort_temperature", 23.5),
                    )
                ] = _number(5, 40, 0.1, "°C")
                temperatures[
                    vol.Required(
                        "solar_temperature",
                        default=room.get("solar_temperature", 25.5),
                    )
                ] = _number(5, 40, 0.1, "°C")
            sections[vol.Required("temperature_settings")] = section(
                self._form_schema(
                    vol.Schema(temperatures), submitted_values, errors
                ),
                {"collapsed": False},
            )
        return self.async_show_form(
            step_id="manage_automation",
            data_schema=self._form_schema(
                vol.Schema(sections), user_input, errors
            ),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_manage_night(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure Night before any Night-dependent pause is offered."""
        if not self.advanced_mode:
            return await self.async_step_room_hub()
        room = self.room()
        errors: dict[str, str] = {}
        current_enabled = bool(room.get("night_enabled", False))
        stored_source = str(room.get("night_source", "entity"))
        current_source = stored_source if stored_source in {"entity", "sun"} else "entity"
        if user_input is not None:
            values = _flatten_sections(user_input)
            enabled = bool(values.get("night_enabled", False))
            source = str(values.get("night_source", current_source))
            if source not in {"entity", "sun"}:
                errors["base"] = "option_not_available"
            elif enabled and not current_enabled:
                for key in (
                    "night_start_offset_minutes",
                    "night_end_offset_minutes",
                    "night_morning_transition_minutes",
                    "night_evening_transition_minutes",
                ):
                    if key in values:
                        room[key] = values[key]
                room["night_enabled"] = True
                room["night_source"] = source
                return await self.async_step_manage_night()
            elif enabled and source != current_source:
                for key in (
                    "night_start_offset_minutes",
                    "night_end_offset_minutes",
                    "night_morning_transition_minutes",
                    "night_evening_transition_minutes",
                ):
                    if key in values:
                        room[key] = values[key]
                room["night_source"] = source
                room["night_entity"] = ""
                return await self.async_step_manage_night()
            elif enabled and source == "entity" and not values.get("night_entity"):
                errors["base"] = "night_entity_required"
            if not errors:
                room.update(values)
                if not enabled and room.get("default_pause_mode") == PAUSE_NEXT_NIGHT_END:
                    room["default_pause_mode"] = PAUSE_NEXT_SUNRISE
                if getattr(self, "_initial_setup", False):
                    if enabled:
                        self._initial_function_layer_index = 0
                        return await self.async_step_initial_night_targets()
                    return await self.async_step_manage_pause()
                return await self.async_step_room_hub()
        night: dict[Any, Any] = {
            vol.Required(
                "night_enabled", default=current_enabled
            ): selector.BooleanSelector(),
        }
        if current_enabled:
            night[
                vol.Required("night_source", default=current_source)
            ] = self._choice(["entity", "sun"], "night_source")
            if current_source == "entity":
                night[
                    vol.Required(
                        "night_entity", default=room.get("night_entity", "")
                    )
                ] = _entity(
                    ["schedule", "input_boolean", "binary_sensor", "switch"]
                )
            if current_source == "sun":
                night.update(
                    {
                    vol.Required("night_start_offset_minutes", default=room.get("night_start_offset_minutes", 0)): _number(-240, 240, 5, "min"),
                    vol.Required("night_end_offset_minutes", default=room.get("night_end_offset_minutes", 0)): _number(-240, 240, 5, "min"),
                    }
                )
            night.update(
                {
                    vol.Required("night_morning_transition_minutes", default=room.get("night_morning_transition_minutes", 0)): _number(0, 120, 5, "min"),
                    vol.Required("night_evening_transition_minutes", default=room.get("night_evening_transition_minutes", 0)): _number(0, 120, 5, "min"),
                }
            )
        return self.async_show_form(
            step_id="manage_night",
            data_schema=self._form_schema(
                vol.Schema(night), user_input, errors
            ),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    def _layers_with_function_targets(
        self, prefix: str
    ) -> list[tuple[dict[str, Any], dict[str, Any], tuple[str, ...]]]:
        """Return room layers that expose targets for one optional function."""
        result = []
        for sector in self.room().get("sectors", []):
            for layer in sector.get("layers", []):
                profile = str(layer.get("profile", DEVICE_VENETIAN))
                keys = tuple(
                    key
                    for key in profile_target_keys(
                        profile,
                        indoor_temperature=True,
                        night=True,
                        safety=True,
                    )
                    if key.startswith(prefix)
                )
                if keys:
                    result.append((sector, layer, keys))
        return result

    async def _async_step_initial_function_targets(
        self,
        *,
        prefix: str,
        step_id: str,
        next_step: str,
        user_input: dict[str, Any] | None,
    ) -> ConfigFlowResult:
        layers = self._layers_with_function_targets(prefix)
        index = int(getattr(self, "_initial_function_layer_index", 0))
        if index >= len(layers):
            self._initial_function_layer_index = 0
            return await getattr(self, f"async_step_{next_step}")()
        sector, layer, keys = layers[index]
        self._sector_id = str(sector["id"])
        self._layer_id = str(layer["id"])
        if user_input is not None:
            for key in keys:
                if key in user_input:
                    layer[key] = float(user_input[key])
            self._initial_function_layer_index = index + 1
            return await self._async_step_initial_function_targets(
                prefix=prefix,
                step_id=step_id,
                next_step=next_step,
                user_input=None,
            )
        profile = str(layer.get("profile", DEVICE_VENETIAN))
        fields = {
            vol.Required(
                key,
                default=layer.get(
                    key, PROFILE_DEFAULTS[profile].get(key, 0.0)
                ),
            ): _number(0, 100, 1, "%")
            for key in keys
        }
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(fields),
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_initial_night_targets(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer Night targets only after the customer enables Night."""
        return await self._async_step_initial_function_targets(
            prefix="night_",
            step_id="initial_night_targets",
            next_step="manage_pause",
            user_input=user_input,
        )

    async def async_step_manage_pause(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer only pause durations that have a valid release condition."""
        if not self.advanced_mode:
            return await self.async_step_room_hub()
        room = self.room()
        modes = pause_modes_for_room(room)
        errors: dict[str, str] = {}
        if user_input is not None:
            values = _flatten_sections(user_input)
            if values.get("default_pause_mode") not in modes:
                errors["base"] = "pause_requires_night"
            else:
                room.update(values)
                if getattr(self, "_initial_setup", False):
                    return await self.async_step_manage_conditions()
                return await self.async_step_room_hub()
        pause_default = str(room.get("default_pause_mode", PAUSE_NEXT_SUNRISE))
        if pause_default not in modes:
            pause_default = PAUSE_NEXT_SUNRISE
        pause_fields: dict[Any, Any] = {
            vol.Required(
                "default_pause_mode", default=pause_default
            ): self._choice(modes, "pause_mode"),
            vol.Required(
                "pause_sun_offset_minutes",
                default=room.get("pause_sun_offset_minutes", -60),
            ): _number(-120, 240, 5, "min"),
            vol.Required(
                "pause_duration_hours",
                default=room.get("pause_duration_hours", 2.0),
            ): _number(
                PAUSE_DURATION_MIN_HOURS,
                PAUSE_DURATION_MAX_HOURS,
                PAUSE_DURATION_STEP_HOURS,
                "h",
            ),
            vol.Required(
                CONF_EXTERNAL_MOVEMENT_DETECTION,
                default=room.get(
                    CONF_EXTERNAL_MOVEMENT_DETECTION,
                    DEFAULT_EXTERNAL_MOVEMENT_DETECTION,
                ),
            ): selector.BooleanSelector(),
        }
        if str(room.get("indoor_temperature") or "").strip():
            pause_fields[
                vol.Required(
                    "heat_during_pause",
                    default=room.get("heat_during_pause", False),
                )
            ] = selector.BooleanSelector()
        return self.async_show_form(
            step_id="manage_pause",
            data_schema=self._form_schema(
                vol.Schema(pause_fields), user_input, errors
            ),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_manage_conditions(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show only conditions supported by the selected sources and profiles."""
        if not self.advanced_mode:
            return await self.async_step_room_hub()
        room = self.room()
        errors: dict[str, str] = {}
        source_keys = (
            "irradiance_sensor",
            "cloud_cover_sensor",
            "weather_permission",
            "glare_sensor",
            "occupancy_sensor",
        )
        safety_relevant = self._uses_exterior_safety(room)
        if user_input is not None:
            values = _flatten_sections(user_input)
            occupancy_sensor = str(values.get("occupancy_sensor") or "")
            if (
                values.get("comfort_requires_occupancy", False)
                and not occupancy_sensor
            ):
                errors["base"] = "occupancy_source_required"
            if not errors:
                selected_safety = (
                    list(values.get("safety_blockers") or [])
                    if safety_relevant
                    else []
                )
                source_changed = selected_safety != list(
                    room.get("safety_blockers", [])
                )
                room["safety_blockers"] = selected_safety
                for key in source_keys:
                    selected = str(values.get(key) or "")
                    source_changed = source_changed or selected != str(
                        room.get(key) or ""
                    )
                    room[key] = selected
                for key in (
                    "irradiance_minimum", "cloud_cover_maximum", "weather_logic",
                    "heat_ignores_weather", "heat_requires_sun",
                    "comfort_requires_occupancy", "safety_behavior",
                ):
                    if key in values:
                        room[key] = values[key]
                if not room.get("occupancy_sensor"):
                    room["comfort_requires_occupancy"] = False
                if not room.get("safety_blockers"):
                    room["safety_behavior"] = "move_safe"
                if source_changed:
                    return await self.async_step_manage_conditions()
                if getattr(self, "_initial_setup", False):
                    if (
                        room.get("safety_blockers")
                        and room.get("safety_behavior", "move_safe")
                        == "move_safe"
                    ):
                        self._initial_function_layer_index = 0
                        return await self.async_step_initial_safety_targets()
                    return await self.async_step_after_room()
                return await self.async_step_room_hub()
        fields: dict[Any, Any] = {}
        if safety_relevant:
            fields[_optional_marker(
                "safety_blockers", room.get("safety_blockers", [])
            )] = _entity("binary_sensor", multiple=True)
        fields[_optional_marker(
            "irradiance_sensor", room.get("irradiance_sensor", "")
        )] = _entity("sensor")
        if room.get("irradiance_sensor"):
            fields[vol.Required(
                "irradiance_minimum",
                default=room.get("irradiance_minimum", 150.0),
            )] = _number(
                IRRADIANCE_MINIMUM_MIN,
                IRRADIANCE_MINIMUM_MAX,
                IRRADIANCE_MINIMUM_STEP,
                "W/m²",
            )
        fields[_optional_marker(
            "cloud_cover_sensor", room.get("cloud_cover_sensor", "")
        )] = _entity("sensor")
        if room.get("cloud_cover_sensor"):
            fields[vol.Required(
                "cloud_cover_maximum",
                default=room.get("cloud_cover_maximum", 85.0),
            )] = _number(0, 100, 1, "%")
        fields[_optional_marker(
            "weather_permission", room.get("weather_permission", "")
        )] = _entity("binary_sensor")
        fields[_optional_marker(
            "glare_sensor", room.get("glare_sensor", "")
        )] = _entity("binary_sensor")
        fields[_optional_marker(
            "occupancy_sensor", room.get("occupancy_sensor", "")
        )] = _entity("binary_sensor")

        weather_source_count = sum(
            bool(room.get(key))
            for key in (
                "irradiance_sensor",
                "cloud_cover_sensor",
                "weather_permission",
            )
        )
        if weather_source_count > 1:
            fields[vol.Required(
                "weather_logic", default=room.get("weather_logic", "all")
            )] = self._choice(["all", "any"], "weather_logic")
        if room.get("occupancy_sensor"):
            fields[vol.Required(
                "comfort_requires_occupancy",
                default=room.get("comfort_requires_occupancy", False),
            )] = selector.BooleanSelector()
        if safety_relevant and room.get("safety_blockers"):
            fields[vol.Required(
                "safety_behavior",
                default=room.get("safety_behavior", "move_safe"),
            )] = self._choice(["move_safe", "block"], "safety_behavior")
        if str(room.get("indoor_temperature") or "").strip():
            if weather_source_count:
                fields[vol.Required(
                    "heat_ignores_weather",
                    default=room.get("heat_ignores_weather", True),
                )] = selector.BooleanSelector()
            fields[vol.Required(
                "heat_requires_sun",
                default=room.get("heat_requires_sun", True),
            )] = selector.BooleanSelector()
        return self.async_show_form(
            step_id="manage_conditions",
            data_schema=self._form_schema(
                vol.Schema(fields), user_input, errors
            ),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_initial_safety_targets(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer safe targets only after move-to-safe protection is enabled."""
        return await self._async_step_initial_function_targets(
            prefix="safety_",
            step_id="initial_safety_targets",
            next_step="after_room",
            user_input=user_input,
        )

    async def async_step_manage_sector(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit one sector through one explicit sun-source contract."""
        sector = self.sector()
        errors: dict[str, str] = {}
        submitted_values: dict[str, Any] = {}
        allowed_sources = {"geometry", "lux", "external"}
        current_source = sun_source_for_sector(
            sector, advanced=self.advanced_mode
        )

        if user_input is not None:
            values = _flatten_sections(user_input)
            submitted_values = values
            if values.get("delete_sector", False):
                if len(self.room().get("sectors", [])) <= 1:
                    errors["base"] = "cannot_delete_last_sector"
                else:
                    self.room()["sectors"] = [
                        item
                        for item in self.room().get("sectors", [])
                        if item["id"] != sector["id"]
                    ]
                    return await self.async_step_structure_hub()

            selected_source = current_source
            if selected_source not in allowed_sources:
                errors["base"] = "option_not_available"
            elif selected_source != current_source:
                previous_direction = str(
                    sector.get("direction", DIRECTION_CUSTOM)
                )
                selected_direction = str(
                    values.get("direction", previous_direction)
                )
                direction = (
                    previous_direction
                    if selected_direction == "keep_current"
                    else selected_direction
                )
                if direction != DIRECTION_CUSTOM:
                    defaults = self._direction_defaults(direction)
                    for key in (
                        "azimuth_start",
                        "azimuth_end",
                        "elevation_min",
                    ):
                        sector[key] = defaults[key]
                elif self.advanced_mode:
                    for key in (
                        "azimuth_start",
                        "azimuth_end",
                        "elevation_min",
                    ):
                        if key in values:
                            sector[key] = values[key]
                sector["direction"] = direction
                sector["name"] = str(
                    values.get("name")
                    or sector.get("name", "Sun sector")
                )
                sector["short"] = str(
                    values.get("short") or sector.get("short", "S")
                ).upper()
                sector["sun_source"] = selected_source
                sector["lux_sensor"] = ""
                sector[CONF_SUN_PRESENCE_ENTITY] = ""
                if selected_source != "lux":
                    sector["sun_preset"] = PRESET_MEDIUM
                return await self.async_step_manage_sector()
            selected_preset = str(
                values.get("sun_preset", sector.get("sun_preset", PRESET_MEDIUM))
            )
            preset = (
                str(sector.get("sun_preset", PRESET_MEDIUM))
                if selected_preset == "keep_current"
                else selected_preset
            )
            if (
                not errors
                and selected_source == "lux"
                and preset == PRESET_CUSTOM
                and all(
                    key in values
                    for key in (
                        "sun_on_lux",
                        "sun_off_lux",
                        "sun_on_delay",
                        "sun_off_delay",
                    )
                )
                and float(values["sun_on_lux"]) <= float(values["sun_off_lux"])
            ):
                errors["base"] = "lux_hysteresis"

            if not errors:
                previous_direction = str(
                    sector.get("direction", DIRECTION_CUSTOM)
                )
                previous_preset = str(
                    sector.get("sun_preset", PRESET_MEDIUM)
                )
                selected_direction = str(
                    values.get("direction", previous_direction)
                )
                direction = (
                    previous_direction
                    if selected_direction == "keep_current"
                    else selected_direction
                )
                if direction != DIRECTION_CUSTOM:
                    defaults = self._direction_defaults(direction)
                    for key in ("azimuth_start", "azimuth_end", "elevation_min"):
                        sector[key] = defaults[key]
                elif self.advanced_mode:
                    for key in ("azimuth_start", "azimuth_end", "elevation_min"):
                        if key in values:
                            sector[key] = values[key]

                sector.update(
                    {
                        "direction": direction,
                        "name": str(
                            values.get("name")
                            or sector.get("name", "Sun sector")
                        ),
                        "short": str(
                            values.get("short") or sector.get("short", "S")
                        ).upper(),
                        "sun_source": selected_source,
                        "lux_sensor": (
                            sector.get("lux_sensor", "")
                            if selected_source == "lux"
                            else ""
                        ),
                        CONF_SUN_PRESENCE_ENTITY: (
                            sector.get(CONF_SUN_PRESENCE_ENTITY, "")
                            if selected_source == "external"
                            else ""
                        ),
                        "sun_preset": (
                            preset if selected_source == "lux" else PRESET_MEDIUM
                        ),
                    }
                )
                if selected_source == "lux":
                    if preset in SUN_PRESETS:
                        sector.update(SUN_PRESETS[preset])
                    elif preset == PRESET_CUSTOM:
                        for key in (
                            "sun_on_lux",
                            "sun_off_lux",
                            "sun_on_delay",
                            "sun_off_delay",
                        ):
                            if key in values:
                                sector[key] = values[key]

                needs_second_pass = self.advanced_mode and (
                    (
                        direction == DIRECTION_CUSTOM
                        and previous_direction != DIRECTION_CUSTOM
                    )
                    or (
                        selected_source == "lux"
                        and preset == PRESET_CUSTOM
                        and previous_preset != PRESET_CUSTOM
                    )
                )
                if needs_second_pass:
                    if direction == DIRECTION_CUSTOM:
                        return await self.async_step_manage_sector_geometry()
                    return await self.async_step_sector_hub()

                next_step = getattr(self, "_after_sector_step", None)
                if next_step:
                    self._after_sector_step = None
                    return await getattr(self, f"async_step_{next_step}")()
                return await self.async_step_sector_hub()

        legacy_direction = (
            not self.advanced_mode
            and sector.get("direction") == DIRECTION_CUSTOM
        )
        direction_options = (
            list(DIRECTION_OPTIONS)
            if self.advanced_mode
            else [
                item for item in DIRECTION_OPTIONS
                if item != DIRECTION_CUSTOM
            ]
        )
        if legacy_direction:
            direction_options.append("keep_current")
        identity: dict[Any, Any] = {
            vol.Required(
                "name", default=sector.get("name", "")
            ): selector.TextSelector(),
            vol.Required(
                "short", default=sector.get("short", "")
            ): selector.TextSelector(),
            vol.Required(
                "direction",
                default=(
                    "keep_current"
                    if legacy_direction
                    else sector.get("direction", "south")
                ),
            ): self._choice(direction_options, "direction_preset"),
        }
        if self.advanced_mode and sector.get("direction") == DIRECTION_CUSTOM:
            identity.update(
                {
                    vol.Required(
                        "azimuth_start",
                        default=sector.get("azimuth_start", 120),
                    ): _number(0, 359, 1, "°"),
                    vol.Required(
                        "azimuth_end",
                        default=sector.get("azimuth_end", 240),
                    ): _number(0, 359, 1, "°"),
                    vol.Required(
                        "elevation_min",
                        default=sector.get("elevation_min", 10),
                    ): _number(-10, 90, 1, "°"),
                }
            )

        confirmation: dict[Any, Any] = {
            vol.Required("sun_source", default=current_source): self._choice(
                ["geometry", "lux", "external"], "sun_source"
            )
        }
        if current_source == "lux":
            legacy_sensitivity = (
                not self.advanced_mode
                and sector.get("sun_preset") == PRESET_CUSTOM
            )
            sun_options = (
                list(SUN_PRESET_OPTIONS)
                if self.advanced_mode
                else ["low", "medium", "high"]
            )
            if legacy_sensitivity:
                sun_options.append("keep_current")
            confirmation[
                vol.Required(
                    "lux_sensor", default=sector.get("lux_sensor", "")
                )
            ] = _entity("sensor")
            confirmation[
                vol.Required(
                    "sun_preset",
                    default=(
                        "keep_current"
                        if legacy_sensitivity
                        else sector.get("sun_preset", PRESET_MEDIUM)
                    ),
                )
            ] = self._choice(sun_options, "sun_preset")
            if (
                self.advanced_mode
                and sector.get("sun_preset") == PRESET_CUSTOM
            ):
                confirmation.update(
                    {
                        vol.Required(
                            "sun_on_lux",
                            default=sector.get(
                                "sun_on_lux",
                                SUN_PRESETS[PRESET_MEDIUM]["sun_on_lux"],
                            ),
                        ): _number(0, 200000, 500, "lx"),
                        vol.Required(
                            "sun_off_lux",
                            default=sector.get(
                                "sun_off_lux",
                                SUN_PRESETS[PRESET_MEDIUM]["sun_off_lux"],
                            ),
                        ): _number(0, 200000, 500, "lx"),
                        vol.Required(
                            "sun_on_delay",
                            default=sector.get(
                                "sun_on_delay",
                                SUN_PRESETS[PRESET_MEDIUM]["sun_on_delay"],
                            ),
                        ): _number(0, 60, 0.5, "min"),
                        vol.Required(
                            "sun_off_delay",
                            default=sector.get(
                                "sun_off_delay",
                                SUN_PRESETS[PRESET_MEDIUM]["sun_off_delay"],
                            ),
                        ): _number(0, 120, 0.5, "min"),
                    }
                )
        elif current_source == "external":
            confirmation[
                vol.Required(
                    CONF_SUN_PRESENCE_ENTITY,
                    default=sector.get(CONF_SUN_PRESENCE_ENTITY, ""),
                )
            ] = _entity(["binary_sensor", "input_boolean", "switch"])

        sections: dict[Any, Any] = {
            vol.Required("sector_identity"): section(
                self._form_schema(
                    vol.Schema(identity), submitted_values, errors
                ),
                {"collapsed": False},
            ),
        }
        if not getattr(self, "_after_sector_step", None):
            sections[vol.Required("sector_maintenance")] = section(
                self._form_schema(
                    vol.Schema(
                        {
                            vol.Required(
                                "delete_sector", default=False
                            ): selector.BooleanSelector()
                        }
                    ),
                    submitted_values,
                    errors,
                ),
                {"collapsed": True},
            )
        return self.async_show_form(
            step_id="manage_sector",
            data_schema=self._form_schema(
                vol.Schema(sections), user_input, errors
            ),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_manage_sector_source(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select one sun source before opening its focused configuration."""
        sector = self.sector()
        current_source = sun_source_for_sector(
            sector, advanced=self.advanced_mode
        )
        errors: dict[str, str] = {}
        if user_input is not None:
            source = str(user_input.get("sun_source", current_source))
            if source not in {"geometry", "lux", "external"}:
                errors["base"] = "option_not_available"
            else:
                sector["sun_source"] = source
                if source != "lux":
                    sector["lux_sensor"] = ""
                    sector["sun_preset"] = PRESET_MEDIUM
                if source != "external":
                    sector[CONF_SUN_PRESENCE_ENTITY] = ""
                if source == "geometry":
                    return await self.async_step_sector_hub()
                self._after_source_step = "sector_hub"
                return await self.async_step_configure_sector_source()
        return self.async_show_form(
            step_id="manage_sector_source",
            data_schema=self._form_schema(
                vol.Schema(
                    {
                        vol.Required(
                            "sun_source", default=current_source
                        ): self._choice(
                            ["geometry", "lux", "external"], "sun_source"
                        )
                    }
                ),
                user_input,
                errors,
            ),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_configure_sector_source(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure only the entity required by the selected sun source."""
        sector = self.sector()
        source = str(sector.get("sun_source", "geometry"))
        if source == "geometry":
            return await self._go_to_saved_step(
                "_after_source_step", fallback="sector_hub"
            )
        errors: dict[str, str] = {}
        fields: dict[Any, Any] = {}
        if source == "lux":
            options = (
                list(SUN_PRESET_OPTIONS)
                if self.advanced_mode
                else ["low", "medium", "high"]
            )
            current_preset = str(sector.get("sun_preset", PRESET_MEDIUM))
            if current_preset not in options:
                current_preset = PRESET_MEDIUM
            fields = {
                vol.Required(
                    "lux_sensor", default=sector.get("lux_sensor", "")
                ): _entity("sensor"),
                vol.Required(
                    "sun_preset", default=current_preset
                ): self._choice(options, "sun_preset"),
            }
        elif source == "external":
            fields = {
                vol.Required(
                    CONF_SUN_PRESENCE_ENTITY,
                    default=sector.get(CONF_SUN_PRESENCE_ENTITY, ""),
                ): _entity(["binary_sensor", "input_boolean", "switch"])
            }
        else:
            return await self.async_step_manage_sector_source()

        if user_input is not None:
            values = dict(user_input)
            if source == "lux" and not str(values.get("lux_sensor") or ""):
                errors["base"] = "sun_source_required"
            elif source == "external" and not str(
                values.get(CONF_SUN_PRESENCE_ENTITY) or ""
            ):
                errors["base"] = "sun_source_required"
            else:
                if source == "lux":
                    preset = str(values.get("sun_preset", PRESET_MEDIUM))
                    sector["lux_sensor"] = str(values["lux_sensor"])
                    sector[CONF_SUN_PRESENCE_ENTITY] = ""
                    sector["sun_preset"] = preset
                    if preset == PRESET_CUSTOM and self.advanced_mode:
                        self._after_lux_step = str(
                            getattr(self, "_after_source_step", None)
                            or "sector_hub"
                        )
                        self._after_source_step = None
                        return await self.async_step_configure_lux_profile()
                    sector.update(SUN_PRESETS[preset])
                else:
                    sector[CONF_SUN_PRESENCE_ENTITY] = str(
                        values[CONF_SUN_PRESENCE_ENTITY]
                    )
                    sector["lux_sensor"] = ""
                    sector["sun_preset"] = PRESET_MEDIUM
                return await self._go_to_saved_step(
                    "_after_source_step", fallback="sector_hub"
                )
        return self.async_show_form(
            step_id="configure_sector_source",
            data_schema=self._form_schema(
                vol.Schema(fields), user_input, errors
            ),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_configure_lux_profile(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure custom Lux hysteresis without reloading another form."""
        sector = self.sector()
        errors: dict[str, str] = {}
        fields: dict[Any, Any] = {
            vol.Required(
                "sun_on_lux",
                default=sector.get(
                    "sun_on_lux", SUN_PRESETS[PRESET_MEDIUM]["sun_on_lux"]
                ),
            ): _number(0, 200000, 500, "lx"),
            vol.Required(
                "sun_off_lux",
                default=sector.get(
                    "sun_off_lux", SUN_PRESETS[PRESET_MEDIUM]["sun_off_lux"]
                ),
            ): _number(0, 200000, 500, "lx"),
            vol.Required(
                "sun_on_delay",
                default=sector.get(
                    "sun_on_delay", SUN_PRESETS[PRESET_MEDIUM]["sun_on_delay"]
                ),
            ): _number(0, 60, 0.5, "min"),
            vol.Required(
                "sun_off_delay",
                default=sector.get(
                    "sun_off_delay", SUN_PRESETS[PRESET_MEDIUM]["sun_off_delay"]
                ),
            ): _number(0, 120, 0.5, "min"),
        }
        if user_input is not None:
            if float(user_input["sun_on_lux"]) <= float(
                user_input["sun_off_lux"]
            ):
                errors["base"] = "lux_hysteresis"
            else:
                for key in (
                    "sun_on_lux",
                    "sun_off_lux",
                    "sun_on_delay",
                    "sun_off_delay",
                ):
                    sector[key] = float(user_input[key])
                return await self._go_to_saved_step(
                    "_after_lux_step", fallback="sector_hub"
                )
        return self.async_show_form(
            step_id="configure_lux_profile",
            data_schema=self._form_schema(
                vol.Schema(fields), user_input, errors
            ),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_manage_sector_geometry(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure custom sun geometry on a dedicated Advanced page."""
        if not self.advanced_mode:
            return await self.async_step_sector_hub()
        sector = self.sector()
        errors: dict[str, str] = {}
        fields = {
            vol.Required(
                "azimuth_start", default=sector.get("azimuth_start", 120)
            ): _number(0, 359, 1, "°"),
            vol.Required(
                "azimuth_end", default=sector.get("azimuth_end", 240)
            ): _number(0, 359, 1, "°"),
            vol.Required(
                "elevation_min", default=sector.get("elevation_min", 10)
            ): _number(-10, 90, 1, "°"),
        }
        if user_input is not None:
            for key in ("azimuth_start", "azimuth_end", "elevation_min"):
                sector[key] = float(user_input[key])
            return await self._go_to_saved_step(
                "_after_source_step", fallback="sector_hub"
            )
        return self.async_show_form(
            step_id="manage_sector_geometry",
            data_schema=self._form_schema(
                vol.Schema(fields), user_input, errors
            ),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_add_sector_flat(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Start one atomic sector, group and cover creation chain."""
        errors: dict[str, str] = {}
        if user_input is not None:
            values = _flatten_sections(user_input)
            allowed_sources = {"geometry", "lux", "external"}
            source = str(values.get("sun_source", "geometry"))
            direction = str(values.get("direction", "south"))
            if source not in allowed_sources or (
                not self.advanced_mode and direction == DIRECTION_CUSTOM
            ):
                errors["base"] = "option_not_available"
            else:
                sector = self._direction_defaults(direction)
                sector.update(
                    {
                        "id": _new_id(sector["name"]),
                        "direction": direction,
                        "name": str(values.get("name") or sector["name"]),
                        "short": str(
                            values.get("short") or sector["short"]
                        ).upper(),
                        "lux_sensor": "",
                        CONF_SUN_PRESENCE_ENTITY: "",
                        "sun_preset": PRESET_MEDIUM,
                        "sun_source": source,
                        "layers": [],
                    }
                )
                self._pending_sector = sector
                self._pending_layer = None
                self._sector_id = str(sector["id"])
                self._layer_id = None
                if direction == DIRECTION_CUSTOM:
                    self._after_source_step = "continue_pending_sector_source"
                    return await self.async_step_manage_sector_geometry()
                if source == "geometry":
                    return await self.async_step_add_sector_group()
                self._after_source_step = "add_sector_group"
                return await self.async_step_configure_sector_source()

        fields: dict[Any, Any] = {
            vol.Required("name"): selector.TextSelector(),
            vol.Required("short"): selector.TextSelector(),
            vol.Required("direction", default="south"): self._choice(
                DIRECTION_OPTIONS
                if self.advanced_mode
                else [
                    item for item in DIRECTION_OPTIONS
                    if item != DIRECTION_CUSTOM
                ],
                "direction_preset",
            ),
            vol.Required("sun_source", default="geometry"): self._choice(
                ["geometry", "lux", "external"], "sun_source"
            ),
        }
        default_name, default_short = _direction_name(
            "south", getattr(self.hass.config, "language", "en") or "en"
        )
        return self.async_show_form(
            step_id="add_sector_flat",
            data_schema=self._form_schema(
                self.add_suggested_values_to_schema(
                    vol.Schema(fields),
                    {"name": default_name, "short": default_short},
                ),
                user_input,
                errors,
            ),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_continue_pending_sector_source(
        self, user_input=None
    ) -> ConfigFlowResult:
        """Continue custom geometry through its selected source."""
        if str(self.sector().get("sun_source", "geometry")) == "geometry":
            return await self.async_step_add_sector_group()
        self._after_source_step = "add_sector_group"
        return await self.async_step_configure_sector_source()

    async def async_step_add_sector_group(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the first group inside a pending sector."""
        errors: dict[str, str] = {}
        if user_input is not None:
            values = dict(user_input)
            profile = str(values.get("profile", DEVICE_VENETIAN))
            default_name = (
                "Behanggruppe" if self._is_german() else "Cover group"
            )
            layer = self._new_layer(
                str(values.get("name") or default_name), profile
            )
            self.sector()["layers"] = [layer]
            self._pending_layer = layer
            self._layer_id = str(layer["id"])
            if self.advanced_mode and (
                profile_supports_position(profile)
                or profile_supports_tilt(profile)
            ):
                self._after_layer_profile_step = "add_sector_covers"
                return await self.async_step_manage_layer_profile()
            return await self.async_step_add_sector_covers()
        fields = {
            vol.Required(
                "name",
                default=(
                    "Behanggruppe" if self._is_german() else "Cover group"
                ),
            ): selector.TextSelector(),
            vol.Required(
                "profile", default=DEVICE_VENETIAN
            ): self._choice(DEVICE_TYPES, "device_type"),
        }
        return self.async_show_form(
            step_id="add_sector_group",
            data_schema=self._form_schema(
                vol.Schema(fields), user_input, errors
            ),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_add_sector_covers(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Require covers before committing a complete new sector."""
        errors: dict[str, str] = {}
        if user_input is not None:
            entities = list(user_input.get("cover_entities", []))
            duplicates = sorted(set(entities) & self.all_cover_entities())
            if duplicates:
                errors["base"] = "cover_already_assigned"
            elif not entities:
                errors["base"] = "select_at_least_one"
            else:
                self._pending_cover_entities = entities
                self._pending_cover_index = 0
                self._pending_cover_short_offset = 0
                self._pending_cover_return_step = "commit_pending_sector"
                return await self.async_step_compact_cover_details()
        return self.async_show_form(
            step_id="add_sector_covers",
            data_schema=self._form_schema(
                vol.Schema(
                    {
                        vol.Required("cover_entities"): _entity(
                            "cover", multiple=True
                        )
                    }
                ),
                user_input,
                errors,
            ),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_commit_pending_sector(
        self, user_input=None
    ) -> ConfigFlowResult:
        """Commit a sector only after its group and covers are complete."""
        sector = getattr(self, "_pending_sector", None)
        if sector is None or not sector.get("layers"):
            return await self.async_step_structure_hub()
        if not sector["layers"][0].get("covers"):
            return await self.async_step_add_sector_covers()
        self.room().setdefault("sectors", []).append(sector)
        self._pending_sector = None
        self._pending_layer = None
        if getattr(self, "_initial_setup", False):
            if self.advanced_mode:
                self._initial_special_cover_index = 0
                return await self.async_step_initial_cover_special_functions()
            return await self.async_step_after_room()
        return await self.async_step_sector_hub()

    async def async_step_manage_layer(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit only group identity; profile behavior has its own page."""
        layer = self.layer()
        errors: dict[str, str] = {}
        if user_input is not None:
            values = _flatten_sections(user_input)
            if values.get("delete_layer", False):
                if getattr(self, "_continue_cover_setup", False):
                    errors["base"] = "option_not_available"
                elif len(self.sector().get("layers", [])) <= 1:
                    errors["base"] = "cannot_delete_last_layer"
                else:
                    self.sector()["layers"] = [
                        item for item in self.sector().get("layers", [])
                        if item["id"] != layer["id"]
                    ]
                    self._layer_id = None
                    return await self.async_step_sector_hub()
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
                    self._normalize_covers_for_profile(covers, profile)
                    if not self._uses_exterior_safety():
                        self.room()["safety_blockers"] = []
                layer["name"] = str(
                    values.get("name") or layer.get("name", "Cover group")
                )
                if profile_changed:
                    return await self.async_step_manage_layer_profile()
                return await self.async_step_group_hub()
        identity: dict[Any, Any] = {
            vol.Required("name", default=layer.get("name", "")): selector.TextSelector(),
            vol.Required("profile", default=layer.get("profile", DEVICE_VENETIAN)): self._choice(DEVICE_TYPES, "device_type"),
        }
        sections: dict[Any, Any] = {
            vol.Required("group_identity"): section(vol.Schema(identity), {"collapsed": False}),
        }
        if not getattr(self, "_continue_cover_setup", False):
            sections[vol.Required("group_maintenance")] = section(
                vol.Schema(
                    {
                        vol.Required(
                            "delete_layer", default=False
                        ): selector.BooleanSelector()
                    }
                ),
                {"collapsed": True},
            )
        return self.async_show_form(
            step_id="manage_layer",
            data_schema=self._form_schema(
                vol.Schema(sections), user_input, errors
            ),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_manage_layer_profile(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show only options supported by the already selected cover type."""
        layer = self.layer()
        profile = str(layer.get("profile", DEVICE_VENETIAN))
        has_position = profile_supports_position(profile)
        has_tilt = profile_supports_tilt(profile)
        has_indoor_temperature = bool(
            str(self.room().get("indoor_temperature") or "").strip()
        )
        errors: dict[str, str] = {}
        if user_input is not None:
            values = _flatten_sections(user_input)
            curve_values_present = all(
                f"elevation_{index}" in values
                and f"tilt_{index}" in values
                for index in range(1, 5)
            )
            preset = str(
                values.get(
                    "tilt_preset",
                    layer.get("tilt_preset", TILT_PRESET_BALANCED),
                )
            )
            if has_tilt and preset == TILT_PRESET_CUSTOM and curve_values_present:
                elevations = [
                    float(values[f"elevation_{index}"])
                    for index in range(1, 5)
                ]
                if any(
                    elevations[index] >= elevations[index + 1]
                    for index in range(3)
                ):
                    errors["base"] = "elevation_order"
            if not errors:
                if has_position and "position_tolerance" in values:
                    layer["position_tolerance"] = float(
                        values["position_tolerance"]
                    )
                if has_tilt:
                    previous_preset = str(
                        layer.get("tilt_preset", TILT_PRESET_BALANCED)
                    )
                    layer["tilt_preset"] = preset
                    if preset in TILT_CURVE_PRESETS:
                        layer["tilt_curve"] = deepcopy(TILT_CURVE_PRESETS[preset])
                    elif preset == TILT_PRESET_CUSTOM and curve_values_present:
                        layer["tilt_curve"] = [
                            {
                                "elevation": float(values[f"elevation_{index}"]),
                                "tilt": float(values[f"tilt_{index}"]),
                            }
                            for index in range(1, 5)
                        ]
                    if "tilt_tolerance" in values:
                        layer["tilt_tolerance"] = float(values["tilt_tolerance"])
                    if preset == TILT_PRESET_CUSTOM and (
                        previous_preset != TILT_PRESET_CUSTOM
                        or not curve_values_present
                    ):
                        rerender_custom_curve = True
                for key in profile_target_keys(
                    profile,
                    indoor_temperature=has_indoor_temperature,
                    night=bool(self.room().get("night_enabled", False)),
                    safety=bool(self.room().get("safety_blockers")),
                ):
                    if key in values:
                        layer[key] = values[key]
                if rerender_custom_curve:
                    return await self.async_step_manage_layer_profile()
                return await self._go_to_saved_step(
                    "_after_layer_profile_step", fallback="group_hub"
                )

        behavior: dict[Any, Any] = {}
        if has_position:
            behavior[
                vol.Required(
                    "position_tolerance",
                    default=layer.get(
                        "position_tolerance", DEFAULT_POSITION_TOLERANCE
                    ),
                )
            ] = _number(0, 15, 1, "%")
        if has_tilt:
            behavior[
                vol.Required(
                    "tilt_preset",
                    default=layer.get("tilt_preset", TILT_PRESET_BALANCED),
                )
            ] = self._choice(TILT_PRESET_OPTIONS, "tilt_preset")
            behavior[
                vol.Required(
                    "tilt_tolerance",
                    default=layer.get(
                        "tilt_tolerance", DEFAULT_TILT_TOLERANCE
                    ),
                )
            ] = _number(0, 15, 1, "%")
        sections: dict[Any, Any] = {}
        if behavior:
            sections[vol.Required("profile_behavior")] = section(
                vol.Schema(behavior), {"collapsed": False}
            )
        if has_tilt and layer.get("tilt_preset") == TILT_PRESET_CUSTOM:
            curve = list(
                layer.get("tilt_curve")
                or TILT_CURVE_PRESETS[TILT_PRESET_BALANCED]
            )
            if len(curve) != 4:
                curve = deepcopy(TILT_CURVE_PRESETS[TILT_PRESET_BALANCED])
            curve_fields: dict[Any, Any] = {}
            for index, point in enumerate(curve, start=1):
                curve_fields[
                    vol.Required(
                        f"elevation_{index}", default=point["elevation"]
                    )
                ] = _number(-10, 90, 1, "°")
                curve_fields[
                    vol.Required(f"tilt_{index}", default=point["tilt"])
                ] = _number(0, 100, 1, "%")
            sections[vol.Required("slat_curve")] = section(
                vol.Schema(curve_fields), {"collapsed": False}
            )
        if has_position:
            targets = {
                vol.Required(
                    key,
                    default=layer.get(
                        key, PROFILE_DEFAULTS[profile].get(key, 0.0)
                    ),
                ): _number(0, 100, 1, "%")
                for key in profile_target_keys(
                    profile,
                    indoor_temperature=has_indoor_temperature,
                    night=bool(self.room().get("night_enabled", False)),
                    safety=bool(self.room().get("safety_blockers")),
                )
            }
            if targets:
                sections[vol.Required("target_positions")] = section(
                    vol.Schema(targets), {"collapsed": True}
                )
        if not sections:
            return await self._go_to_saved_step(
                "_after_layer_profile_step", fallback="group_hub"
            )
        return self.async_show_form(
            step_id="manage_layer_profile",
            data_schema=self._form_schema(
                vol.Schema(sections), user_input, errors
            ),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_add_layer_flat(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Start an atomic group-and-cover creation chain."""
        errors: dict[str, str] = {}
        if user_input is not None:
            values = _flatten_sections(user_input)
            profile = str(values.get("profile", DEVICE_VENETIAN))
            default_name = (
                "Behanggruppe" if self._is_german() else "Cover group"
            )
            layer = self._new_layer(
                str(values.get("name") or default_name), profile
            )
            layer["covers"] = []
            self._pending_layer = layer
            self._layer_id = str(layer["id"])
            if self.advanced_mode and (
                profile_supports_position(profile)
                or profile_supports_tilt(profile)
            ):
                self._after_layer_profile_step = "add_group_covers"
                return await self.async_step_manage_layer_profile()
            return await self.async_step_add_group_covers()
        fields: dict[Any, Any] = {
            vol.Required(
                "name", default="Behanggruppe" if self._is_german() else "Cover group"
            ): selector.TextSelector(),
            vol.Required("profile", default=DEVICE_VENETIAN): self._choice(DEVICE_TYPES, "device_type"),
        }
        return self.async_show_form(
            step_id="add_layer_flat",
            data_schema=self._form_schema(
                vol.Schema(fields), user_input, errors
            ),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_add_group_covers(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Require covers before committing a new group."""
        errors: dict[str, str] = {}
        if user_input is not None:
            entities = list(user_input.get("cover_entities", []))
            duplicates = sorted(set(entities) & self.all_cover_entities())
            if duplicates:
                errors["base"] = "cover_already_assigned"
            elif not entities:
                errors["base"] = "select_at_least_one"
            else:
                self._pending_cover_entities = entities
                self._pending_cover_index = 0
                self._pending_cover_short_offset = 0
                self._pending_cover_return_step = "commit_pending_layer"
                return await self.async_step_compact_cover_details()
        return self.async_show_form(
            step_id="add_group_covers",
            data_schema=self._form_schema(
                vol.Schema(
                    {
                        vol.Required("cover_entities"): _entity(
                            "cover", multiple=True
                        )
                    }
                ),
                user_input,
                errors,
            ),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_commit_pending_layer(
        self, user_input=None
    ) -> ConfigFlowResult:
        """Commit a group only after at least one cover is configured."""
        layer = getattr(self, "_pending_layer", None)
        if layer is None:
            return await self.async_step_sector_hub()
        if not layer.get("covers"):
            return await self.async_step_add_group_covers()
        self.sector().setdefault("layers", []).append(layer)
        self._pending_layer = None
        return await self.async_step_group_hub()

    async def async_step_manage_cover(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit one cover using only settings supported by its group."""
        covers = self.layer().get("covers", [])
        cover = covers[self._cover_index]
        profile = str(self.layer().get("profile", DEVICE_VENETIAN))
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
                    return await self.async_step_group_hub()
            if not errors:
                cover["name"] = str(values.get("name") or cover.get("name", "Cover"))
                cover["short"] = str(values.get("short") or cover.get("short", ""))
                if self.advanced_mode:
                    cover["lock"] = values.get("lock", "")
                    cover["window"] = values.get("window", "")
                    for key in (
                        "window_safe_state", "window_policy",
                        CONF_WINDOW_RETURNS_TO_AUTOMATION, "invert_position",
                    ):
                        if key in values:
                            cover[key] = values[key]
                    cover["invert_tilt"] = (
                        bool(values.get("invert_tilt", False))
                        if profile_supports_tilt(profile)
                        else False
                    )
                return await self.async_step_cover_settings_hub()
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
                vol.Required("invert_position", default=cover.get("invert_position", False)): selector.BooleanSelector(),
            }
            if profile_supports_tilt(profile):
                automation[
                    vol.Required(
                        "invert_tilt",
                        default=cover.get("invert_tilt", False),
                    )
                ] = selector.BooleanSelector()
            sections[vol.Required("cover_automation")] = section(vol.Schema(automation), {"collapsed": True})
        sections[vol.Required("cover_maintenance")] = section(vol.Schema({vol.Required("remove_cover", default=False): selector.BooleanSelector()}), {"collapsed": True})
        return self.async_show_form(
            step_id="manage_cover",
            data_schema=self._form_schema(
                vol.Schema(sections), user_input, errors
            ),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_manage_cover_special(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure opt-in cover behavior that may override manual movement."""
        cover = self.layer().get("covers", [])[self._cover_index]
        profile = str(self.layer().get("profile", DEVICE_VENETIAN))
        if not self.advanced_mode or not profile_supports_position(profile):
            return await self._go_to_saved_step(
                "_special_return_step", fallback="cover_settings_hub"
            )
        current_enabled = bool(
            cover.get("enforce_max_open_position", False)
        )
        if user_input is not None:
            enabled = bool(
                user_input.get("enforce_max_open_position", False)
            )
            cover["enforce_max_open_position"] = enabled
            if enabled and not current_enabled:
                return await self.async_step_manage_cover_special()
            if enabled and "max_open_position" in user_input:
                cover["max_open_position"] = float(
                    user_input["max_open_position"]
                )
            return await self._go_to_saved_step(
                "_special_return_step", fallback="cover_settings_hub"
            )
        fields: dict[Any, Any] = {
            vol.Required(
                "enforce_max_open_position", default=current_enabled
            ): selector.BooleanSelector()
        }
        if current_enabled:
            fields[
                vol.Required(
                    "max_open_position",
                    default=cover.get("max_open_position", 100.0),
                )
            ] = _number(0, 100, 1, "%")
        return self.async_show_form(
            step_id="manage_cover_special",
            data_schema=vol.Schema(fields),
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_initial_cover_special_functions(
        self, user_input=None
    ) -> ConfigFlowResult:
        """Offer every new Advanced cover its opt-in special functions."""
        covers = list(self.layer().get("covers", []))
        index = int(getattr(self, "_initial_special_cover_index", 0))
        if index >= len(covers):
            self._cover_index = None
            self._initial_special_cover_index = 0
            return await self.async_step_manage_automation()
        self._cover_index = index
        self._special_return_step = "continue_initial_cover_special_functions"
        return await self.async_step_manage_cover_special()

    async def async_step_continue_initial_cover_special_functions(
        self, user_input=None
    ) -> ConfigFlowResult:
        self._initial_special_cover_index = int(
            getattr(self, "_initial_special_cover_index", 0)
        ) + 1
        return await self.async_step_initial_cover_special_functions()

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
                existing_count = len(self.layer().get("covers", []))
                self._pending_cover_entities = entities
                self._pending_cover_index = 0
                self._pending_cover_return_step = "group_hub"
                self._pending_cover_short_offset = existing_count
                return await self.async_step_compact_cover_details()
        return self.async_show_form(
            step_id="add_covers_flat",
            data_schema=self._form_schema(
                vol.Schema(
                    {
                        vol.Required("cover_entities"): _entity(
                            "cover", multiple=True
                        )
                    }
                ),
                user_input,
                errors,
            ),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_add_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create every room through the same fixed setup contract."""
        self._initial_setup = True
        return await SmartShadingConfigFlow._async_step_room_setup(self, user_input)

    async def async_step_compact_cover_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reuse the complete per-cover setup for newly created rooms."""
        return await SmartShadingConfigFlow.async_step_compact_cover_details(
            self, user_input
        )

    async def async_step_after_room(self, user_input=None) -> ConfigFlowResult:
        """Return a completed options-room setup to its task overview."""
        self._initial_setup = False
        return await self.async_step_room_hub()

    async def async_step_finish(self, user_input=None) -> ConfigFlowResult:
        if not self.rooms:
            return self.async_abort(reason="no_rooms")
        placeholders, issues = SmartShadingConfigFlow._review_snapshot(self)
        if issues:
            return self.async_show_form(
                step_id="finish",
                data_schema=vol.Schema({}),
                errors={"base": "incomplete_configuration"},
                description_placeholders=placeholders,
            )
        engine = getattr(self.config_entry, "runtime_data", None)
        store = getattr(engine, "store", None)
        if store is not None:
            await store.async_clear_overrides()
        return self.async_create_entry(title="", data=editable_options(self._working))
