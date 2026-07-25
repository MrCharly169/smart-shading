from __future__ import annotations

from copy import deepcopy
import hashlib
import math
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
    ADVANCED_FEATURES,
    ADVANCED_EXECUTION_ROOM_DEFAULTS,
    CARD_RESOURCE,
    CONF_ADVANCED_MODE,
    CONF_ADVANCED_FEATURES,
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
    DEFAULT_ALLOW_AUTOMATIC_REVERSE,
    DAY_WINDOW_FIXED,
    DAY_WINDOW_OPTIONS,
    DEFAULT_EVALUATION_INTERVAL,
    DEFAULT_EXTERNAL_MOVEMENT_DETECTION,
    DEFAULT_EVENING_RELEASE_TIME,
    DEFAULT_OPENING_ORDER,
    DEFAULT_MOVEMENT_SECONDS,
    DEFAULT_POSITION_TOLERANCE,
    DEFAULT_SAFETY_BYPASSES_STAGGER,
    DEFAULT_SOURCE_STALE_SECONDS,
    DEFAULT_SETTLING_SECONDS,
    DEFAULT_STAGGER_SECONDS,
    DEFAULT_STAGGER_SCOPE,
    DEFAULT_SUNSET_OFFSET_MINUTES,
    DEFAULT_SUN_ENTITY,
    DEFAULT_TILT_TOLERANCE,
    DEFAULT_VERIFICATION_RETRIES,
    DEFAULT_WINDOW_RETURNS_TO_AUTOMATION,
    DIAGNOSTIC_OFF,
    DIAGNOSTIC_OPTIONS,
    DEVICE_BINARY,
    DEVICE_CURTAIN,
    DEVICE_ROLLER,
    DEVICE_SCREEN,
    DEVICE_TYPES,
    DEVICE_VERTICAL,
    DEVICE_VENETIAN,
    FEEDBACK_QUALITY_OPTIONS,
    DIRECTION_CUSTOM,
    DIRECTION_OPTIONS,
    DIRECTION_PRESETS,
    DOMAIN,
    FEATURE_CONDITIONS,
    FEATURE_EXPERT_EXECUTION,
    FEATURE_GLARE_PROTECTION,
    FEATURE_MAXIMUM_OPENING,
    FEATURE_NIGHT,
    FEATURE_SAFETY,
    FEATURE_SCHEDULE,
    FEATURE_TEMPERATURE,
    FEATURE_TEST_TOOLS,
    OUTSIDE_OPEN,
    OUTSIDE_OPTIONS,
    OUTDOOR_MINIMUM_MAX_C,
    OUTDOOR_MINIMUM_MIN_C,
    OUTDOOR_MINIMUM_STEP_C,
    OPENING_ORDER_OPTIONS,
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
    STAGGER_SCOPE_OPTIONS,
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
from .decision import (
    ProtectedZone,
    ProtectedZoneStatus,
    SunGeometry,
    evaluate_protected_zone,
    validate_protected_zone,
)
from .logic import azimuth_inside, parse_numeric_value
from .options_navigation import (
    build_cover_routes,
    build_group_routes,
    build_main_room_routes,
    build_protected_zone_routes,
    build_room_routes,
    build_sector_routes,
    build_structure_routes,
    night_is_configured,
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
    "sun_preset": {"low": "Nur starke Sonne", "medium": "Ausgewogen", "high": "Früher beschatten", "custom": "Benutzerdefiniert", "keep_current": "Bestehendes Lux-Profil beibehalten"},
    "sun_source": {"geometry": "Nur Sonnenstand", "lux": "Fassadenbezogener Außensensor (empfohlen)", "external": "Externer Ein/Aus-Sensor"},
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
    "feedback_quality": {"trusted": "Vertrauenswürdige Positionsrückmeldung", "intermediate": "Zwischenpositions-Rückmeldung", "end_positions": "Nur Endpositions-Rückmeldung", "none": "Keine nutzbare Positionsrückmeldung"},
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
    "sun_preset": {"low": "Strong sunlight only", "medium": "Balanced", "high": "Shade earlier", "custom": "Custom", "keep_current": "Keep existing Lux profile"},
    "sun_source": {"geometry": "Sun position only", "lux": "Facade-related outdoor sensor (recommended)", "external": "External on/off sensor"},
    "tilt_preset": {"glare": "More glare protection", "balanced": "Balanced", "daylight": "More daylight", "custom": "Custom"},
    "device_type": {"venetian": "Exterior venetian blind", "roller_shutter": "Roller shutter", "exterior_screen": "Exterior / zip screen", "curtain": "Interior curtain", "vertical_blind": "Vertical blind", "awning": "Awning", "binary_cover": "Simple open/close cover"},
    "schedule_profile": {"year_round": "Automatic all year", "summer": "Summer season (May–September)", "custom": "Custom schedule"},
    "day_window": {"fixed_time": "Fixed time", "all_day": "All day"},
    "outside_schedule_behavior": {"open": "Move to neutral/open position", "hold": "Keep current position"},
    "feedback_policy": {"send": "Send command", "skip": "Do not send without feedback"},
    "feedback_quality": {"trusted": "Trusted position feedback", "intermediate": "Intermediate position feedback", "end_positions": "End-position feedback only", "none": "No usable position feedback"},
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
                self._zone_id = route.get("zone_id")
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
                    self._zone_id = None
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
                "zone_id",
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

    def _advanced_features(self, room: dict[str, Any] | None = None) -> set[str]:
        """Return the customer's selected optional capabilities for a room."""
        selected = (room or self.room()).get(CONF_ADVANCED_FEATURES, [])
        return {
            str(feature)
            for feature in selected
            if str(feature) in ADVANCED_FEATURES
        }

    def _feature_enabled(self, feature: str, room: dict[str, Any] | None = None) -> bool:
        return feature in self._advanced_features(room)

    def _room_supports_glare_protection(
        self, room: dict[str, Any] | None = None
    ) -> bool:
        """Return whether the room has an individually usable glare cover."""
        selected_room = room or self.room()
        return any(
            self._protected_zone_calculation_mode(
                str(layer.get("profile") or "")
            )
            and any(
                str(cover.get("entity") or "").strip()
                for cover in layer.get("covers", [])
                if isinstance(cover, dict)
            )
            for sector in selected_room.get("sectors", [])
            if isinstance(sector, dict)
            for layer in sector.get("layers", [])
            if isinstance(layer, dict)
        )

    def _room_supports_maximum_opening(
        self, room: dict[str, Any] | None = None
    ) -> bool:
        """Return whether at least one configured cover supports a position."""
        selected_room = room or self.room()
        return any(
            profile_supports_position(str(layer.get("profile") or ""))
            and any(
                str(cover.get("entity") or "").strip()
                for cover in layer.get("covers", [])
                if isinstance(cover, dict)
            )
            for sector in selected_room.get("sectors", [])
            if isinstance(sector, dict)
            for layer in sector.get("layers", [])
            if isinstance(layer, dict)
        )

    def _available_optional_features(
        self, room: dict[str, Any] | None = None
    ) -> set[str]:
        """Return optional features made possible by the current structure."""
        selected_room = room or self.room()
        available: set[str] = set()
        if self._room_supports_glare_protection(selected_room):
            available.add(FEATURE_GLARE_PROTECTION)
        if self._room_supports_maximum_opening(selected_room):
            available.add(FEATURE_MAXIMUM_OPENING)
        return available

    def _remember_optional_feature_availability(self) -> None:
        """Capture capabilities before one atomic structure change."""
        if self.advanced_mode and not getattr(self, "_initial_setup", False):
            self._features_before_structure_change = (
                self._available_optional_features()
            )

    async def _finish_structure_change(
        self, *, fallback: str
    ) -> ConfigFlowResult:
        """Show a one-time discovery page for newly possible features."""
        before = getattr(self, "_features_before_structure_change", None)
        self._features_before_structure_change = None
        if (
            self.advanced_mode
            and not getattr(self, "_initial_setup", False)
            and isinstance(before, set)
        ):
            selected = self._advanced_features()
            newly_available = sorted(
                self._available_optional_features() - before - selected
            )
            if newly_available:
                labels = self._feature_labels()
                self._new_available_features = newly_available
                self._new_feature_return_step = fallback
                self._new_available_feature_labels = ", ".join(
                    labels.get(feature, feature)
                    for feature in newly_available
                )
                return await self.async_step_new_optional_feature_available()
        return await getattr(self, f"async_step_{fallback}")()

    async def async_step_new_optional_feature_available(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Explain a capability unlocked by a newly added cover profile."""
        if user_input is not None:
            open_features = bool(
                user_input.get("open_optional_features", False)
            )
            return_step = str(
                getattr(self, "_new_feature_return_step", None) or "room_hub"
            )
            self._new_feature_return_step = None
            self._new_available_features = []
            if open_features:
                return await self.async_step_choose_advanced_features()
            return await getattr(self, f"async_step_{return_step}")()
        return self.async_show_form(
            step_id="new_optional_feature_available",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "open_optional_features", default=True
                    ): selector.BooleanSelector()
                }
            ),
            description_placeholders={
                **self._option_placeholders(),
                "new_features": str(
                    getattr(
                        self,
                        "_new_available_feature_labels",
                        "",
                    )
                ),
            },
        )

    def _feature_labels(self) -> dict[str, str]:
        """Keep the menu customer-facing even before a translation reload."""
        if self._is_german():
            return {
                FEATURE_SCHEDULE: "Zeitplan",
                FEATURE_TEMPERATURE: "Temperatur & Hitzeschutz",
                FEATURE_NIGHT: "Nachtfunktion",
                FEATURE_SAFETY: "Sicherheit für Wind, Frost und Fenster",
                FEATURE_CONDITIONS: "Wetter & Anwesenheit",
                FEATURE_GLARE_PROTECTION: "Blendschutz für Bereich oder Objekt",
                FEATURE_MAXIMUM_OPENING: "Maximale Öffnungsbegrenzung",
                FEATURE_TEST_TOOLS: "Test & Vorschau",
                FEATURE_EXPERT_EXECUTION: "Experteneinstellungen für Fahrbefehle",
            }
        return {
            FEATURE_SCHEDULE: "Schedule",
            FEATURE_TEMPERATURE: "Temperature & heat protection",
            FEATURE_NIGHT: "Night mode",
            FEATURE_SAFETY: "Wind, frost and window safety",
            FEATURE_CONDITIONS: "Weather & occupancy",
            FEATURE_GLARE_PROTECTION: "Glare protection for an area or object",
            FEATURE_MAXIMUM_OPENING: "Maximum opening limit",
            FEATURE_TEST_TOOLS: "Test & preview",
            FEATURE_EXPERT_EXECUTION: "Expert command settings",
        }

    def _feature_context_placeholders(
        self, feature: str
    ) -> dict[str, str]:
        """Identify the current feature and its place in initial setup."""
        german = self._is_german()
        labels = self._feature_labels()
        descriptions_de = {
            FEATURE_SCHEDULE: (
                "Der allgemeine Beschattungszeitplan gibt alle automatischen "
                "Tagesfunktionen frei. Die Nachtfunktion arbeitet unabhängig."
            ),
            FEATURE_TEMPERATURE: (
                "Temperaturstufen wirken nur im allgemeinen "
                "Beschattungszeitplan. Hitzeschutz startet höchstens einmal "
                "pro Tag und endet an der frühesten Abendfreigabe."
            ),
            FEATURE_NIGHT: (
                "Die Nachtfunktion besitzt einen eigenen Zeitraum und kann "
                "dadurch ganzjährig unabhängig vom Beschattungszeitplan arbeiten."
            ),
            FEATURE_SAFETY: (
                "Sicherheitsquellen verhindern unsichere Bewegungen oder "
                "fordern die festgelegte sichere Position an."
            ),
            FEATURE_CONDITIONS: (
                "Optionale Wetter- und Anwesenheitsquellen ergänzen die "
                "Tagesautomatik. Leere Quellen haben keine Wirkung."
            ),
            FEATURE_GLARE_PROTECTION: (
                "Der Blendschutz berechnet für einen einzelnen Behang die "
                "offenste Position, die den eingemessenen Bereich vor direkter Sonne schützt."
            ),
            FEATURE_MAXIMUM_OPENING: (
                "Die harte Öffnungsgrenze korrigiert auch externe Fahrten "
                "oberhalb des Grenzwerts. Nur Sicherheitsfahrten haben Vorrang."
            ),
            FEATURE_TEST_TOOLS: (
                "Vorschau und Simulation erklären Entscheidungen, bewegen "
                "aber niemals einen Behang."
            ),
            FEATURE_EXPERT_EXECUTION: (
                "Diese technischen Einstellungen verändern Fahrabstände und "
                "Zielprüfung, aktivieren aber keine zusätzliche Beschattungsfunktion."
            ),
        }
        descriptions_en = {
            FEATURE_SCHEDULE: (
                "The general shading schedule enables every automatic daytime "
                "function. Night Mode operates independently."
            ),
            FEATURE_TEMPERATURE: (
                "Temperature stages operate only inside the general shading "
                "schedule. Heat protection starts at most once per day and "
                "ends at the earliest evening release."
            ),
            FEATURE_NIGHT: (
                "Night Mode has its own time source and can therefore operate "
                "year-round independently of the shading schedule."
            ),
            FEATURE_SAFETY: (
                "Safety sources prevent unsafe movement or request the "
                "configured safe position."
            ),
            FEATURE_CONDITIONS: (
                "Optional weather and occupancy sources complement daytime "
                "automation. Empty sources have no effect."
            ),
            FEATURE_GLARE_PROTECTION: (
                "Glare protection calculates the most open safe target for "
                "one physical cover and one measured protected area."
            ),
            FEATURE_MAXIMUM_OPENING: (
                "The hard opening limit also corrects external movement above "
                "the configured maximum. Only safety movement has priority."
            ),
            FEATURE_TEST_TOOLS: (
                "Preview and simulation explain decisions but never move a cover."
            ),
            FEATURE_EXPERT_EXECUTION: (
                "These technical settings control command spacing and target "
                "verification; they do not enable another shading function."
            ),
        }
        queue = self._initial_feature_queue()
        index = int(getattr(self, "_initial_feature_index", 0))
        initial = bool(getattr(self, "_initial_setup", False) and feature in queue)
        context = (
            (
                f"Zusatzfunktion {index + 1} von {len(queue)}"
                if german
                else f"Additional feature {index + 1} of {len(queue)}"
            )
            if initial
            else ("Einstellungen" if german else "Settings")
        )
        next_label = (
            labels.get(queue[index + 1], queue[index + 1])
            if initial and index + 1 < len(queue)
            else ""
        )
        next_text = (
            (
                f"Als Nächstes: {next_label}."
                if german
                else f"Next: {next_label}."
            )
            if next_label
            else (
                "Danach wird die Raumeinrichtung abgeschlossen."
                if initial and german
                else "The room setup will be completed afterwards."
                if initial
                else ""
            )
        )
        return {
            **self._option_placeholders(),
            "feature_name": labels.get(feature, feature),
            "feature_context": context,
            "feature_progress": context,
            "feature_description": (
                descriptions_de if german else descriptions_en
            ).get(feature, ""),
            "next_feature": next_text,
        }

    def _initial_feature_queue(self) -> list[str]:
        """Return selected features in the order customers configure them."""
        queued = getattr(self, "_queued_feature_setup", None)
        if isinstance(queued, list):
            return list(queued)
        selected = self._advanced_features()
        return [
            feature
            for feature in ADVANCED_FEATURES
            if feature in selected and feature != FEATURE_TEST_TOOLS
        ]

    async def _start_initial_feature_sequence(self) -> ConfigFlowResult:
        """Start a linear first-time setup for the selected room features."""
        self._initial_feature_index = 0
        return await self.async_step_configure_next_advanced_feature()

    async def _complete_initial_feature(self) -> ConfigFlowResult:
        """Advance exactly once after a selected feature was configured."""
        self._initial_feature_index = int(
            getattr(self, "_initial_feature_index", 0)
        ) + 1
        return await self.async_step_configure_next_advanced_feature()

    async def _finish_feature_step(self) -> ConfigFlowResult:
        """Continue initial setup or return later edits to the room."""
        if getattr(self, "_initial_setup", False):
            return await self._complete_initial_feature()
        return await self.async_step_room_hub()

    async def async_step_complete_initial_feature(
        self, user_input=None
    ) -> ConfigFlowResult:
        """Public continuation used by nested feature forms."""
        return await self._complete_initial_feature()

    async def async_step_configure_next_advanced_feature(
        self, user_input=None
    ) -> ConfigFlowResult:
        """Open the next selected feature without an intermediate menu."""
        queue = self._initial_feature_queue()
        index = int(getattr(self, "_initial_feature_index", 0))
        if index >= len(queue):
            self._queued_feature_setup = None
            return await self.async_step_after_room()
        feature = queue[index]
        handlers = {
            FEATURE_SCHEDULE: "manage_schedule",
            FEATURE_TEMPERATURE: "manage_temperature",
            FEATURE_NIGHT: "manage_night",
            FEATURE_SAFETY: "manage_safety",
            FEATURE_CONDITIONS: "manage_weather_conditions",
            FEATURE_GLARE_PROTECTION: "initial_glare_protection",
            FEATURE_MAXIMUM_OPENING: "initial_maximum_opening",
            FEATURE_EXPERT_EXECUTION: "manage_execution",
        }
        handler = handlers.get(feature)
        if handler is None:
            return await self._complete_initial_feature()
        return await getattr(self, f"async_step_{handler}")()

    async def async_step_advanced_features_hub(self, user_input=None):
        """Show only features the customer selected for this room."""
        if not self.advanced_mode:
            return await self.async_step_room_hub()
        labels = self._feature_labels()
        selected = self._advanced_features()
        menu_options = {
            "choose_advanced_features": (
                "Funktionen auswählen" if self._is_german() else "Choose features"
            ),
        }
        if FEATURE_SCHEDULE in selected:
            menu_options["manage_schedule"] = labels[FEATURE_SCHEDULE]
        if FEATURE_TEMPERATURE in selected:
            menu_options["manage_temperature"] = labels[FEATURE_TEMPERATURE]
        if FEATURE_NIGHT in selected:
            menu_options["manage_night"] = labels[FEATURE_NIGHT]
        if FEATURE_SAFETY in selected:
            menu_options["manage_safety"] = labels[FEATURE_SAFETY]
        if FEATURE_CONDITIONS in selected:
            menu_options["manage_weather_conditions"] = labels[
                FEATURE_CONDITIONS
            ]
        if FEATURE_GLARE_PROTECTION in selected:
            menu_options["glare_protection_hub"] = labels[
                FEATURE_GLARE_PROTECTION
            ]
        if FEATURE_MAXIMUM_OPENING in selected:
            menu_options["maximum_opening_hub"] = labels[
                FEATURE_MAXIMUM_OPENING
            ]
        if FEATURE_EXPERT_EXECUTION in selected:
            menu_options["manage_execution"] = labels[
                FEATURE_EXPERT_EXECUTION
            ]
        menu_options["manage_pause"] = (
            "Pause und manuelle Bedienung"
            if self._is_german()
            else "Pause and manual control"
        )
        menu_options["back_to_room"] = "Zurück zum Raum" if self._is_german() else "Back to room"
        return self.async_show_menu(
            step_id="advanced_features_hub",
            menu_options=menu_options,
            description_placeholders={
                **self._option_placeholders(),
                "active_features": str(len(selected)),
            },
        )

    async def async_step_choose_advanced_features(self, user_input=None):
        """Let a customer opt into Advanced capabilities before configuration."""
        if not self.advanced_mode:
            return await self.async_step_room_hub()
        room = self.room()
        selected = self._advanced_features(room)
        glare_available = self._room_supports_glare_protection(room)
        maximum_opening_available = self._room_supports_maximum_opening(room)
        if user_input is not None:
            previously_selected = set(selected)
            selected_features = [
                feature
                for feature in ADVANCED_FEATURES
                if user_input.get(feature, False)
                and (
                    feature != FEATURE_GLARE_PROTECTION
                    or glare_available
                )
                and (
                    feature != FEATURE_MAXIMUM_OPENING
                    or maximum_opening_available
                )
            ]
            room[CONF_ADVANCED_FEATURES] = selected_features
            # A feature choice controls behaviour, not just which form happens
            # to be visible.  Clearing the optional source is intentional: a
            # later re-enable returns to its focused setup page instead of
            # leaving an invisible automatic rule active in the room.
            selected_set = set(selected_features)
            if FEATURE_SCHEDULE not in selected_set:
                room["schedule_enabled"] = False
            else:
                room["schedule_enabled"] = True
            if FEATURE_TEMPERATURE not in selected_set:
                room["indoor_temperature"] = ""
            if FEATURE_NIGHT not in selected_set:
                room["night_enabled"] = False
            else:
                room["night_enabled"] = True
            if FEATURE_SAFETY not in selected_set:
                room["safety_blockers"] = []
            if FEATURE_CONDITIONS not in selected_set:
                for key in (
                    "irradiance_sensor",
                    "cloud_cover_sensor",
                    "weather_permission",
                    "occupancy_sensor",
                    "glare_sensor",
                ):
                    room[key] = ""
            if FEATURE_MAXIMUM_OPENING not in selected_set:
                for sector in room.get("sectors", []):
                    for layer in sector.get("layers", []):
                        for cover in layer.get("covers", []):
                            cover["enforce_max_open_position"] = False
            # These tools create entities, so an Options-flow save/reload is
            # required before Home Assistant can add or remove them.
            if getattr(self, "_initial_setup", False):
                return await self._start_initial_feature_sequence()
            newly_enabled = [
                feature
                for feature in ADVANCED_FEATURES
                if feature in selected_set
                and feature not in previously_selected
                and feature != FEATURE_TEST_TOOLS
            ]
            if newly_enabled:
                # A later feature selection is a setup request, not merely a
                # visibility toggle. Guide the customer through only the
                # newly enabled features before returning to the room.
                self._queued_feature_setup = newly_enabled
                self._initial_setup = True
                return await self._start_initial_feature_sequence()
            return await self.async_step_advanced_features_hub()
        fields = {
            vol.Required(feature, default=feature in selected): selector.BooleanSelector()
            for feature in ADVANCED_FEATURES
            if (
                feature != FEATURE_GLARE_PROTECTION
                or glare_available
                or feature in selected
            )
            and (
                feature != FEATURE_MAXIMUM_OPENING
                or maximum_opening_available
                or feature in selected
            )
        }
        return self.async_show_form(
            step_id="choose_advanced_features",
            data_schema=vol.Schema(fields),
            description_placeholders=self._option_placeholders(),
        )


    def _is_german(self) -> bool:
        return (getattr(self.hass.config, "language", "en") or "en").lower().startswith("de")

    def _menu(self, options: list[str]) -> dict[str, str]:
        labels = MENU_LABELS_DE if self._is_german() else MENU_LABELS_EN
        return {option: labels.get(option, option.replace("_", " ").title()) for option in options}

    def _choice(self, options: list[str], key: str, *, multiple: bool = False):
        if (
            key in {"sun_preset", "tilt_preset", "schedule_profile"}
            and self.advanced_mode
            and not multiple
        ):
            profile_labels = self._advanced_profile_labels(key)
            if profile_labels:
                return selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {
                                "value": str(option),
                                "label": profile_labels.get(
                                    str(option), str(option)
                                ),
                            }
                            for option in options
                        ],
                        mode="dropdown",
                    )
                )
        return _select(options, key, multiple=multiple)

    def _advanced_profile_labels(self, key: str) -> dict[str, str]:
        """Expose concrete preset values in Advanced choices, never in Easy."""
        german = self._is_german()
        base = SELECT_LABELS_DE if german else SELECT_LABELS_EN
        if key == "sun_preset":
            labels = dict(base[key])
            for preset, values in SUN_PRESETS.items():
                on_lux = int(values["sun_on_lux"])
                off_lux = int(values["sun_off_lux"])
                on_delay = values["sun_on_delay"]
                off_delay = values["sun_off_delay"]
                lux = f"{on_lux:,}/{off_lux:,}"
                if german:
                    lux = lux.replace(",", ".")
                labels[preset] = (
                    f"{labels[preset]} · {lux} lx · "
                    f"{on_delay:g}/{off_delay:g} min"
                )
            return labels
        if key == "tilt_preset":
            labels = dict(base[key])
            for preset, curve in TILT_CURVE_PRESETS.items():
                values = " · ".join(
                    f"{point['elevation']:g}°/{point['tilt']:g}%"
                    for point in curve
                )
                labels[preset] = f"{labels[preset]} · {values}"
            return labels
        if key == "schedule_profile":
            labels = dict(base[key])
            labels[SCHEDULE_YEAR_ROUND] = (
                "Ganzjährig · Januar–Dezember · Montag–Sonntag"
                if german
                else "All year · January–December · Monday–Sunday"
            )
            labels[SCHEDULE_SUMMER] = (
                "Sommersaison · Mai–September · Montag–Sonntag"
                if german
                else "Summer season · May–September · Monday–Sunday"
            )
            return labels
        return {}

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

    def protected_zones(self) -> list[dict[str, Any]]:
        """Return Advanced protected zones, assigning missing stable IDs once."""
        sector = self.sector()
        raw_zones = sector.get("protected_zones", [])
        if not isinstance(raw_zones, list):
            raw_zones = []
        zones: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for index, raw_zone in enumerate(raw_zones):
            if not isinstance(raw_zone, dict):
                continue
            zone = raw_zone
            zone_id = str(zone.get("id") or "").strip()
            if not zone_id or zone_id in seen_ids:
                zone_id = _new_id(
                    str(zone.get("name") or f"protected_zone_{index + 1}")
                )
                zone["id"] = zone_id
            seen_ids.add(zone_id)
            zone["sector_id"] = str(sector.get("id") or "")
            zones.append(zone)
        sector["protected_zones"] = zones
        return zones

    def protected_zone(self) -> dict[str, Any]:
        """Return the protected zone selected by its stable route identity."""
        return next(
            zone for zone in self.protected_zones()
            if zone["id"] == self._zone_id
        )

    @staticmethod
    def _protected_zone_calculation_mode(profile: str) -> str:
        """Return the supported object-protection calculation for a profile."""
        return {
            DEVICE_ROLLER: "top_down",
            DEVICE_SCREEN: "top_down",
            DEVICE_CURTAIN: "curtain",
            DEVICE_BINARY: "binary",
            DEVICE_VERTICAL: "vertical_slats",
        }.get(str(profile), "")

    def _protected_zone_covers(self) -> dict[str, dict[str, Any]]:
        """Return individually addressable covers supported by the calculator."""
        covers: dict[str, dict[str, Any]] = {}
        for layer in self.sector().get("layers", []):
            if not isinstance(layer, dict):
                continue
            profile = str(layer.get("profile") or "")
            if not self._protected_zone_calculation_mode(profile):
                continue
            for cover in layer.get("covers", []):
                if not isinstance(cover, dict):
                    continue
                entity_id = str(cover.get("entity") or "").strip()
                if entity_id:
                    covers[entity_id] = {
                        "cover": cover,
                        "layer": layer,
                        "profile": profile,
                    }
        return covers

    def _protected_zone_cover_selector(self):
        """Build a single-cover selector from the current sector."""
        german = self._is_german()
        options = [
            {
                "value": entity_id,
                "label": str(
                    details["cover"].get("name")
                    or self._friendly_name(
                        entity_id,
                        "Behang" if german else "Cover",
                    )
                ),
            }
            for entity_id, details in self._protected_zone_covers().items()
        ]
        return selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=options,
                mode="dropdown",
                multiple=False,
            )
        )

    def _protected_zone_form_sections(
        self,
        zone: dict[str, Any],
        *,
        include_maintenance: bool,
    ) -> dict[Any, Any]:
        """Return the shared Advanced protected-zone form contract."""
        available_covers = self._protected_zone_covers()
        selected_cover = str(zone.get("cover_entity") or "")
        if selected_cover not in available_covers:
            # Never guess when converting a legacy group-scoped zone: the
            # customer must explicitly identify the one physical cover.
            selected_cover = (
                ""
                if include_maintenance and zone
                else next(iter(available_covers), "")
            )

        def _stored_number(key: str, fallback: float) -> float:
            try:
                value = float(zone.get(key, fallback))
            except (TypeError, ValueError):
                return fallback
            return value if math.isfinite(value) else fallback

        legacy_lower = _stored_number("lower_height_m", 0.75)
        legacy_upper = _stored_number("upper_height_m", 1.25)
        object_center = _stored_number(
            "object_center_height_m",
            (legacy_lower + legacy_upper) / 2.0,
        )
        object_height = _stored_number(
            "object_height_m",
            max(0.01, legacy_upper - legacy_lower),
        )
        identity = {
            vol.Required(
                "name",
                default=zone.get(
                    "name",
                    "Schutzzone" if self._is_german() else "Protected zone",
                ),
            ): selector.TextSelector(),
            vol.Required(
                "cover_entity", default=selected_cover
            ): self._protected_zone_cover_selector(),
        }
        if include_maintenance:
            identity[
                vol.Required(
                    "enabled", default=bool(zone.get("enabled", True))
                )
            ] = selector.BooleanSelector()
        window = {
            vol.Required(
                "window_width_m",
                default=_stored_number("window_width_m", 1.2),
            ): _number(0.1, 30, 0.01, "m", mode="box"),
            vol.Required(
                "window_height_m",
                default=_stored_number("window_height_m", 2.0),
            ): _number(0.1, 15, 0.01, "m", mode="box"),
            vol.Required(
                "window_sill_height_m",
                default=_stored_number("window_sill_height_m", 0.8),
            ): _number(0, 10, 0.01, "m", mode="box"),
        }
        protected_object = {
            vol.Required(
                "object_distance_m",
                default=_stored_number(
                    "object_distance_m",
                    _stored_number("distance_m", 1.0),
                ),
            ): _number(0.1, 30, 0.01, "m", mode="box"),
            vol.Required(
                "object_center_height_m", default=object_center
            ): _number(0, 10, 0.01, "m", mode="box"),
            vol.Required(
                "object_height_m", default=object_height
            ): _number(0.01, 10, 0.01, "m", mode="box"),
            vol.Required(
                "object_lateral_center_m",
                default=_stored_number(
                    "object_lateral_center_m",
                    _stored_number("target_lateral_center_m", 0.0),
                ),
            ): _number(-30, 30, 0.01, "m", mode="box"),
            vol.Required(
                "object_width_m",
                default=_stored_number(
                    "object_width_m",
                    _stored_number("target_lateral_width_m", 0.5),
                ),
            ): _number(0.01, 30, 0.01, "m", mode="box"),
        }
        sections: dict[Any, Any] = {
            vol.Required("protected_zone_identity"): section(
                vol.Schema(identity), {"collapsed": False}
            ),
            vol.Required("protected_zone_window"): section(
                vol.Schema(window),
                {"collapsed": False},
            ),
            vol.Required("protected_zone_object"): section(
                vol.Schema(protected_object),
                {"collapsed": False},
            ),
        }
        if include_maintenance:
            sections[vol.Required("protected_zone_maintenance")] = section(
                vol.Schema(
                    {
                        vol.Required(
                            "delete_protected_zone", default=False
                        ): selector.BooleanSelector()
                    }
                ),
                {"collapsed": True},
            )
        return sections

    def _validated_protected_zone_values(
        self, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, dict[str, str]]:
        """Validate and normalize only fields consumed by the zone pipeline."""
        errors: dict[str, str] = {}
        name = str(values.get("name") or "").strip()
        if not name:
            errors["base"] = "protected_zone_name_required"

        cover_entity = str(values.get("cover_entity") or "").strip()
        available_covers = self._protected_zone_covers()
        if not cover_entity:
            errors["base"] = "protected_zone_cover_required"
        elif cover_entity not in available_covers:
            errors["base"] = "protected_zone_cover_invalid"

        def _number_value(key: str) -> tuple[float | None, bool]:
            value = values.get(key)
            if value in (None, ""):
                return None, True
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None, False
            return (number, True) if math.isfinite(number) else (None, False)

        window_width_m, window_width_valid = _number_value("window_width_m")
        window_height_m, window_height_valid = _number_value(
            "window_height_m"
        )
        window_sill_height_m, window_sill_valid = _number_value(
            "window_sill_height_m"
        )
        if (
            not window_width_valid
            or not window_height_valid
            or not window_sill_valid
            or window_width_m is None
            or window_height_m is None
            or window_sill_height_m is None
            or not 0.1 <= window_width_m <= 30
            or not 0.1 <= window_height_m <= 15
            or not 0 <= window_sill_height_m <= 10
            or window_sill_height_m + window_height_m > 15
        ):
            errors["base"] = "protected_zone_window_geometry_range"

        object_distance_m, object_distance_valid = _number_value(
            "object_distance_m"
        )
        object_center_height_m, object_center_valid = _number_value(
            "object_center_height_m"
        )
        object_height_m, object_height_valid = _number_value(
            "object_height_m"
        )
        object_lateral_center_m, object_lateral_valid = _number_value(
            "object_lateral_center_m"
        )
        object_width_m, object_width_valid = _number_value(
            "object_width_m"
        )
        if (
            not object_distance_valid
            or not object_center_valid
            or not object_height_valid
            or not object_lateral_valid
            or not object_width_valid
            or object_distance_m is None
            or object_center_height_m is None
            or object_height_m is None
            or object_lateral_center_m is None
            or object_width_m is None
            or not 0.1 <= object_distance_m <= 30
            or not 0 <= object_center_height_m <= 10
            or not 0.01 <= object_height_m <= 10
            or object_center_height_m - object_height_m / 2.0 < 0
            or object_center_height_m + object_height_m / 2.0 > 15
            or not -30 <= object_lateral_center_m <= 30
            or not 0.01 <= object_width_m <= 30
        ):
            errors["base"] = "protected_zone_object_geometry_range"

        profile = str(
            available_covers.get(cover_entity, {}).get("profile") or ""
        )
        calculation_mode = self._protected_zone_calculation_mode(profile)
        if cover_entity and not calculation_mode:
            errors["base"] = "protected_zone_profile_not_supported"

        if errors:
            return None, errors

        lower_height_m = (
            float(object_center_height_m) - float(object_height_m) / 2.0
        )
        upper_height_m = (
            float(object_center_height_m) + float(object_height_m) / 2.0
        )
        result: dict[str, Any] = {
            "name": name,
            "enabled": bool(values.get("enabled", True)),
            "sector_id": str(self.sector().get("id") or ""),
            "cover_entity": cover_entity,
            "distance_m": float(object_distance_m),
            "lower_height_m": lower_height_m,
            "upper_height_m": upper_height_m,
            "calculation_mode": calculation_mode,
            "window_width_m": float(window_width_m),
            "window_height_m": float(window_height_m),
            "window_sill_height_m": float(window_sill_height_m),
            "object_distance_m": float(object_distance_m),
            "object_center_height_m": float(object_center_height_m),
            "object_height_m": float(object_height_m),
            "object_lateral_center_m": float(object_lateral_center_m),
            "object_width_m": float(object_width_m),
            "target_lateral_center_m": float(object_lateral_center_m),
            "target_lateral_width_m": float(object_width_m),
        }
        return result, errors

    def _protected_zone_preview(
        self, zone_values: dict[str, Any]
    ) -> dict[str, str]:
        """Return a customer-readable live calculation check for one zone."""
        german = self._is_german()
        sector = self.sector()
        candidate = {
            "id": str(zone_values.get("id") or "preview"),
            **zone_values,
        }
        zone = ProtectedZone.from_config(
            candidate, sector_id=str(sector.get("id") or "")
        )
        validation = validate_protected_zone(zone)
        sun = self.hass.states.get(DEFAULT_SUN_ENTITY)
        azimuth = parse_numeric_value(
            sun.attributes.get("azimuth") if sun else None
        )
        elevation = parse_numeric_value(
            sun.attributes.get("elevation") if sun else None
        )
        start = parse_numeric_value(sector.get("azimuth_start"))
        end = parse_numeric_value(sector.get("azimuth_end"))
        minimum = parse_numeric_value(sector.get("elevation_min")) or 0.0
        geometry_active = bool(
            sun
            and sun.state == "above_horizon"
            and azimuth is not None
            and elevation is not None
            and start is not None
            and end is not None
            and azimuth_inside(azimuth, start, end)
            and elevation >= minimum
        )
        source = sun_source_for_sector(sector, advanced=True)
        confirmed = geometry_active
        if source == "external":
            entity_id = str(sector.get(CONF_SUN_PRESENCE_ENTITY) or "")
            confirmed = bool(
                geometry_active
                and entity_id
                and self.hass.states.is_state(entity_id, "on")
            )
        elif source == "lux":
            entity_id = str(sector.get("lux_sensor") or "")
            state = self.hass.states.get(entity_id) if entity_id else None
            lux = parse_numeric_value(state.state if state else None)
            threshold = max(
                float(sector.get("sun_on_lux", 35000)),
                float(sector.get("sun_off_lux", 30000)),
            )
            confirmed = bool(
                geometry_active and lux is not None and lux >= threshold
            )
        facade = None
        explicit_facade = parse_numeric_value(sector.get("facade_azimuth"))
        if explicit_facade is not None:
            facade = explicit_facade % 360.0
        elif start is not None and end is not None:
            facade = (start + ((end - start) % 360.0) / 2.0) % 360.0
        geometry = SunGeometry(
            elevation_degrees=elevation,
            azimuth_degrees=azimuth,
            facade_azimuth_degrees=facade,
            window_lower_height_m=zone_values.get(
                "window_sill_height_m", 0.0
            ),
            window_upper_height_m=float(
                zone_values.get("window_sill_height_m", 0.0)
            )
            + float(zone_values.get("window_height_m", 0.0)),
            direct_sun=confirmed,
        )
        evaluation = evaluate_protected_zone(
            zone,
            geometry,
            sector_id=str(sector.get("id") or ""),
            cover_entity=str(zone_values.get("cover_entity") or ""),
        )

        if validation.status is not ProtectedZoneStatus.VALID:
            status = (
                "Berechnung nicht möglich"
                if german
                else "Calculation is not possible"
            )
        elif evaluation.status is ProtectedZoneStatus.HIT:
            status = (
                "Berechnung möglich · Schutzzone wird aktuell getroffen"
                if german
                else "Calculation ready · protected zone is currently hit"
            )
        else:
            status = (
                "Berechnung möglich · aktuell kein direkter Treffer"
                if german
                else "Calculation ready · no direct hit right now"
            )
        target_parts: list[str] = []
        if evaluation.target is not None:
            if evaluation.target.position is not None:
                target_parts.append(
                    (
                        "Position"
                        if german
                        else "Position"
                    )
                    + f" {evaluation.target.position:.0f} %"
                )
            if evaluation.target.tilt is not None:
                target_parts.append(
                    ("Lamelle" if german else "Tilt")
                    + f" {evaluation.target.tilt:.0f} %"
                )
        target = (
            " · ".join(target_parts)
            if target_parts
            else (
                "Kein aktuelles Fahrziel; die Zone wird bei passendem Sonnenstand neu berechnet."
                if german
                else "No current movement target; the zone is recalculated when the sun reaches it."
            )
        )
        sun_summary = (
            (
                f"Azimut {azimuth:.0f}° · Höhe {elevation:.0f}° · "
                + (
                    "direkte Sonne bestätigt"
                    if confirmed
                    else "keine bestätigte direkte Sonne"
                )
            )
            if german and azimuth is not None and elevation is not None
            else (
                f"Azimuth {azimuth:.0f}° · elevation {elevation:.0f}° · "
                + (
                    "direct sun confirmed"
                    if confirmed
                    else "no confirmed direct sun"
                )
            )
            if azimuth is not None and elevation is not None
            else (
                "Aktuelle Sonnenwerte nicht verfügbar"
                if german
                else "Current sun values are unavailable"
            )
        )
        geometry_summary = (
            (
                "Fenster "
                f"{float(zone_values['window_width_m']):.2f} × "
                f"{float(zone_values['window_height_m']):.2f} m ab "
                f"{float(zone_values['window_sill_height_m']):.2f} m · "
                "Objekt "
                f"{float(zone_values['object_distance_m']):.2f} m entfernt, "
                f"{float(zone_values['object_width_m']):.2f} × "
                f"{float(zone_values['object_height_m']):.2f} m"
            )
            if german
            else (
                "Window "
                f"{float(zone_values['window_width_m']):.2f} × "
                f"{float(zone_values['window_height_m']):.2f} m from "
                f"{float(zone_values['window_sill_height_m']):.2f} m · "
                "object "
                f"{float(zone_values['object_distance_m']):.2f} m away, "
                f"{float(zone_values['object_width_m']):.2f} × "
                f"{float(zone_values['object_height_m']):.2f} m"
            )
        )
        return {
            **self._option_placeholders(),
            "zone_name": str(zone_values.get("name") or ""),
            "calculation_status": status,
            "calculation_reason": str(evaluation.reason_code),
            "calculated_target": target,
            "current_sun": sun_summary,
            "geometry_summary": geometry_summary,
        }

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

    def _temperature_behavior_text(
        self, room: dict[str, Any] | None = None
    ) -> str:
        """Explain the actual temperature stages for this room's profiles."""
        profiles = self._room_profiles(room)
        has_venetian = DEVICE_VENETIAN in profiles
        has_other_profiles = bool(profiles - {DEVICE_VENETIAN})
        if self._is_german():
            if has_venetian and not has_other_profiles:
                return (
                    "Dieser Raum enthält nur horizontale Lamellen. Sie nutzen "
                    "eine sonnenstandsabhängige adaptive Normalbeschattung und "
                    "eine separate, stärkere Hitzeschutzstufe."
                )
            if has_venetian and has_other_profiles:
                return (
                    "Positionsbehänge wie Rollläden, Screens oder Vorhänge "
                    "wechseln zwischen Komfortbeschattung, stärkerem "
                    "Sonnenschutz und Hitzeschutz. Horizontale Lamellen fassen "
                    "Komfort- und Sonnenschutz zur adaptiven Normalbeschattung "
                    "zusammen und nutzen zusätzlich die stärkere "
                    "Hitzeschutzstufe."
                )
            return (
                "Die Behänge dieses Raums wechseln – soweit ihr Profil die "
                "Positionen unterstützt – zwischen leichter "
                "Komfortbeschattung, stärkerem Sonnenschutz und Hitzeschutz."
            )
        if has_venetian and not has_other_profiles:
            return (
                "This room contains only horizontal slats. They use one "
                "sun-position-dependent adaptive normal shading stage and a "
                "separate, stronger heat-protection stage."
            )
        if has_venetian and has_other_profiles:
            return (
                "Position-controlled covers such as rollers, screens or "
                "curtains move between comfort shading, stronger solar "
                "protection and heat protection. Horizontal slats combine "
                "comfort and solar protection into adaptive normal shading "
                "and add the stronger heat-protection stage."
            )
        return (
            "The covers in this room move, where supported by their profile, "
            "between light comfort shading, stronger solar protection and "
            "heat protection."
        )

    def _strip_easy_issue79_execution_fields(self) -> None:
        """Keep Advanced execution policies out of an Easy saved snapshot."""
        if self.advanced_mode:
            return
        for room in self.rooms:
            for key in ADVANCED_EXECUTION_ROOM_DEFAULTS:
                room.pop(key, None)
            for sector in room.get("sectors", []):
                for layer in sector.get("layers", []):
                    layer.pop("opening_order", None)
                    for cover in layer.get("covers", []):
                        cover.pop("allow_automatic_reverse", None)

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
        if self.advanced_mode and profile_supports_tilt(profile):
            layer["opening_order"] = DEFAULT_OPENING_ORDER
        return layer

    async def async_step_global_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Redirect stale forms after making Home Assistant Sun automatic."""
        self._working[CONF_SUN_ENTITY] = DEFAULT_SUN_ENTITY
        return await self.async_step_init()

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
        self._zone_id = None
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
                    "zone_id",
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
                    "zone_id",
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
        self._zone_id = None
        if getattr(self, "_initial_setup", False) and self.advanced_mode:
            menu_options: dict[str, str] = {}
            for route in build_structure_routes(
                self.room(), german=self._is_german()
            ):
                context = {
                    key: route[key]
                    for key in (
                        "room_id",
                        "sector_id",
                        "layer_id",
                        "cover_index",
                        "cover_entity",
                        "zone_id",
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
            menu_options["complete_initial_structure"] = (
                "Raumstruktur abschließen und Zusatzfunktionen auswählen"
                if self._is_german()
                else "Complete room structure and choose optional features"
            )
            return self.async_show_menu(
                step_id="initial_structure_hub",
                menu_options=menu_options,
                description_placeholders=self._option_placeholders(),
            )
        return self._room_object_menu(
            build_structure_routes(self.room(), german=self._is_german()),
            step_id="structure_hub",
            back_action="back_to_room",
            back_label="back_to_room",
        )

    async def async_step_initial_structure_hub(
        self, user_input=None
    ) -> ConfigFlowResult:
        """Keep the initial structure menu a valid Home Assistant flow step."""
        return await self.async_step_structure_hub(user_input)

    async def async_step_complete_initial_structure(
        self, user_input=None
    ) -> ConfigFlowResult:
        """Enter optional features only after the customer finishes structure."""
        if not getattr(self, "_initial_setup", False) or not self.advanced_mode:
            return await self.async_step_room_hub()
        return await self.async_step_choose_advanced_features()

    async def async_step_sector_hub(self, user_input=None) -> ConfigFlowResult:
        self._layer_id = None
        self._cover_index = None
        self._zone_id = None
        return self._room_object_menu(
            build_sector_routes(
                self.room(),
                self.sector(),
                german=self._is_german(),
                advanced=(
                    self.advanced_mode
                    and self._feature_enabled(FEATURE_GLARE_PROTECTION)
                ),
            ),
            step_id="sector_hub",
            back_action="back_to_structure",
            back_label="back_to_structure",
        )

    async def async_step_protected_zones_hub(
        self, user_input=None
    ) -> ConfigFlowResult:
        """List only the selected sector's Advanced protected zones."""
        if not self.advanced_mode or not self._feature_enabled(FEATURE_GLARE_PROTECTION):
            return await self.async_step_sector_hub()
        self._layer_id = None
        self._cover_index = None
        self._zone_id = None
        self.protected_zones()
        return self._room_object_menu(
            build_protected_zone_routes(
                self.room(), self.sector(), german=self._is_german()
            ),
            step_id="protected_zones_hub",
            back_action="back_to_sector",
            back_label="back_to_sector",
        )

    async def async_step_glare_protection_hub(
        self, user_input=None
    ) -> ConfigFlowResult:
        """List the room's sectors inside the selected glare feature."""
        routes = []
        for sector in self.room().get("sectors", []):
            zone_count = len(
                [
                    zone
                    for zone in sector.get("protected_zones", [])
                    if isinstance(zone, dict)
                ]
            )
            zone_label = (
                f"{zone_count} Zone"
                if self._is_german() and zone_count == 1
                else f"{zone_count} Zonen"
                if self._is_german()
                else f"{zone_count} zone"
                if zone_count == 1
                else f"{zone_count} zones"
            )
            routes.append(
                {
                    "label": f"{sector['name']} · {zone_label}",
                    "action": "protected_zones_hub",
                    "room_id": self.room()["id"],
                    "sector_id": sector["id"],
                }
            )
        return self._room_object_menu(
            routes,
            step_id="glare_protection_hub",
            back_action="back_to_room",
            back_label="back_to_room",
        )

    async def async_step_initial_glare_protection(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the first protected zone during the linear feature setup."""
        if not self._room_supports_glare_protection():
            return await self._complete_initial_feature()
        sectors = [
            sector
            for sector in self.room().get("sectors", [])
            if isinstance(sector, dict)
            and any(
                self._protected_zone_calculation_mode(
                    str(layer.get("profile") or "")
                )
                and any(
                    str(cover.get("entity") or "").strip()
                    for cover in layer.get("covers", [])
                    if isinstance(cover, dict)
                )
                for layer in sector.get("layers", [])
                if isinstance(layer, dict)
            )
        ]
        if not sectors:
            return await self._complete_initial_feature()
        if user_input is not None:
            self._sector_id = str(user_input["sector_id"])
        elif len(sectors) == 1:
            self._sector_id = str(sectors[0]["id"])
        else:
            return self.async_show_form(
                step_id="initial_glare_protection",
                data_schema=vol.Schema(
                    {
                        vol.Required("sector_id"): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=[
                                    {
                                        "value": str(sector["id"]),
                                        "label": str(sector["name"]),
                                    }
                                    for sector in sectors
                                ],
                                mode="dropdown",
                            )
                        )
                    }
                ),
                description_placeholders=self._option_placeholders(),
            )
        self._after_protected_zone_step = "complete_initial_feature"
        return await self.async_step_add_protected_zone()

    def _maximum_opening_covers(self) -> list[dict[str, Any]]:
        """Return stable context for every position-capable cover in a room."""
        result: list[dict[str, Any]] = []
        for sector in self.room().get("sectors", []):
            for layer in sector.get("layers", []):
                if not profile_supports_position(
                    str(layer.get("profile") or "")
                ):
                    continue
                for cover_index, cover in enumerate(layer.get("covers", [])):
                    if not str(cover.get("entity") or "").strip():
                        continue
                    result.append(
                        {
                            "sector": sector,
                            "layer": layer,
                            "cover": cover,
                            "cover_index": cover_index,
                        }
                    )
        return result

    async def async_step_initial_maximum_opening(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure the hard opening limit for each eligible cover."""
        covers = self._maximum_opening_covers()
        index = int(getattr(self, "_initial_maximum_cover_index", 0))
        if not covers or index >= len(covers):
            self._initial_maximum_cover_index = 0
            self._cover_index = None
            self._layer_id = None
            self._sector_id = None
            return await self._complete_initial_feature()
        context = covers[index]
        self._sector_id = str(context["sector"]["id"])
        self._layer_id = str(context["layer"]["id"])
        self._cover_index = int(context["cover_index"])
        cover = context["cover"]
        if user_input is not None:
            cover["enforce_max_open_position"] = bool(
                user_input.get("enforce_max_open_position", False)
            )
            cover["max_open_position"] = float(
                user_input.get(
                    "max_open_position",
                    cover.get("max_open_position", 100.0),
                )
            )
            self._initial_maximum_cover_index = index + 1
            return await self.async_step_initial_maximum_opening()
        return self.async_show_form(
            step_id="initial_maximum_opening",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "enforce_max_open_position",
                        default=cover.get(
                            "enforce_max_open_position", False
                        ),
                    ): selector.BooleanSelector(),
                    vol.Required(
                        "max_open_position",
                        default=cover.get("max_open_position", 100.0),
                    ): _number(0, 100, 1, "%"),
                }
            ),
            description_placeholders={
                **self._feature_context_placeholders(
                    FEATURE_MAXIMUM_OPENING
                ),
                **self._option_placeholders(),
                "current": str(index + 1),
                "count": str(len(covers)),
            },
        )

    async def async_step_maximum_opening_hub(
        self, user_input=None
    ) -> ConfigFlowResult:
        """List every eligible cover under the selected room feature."""
        routes: list[dict[str, Any]] = []
        for context in self._maximum_opening_covers():
            cover = context["cover"]
            enabled = bool(cover.get("enforce_max_open_position", False))
            limit = float(cover.get("max_open_position", 100.0))
            state = (
                f"{limit:g} %"
                if enabled
                else ("Aus" if self._is_german() else "Off")
            )
            routes.append(
                {
                    "label": (
                        f"{cover.get('name') or cover.get('entity')} · {state}"
                    ),
                    "action": "manage_maximum_opening_cover",
                    "room_id": self.room()["id"],
                    "sector_id": context["sector"]["id"],
                    "layer_id": context["layer"]["id"],
                    "cover_index": context["cover_index"],
                    "cover_entity": cover.get("entity"),
                }
            )
        return self._room_object_menu(
            routes,
            step_id="maximum_opening_hub",
            back_action="back_to_room",
            back_label="back_to_room",
        )

    async def async_step_manage_maximum_opening_cover(
        self, user_input=None
    ) -> ConfigFlowResult:
        """Edit one cover limit and return to the dedicated feature page."""
        self._special_return_step = "maximum_opening_hub"
        return await self.async_step_manage_cover_special(user_input)

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

    VERSION = 20

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        sun_state = self.hass.states.get(DEFAULT_SUN_ENTITY)
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
                    CONF_SUN_ENTITY: DEFAULT_SUN_ENTITY,
                    CONF_DIAGNOSTIC_LEVEL: "off",
                    CONF_ADVANCED_MODE: advanced,
                    CONF_EVALUATION_INTERVAL: DEFAULT_EVALUATION_INTERVAL,
                    CONF_ROOMS: [],
                }
                self._room_id = None
                self._sector_id = None
                self._layer_id = None
                self._cover_index = None
                self._zone_id = None
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
                self._initial_maximum_cover_index = 0
                self._initial_function_layer_index = 0
                self._initial_feature_index = 0
                self._queued_feature_setup = None
                self._night_just_enabled = False
                self._automation_feature_scope = None
                self._conditions_feature_scope = None
                self._after_protected_zone_step = None
                self._pending_sector = None
                self._pending_layer = None
                self._option_routes = {}
                self._initial_setup = True
                if advanced:
                    return await self.async_step_advanced_room_setup()
                return await self.async_step_easy_room_setup()
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
            if self.advanced_mode:
                room.update(deepcopy(ADVANCED_EXECUTION_ROOM_DEFAULTS))
            room.update(
                {
                    "id": _new_id(str(values["name"])),
                    "name": str(values["name"]),
                    "outdoor_temperature": outdoor_temperature,
                    "sectors": [],
                    CONF_EXTERNAL_MOVEMENT_DETECTION: False,
                }
            )
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
        """Handle the first-room form rendered after the setup choice."""
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
            ["add_room", "diagnostics_settings", "finish"]
        )
        menu_options: dict[str, str] = {"add_room": labels["add_room"]}
        for route in build_main_room_routes(self.rooms, german=self._is_german()):
            self._add_option_route(
                menu_options,
                str(route["label"]),
                str(route["action"]),
                room_id=route["room_id"],
            )
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

    async def _async_step_automation_feature(self, feature, user_input):
        return await SmartShadingOptionsFlow._async_step_automation_feature(
            self, feature, user_input
        )

    async def _rerender_automation_feature(self):
        return await SmartShadingOptionsFlow._rerender_automation_feature(self)

    async def async_step_manage_schedule(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_manage_schedule(
            self, user_input
        )

    async def async_step_manage_temperature(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_manage_temperature(
            self, user_input
        )

    async def async_step_manage_execution(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_manage_execution(
            self, user_input
        )

    async def async_step_manage_night(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_manage_night(self, user_input)

    def _layers_with_function_targets(self, prefix):
        return SmartShadingOptionsFlow._layers_with_function_targets(self, prefix)

    async def _async_step_initial_function_targets(self, **kwargs):
        return await SmartShadingOptionsFlow._async_step_initial_function_targets(
            self, **kwargs
        )

    async def async_step_manage_pause(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_manage_pause(self, user_input)

    async def async_step_manage_conditions(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_manage_conditions(
            self, user_input
        )

    async def _rerender_conditions_feature(self):
        return await SmartShadingOptionsFlow._rerender_conditions_feature(self)

    async def async_step_manage_safety(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_manage_safety(
            self, user_input
        )

    async def async_step_manage_weather_conditions(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_manage_weather_conditions(
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

    async def async_step_add_protected_zone(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_add_protected_zone(
            self, user_input
        )

    async def async_step_manage_protected_zone(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_manage_protected_zone(
            self, user_input
        )

    async def async_step_confirm_protected_zone(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_confirm_protected_zone(
            self, user_input
        )

    async def async_step_delete_protected_zone(self, user_input=None):
        return await SmartShadingOptionsFlow.async_step_delete_protected_zone(
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
                if return_step == "group_hub":
                    return await self._finish_structure_change(
                        fallback=return_step
                    )
                return await getattr(self, f"async_step_{return_step}")()
            if getattr(self, "_initial_setup", False) and self.advanced_mode:
                return await self.async_step_choose_advanced_features()
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
                    "allow_automatic_reverse": DEFAULT_ALLOW_AUTOMATIC_REVERSE,
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
                self._strip_easy_issue79_execution_fields()
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
            self._working[CONF_SUN_ENTITY] = DEFAULT_SUN_ENTITY
            self._working.setdefault(
                CONF_DIAGNOSTIC_LEVEL,
                "events" if self._working.get(CONF_TEST_MODE, False) else "off",
            )
            self._working.pop(CONF_TEST_MODE, None)
            self._strip_easy_issue79_execution_fields()
            self._room_id = None
            self._sector_id = None
            self._layer_id = None
            self._cover_index = None
            self._zone_id = None
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
            self._initial_maximum_cover_index = 0
            self._initial_function_layer_index = 0
            self._initial_feature_index = 0
            self._queued_feature_setup = None
            self._night_just_enabled = False
            self._automation_feature_scope = None
            self._conditions_feature_scope = None
            self._after_protected_zone_step = None
            self._pending_sector = None
            self._pending_layer = None
            self._option_routes = {}
            self._initial_setup = False
        labels = self._menu(
            [
                "add_room",
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
        if self.advanced_mode:
            menu_options["diagnostics_settings"] = labels[
                "diagnostics_settings"
            ]
        menu_options["finish"] = labels["save_changes"]
        return self.async_show_menu(step_id="init", menu_options=menu_options)

    async def async_step_manage_room_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit room identity and the optional outdoor temperature source."""
        room = self.room()
        errors: dict[str, str] = {}
        if user_input is not None:
            values = _flatten_sections(user_input)
            temperature_enabled = (
                self.advanced_mode
                and self._feature_enabled(FEATURE_TEMPERATURE, room)
            )
            outdoor_temperature = (
                str(values.get("outdoor_temperature") or "").strip()
                if temperature_enabled
                else ""
            )
            room["name"] = str(values.get("name") or room["name"])
            room["outdoor_temperature"] = outdoor_temperature
            if outdoor_temperature:
                self._after_outdoor_step = "room_hub"
                return await self.async_step_configure_outdoor_temperature()
            return await self.async_step_room_hub()
        temperature_enabled = (
            self.advanced_mode
            and self._feature_enabled(FEATURE_TEMPERATURE, room)
        )
        fields: dict[Any, Any] = {
            vol.Required("name", default=room.get("name", "")): selector.TextSelector(),
        }
        if temperature_enabled:
            fields[_optional_marker(
                "outdoor_temperature",
                room.get("outdoor_temperature", ""),
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

    async def _async_step_automation_feature(
        self, feature: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Render exactly one selected automation feature."""
        self._automation_feature_scope = feature
        if feature == FEATURE_SCHEDULE:
            self.room()["schedule_enabled"] = True
        return await self.async_step_manage_automation(user_input)

    async def async_step_manage_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_step_automation_feature(
            FEATURE_SCHEDULE, user_input
        )

    async def async_step_manage_temperature(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_step_automation_feature(
            FEATURE_TEMPERATURE, user_input
        )

    async def async_step_manage_execution(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_step_automation_feature(
            FEATURE_EXPERT_EXECUTION, user_input
        )

    async def _rerender_automation_feature(self) -> ConfigFlowResult:
        scope = getattr(self, "_automation_feature_scope", None)
        handlers = {
            FEATURE_SCHEDULE: self.async_step_manage_schedule,
            FEATURE_TEMPERATURE: self.async_step_manage_temperature,
            FEATURE_EXPERT_EXECUTION: self.async_step_manage_execution,
        }
        handler = handlers.get(scope)
        if handler is not None:
            return await handler()
        return await self.async_step_manage_automation()

    async def async_step_manage_automation(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Render one selected schedule, temperature or execution feature."""
        if not self.advanced_mode:
            return await self.async_step_room_hub()
        room = self.room()
        selected_features = self._advanced_features(room)
        scope = getattr(self, "_automation_feature_scope", None)
        configure_schedule = (
            FEATURE_SCHEDULE in selected_features
            and scope in (None, FEATURE_SCHEDULE)
        )
        temperature_selected = (
            FEATURE_TEMPERATURE in selected_features
            and scope in (None, FEATURE_TEMPERATURE)
        )
        configure_temperature = temperature_selected
        configure_execution = (
            FEATURE_EXPERT_EXECUTION in selected_features
            and scope in (None, FEATURE_EXPERT_EXECUTION)
        )
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
        stored_stagger_scope = str(room.get("stagger_scope") or "")
        current_stagger_scope = (
            stored_stagger_scope
            if stored_stagger_scope in STAGGER_SCOPE_OPTIONS
            else DEFAULT_STAGGER_SCOPE
        )
        stored_safety_bypasses_stagger = room.get(
            "safety_bypasses_stagger", DEFAULT_SAFETY_BYPASSES_STAGGER
        )
        current_safety_bypasses_stagger = (
            stored_safety_bypasses_stagger
            if isinstance(stored_safety_bypasses_stagger, bool)
            else DEFAULT_SAFETY_BYPASSES_STAGGER
        )
        current_schedule_enabled = bool(room.get("schedule_enabled", False))
        if user_input is not None:
            values = _flatten_sections(user_input)
            selected_schedule_enabled = (
                True if configure_schedule else current_schedule_enabled
            )
            submitted_values = values
            selected_profile = str(
                values.get("schedule_profile", current_profile) if configure_schedule else current_profile
            )
            selected_window = str(values.get("day_window", current_window) if configure_schedule else current_window)
            selected_stagger_scope = str(
                values.get(
                    "stagger_scope",
                    current_stagger_scope,
                )
            )
            if (
                (configure_schedule and (
                    selected_profile not in SCHEDULE_OPTIONS
                    or selected_window not in DAY_WINDOW_OPTIONS
                ))
                or (configure_execution and selected_stagger_scope not in STAGGER_SCOPE_OPTIONS)
            ):
                errors["base"] = "option_not_available"
            if not errors and configure_temperature:
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
            if not errors and configure_schedule and selected_schedule_enabled and selected_profile == SCHEDULE_CUSTOM and (
                not values.get("active_months") or not values.get("active_weekdays")
            ):
                errors["base"] = "select_at_least_one"
            if not errors:
                for key, value in values.items():
                    room[key] = value
                if configure_schedule:
                    profile = room.get("schedule_profile", SCHEDULE_YEAR_ROUND)
                    if profile == SCHEDULE_SUMMER:
                        room["active_months"] = [5, 6, 7, 8, 9]
                        room["active_weekdays"] = list(range(7))
                    elif profile != SCHEDULE_CUSTOM:
                        room["active_months"] = list(range(1, 13))
                        room["active_weekdays"] = list(range(7))
                if configure_temperature and self._venetian_only(room):
                    room["comfort_temperature"] = room["normal_shading_temperature"]
                    room["solar_temperature"] = room["normal_shading_temperature"]
                return await self._finish_feature_step()

        schedule: dict[Any, Any] = {}
        if current_schedule_enabled:
            schedule.update(
                {
                    vol.Required(
                        "schedule_profile", default=current_profile
                    ): self._choice(SCHEDULE_OPTIONS, "schedule_profile"),
                    vol.Required(
                        "day_window", default=current_window
                    ): self._choice(DAY_WINDOW_OPTIONS, "day_window"),
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
                    vol.Required(
                        "start_time",
                        default=room.get("start_time", "00:00:00"),
                    ): selector.TimeSelector(),
                    vol.Required(
                        "end_time",
                        default=room.get("end_time", "23:59:59"),
                    ): selector.TimeSelector(),
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
        sections: dict[Any, Any] = {}
        if configure_schedule:
            sections[vol.Required("schedule_settings")] = section(
                self._form_schema(vol.Schema(schedule), submitted_values, errors),
                {"collapsed": False},
            )
        if temperature_selected:
            temperatures: dict[Any, Any] = {
                vol.Required(
                    "indoor_temperature",
                    default=room.get("indoor_temperature", ""),
                ): _temperature_entity(),
            }
            if configure_temperature:
                temperatures.update(
                    {
                        vol.Required(
                            "heat_temperature",
                            default=room.get("heat_temperature", 27.0),
                        ): _number(5, 45, 0.1, "°C"),
                        vol.Required(
                            "evening_release_time",
                            default=room.get(
                                "evening_release_time",
                                DEFAULT_EVENING_RELEASE_TIME,
                            ),
                        ): selector.TimeSelector(),
                        vol.Required(
                            "sunset_offset_minutes",
                            default=room.get(
                                "sunset_offset_minutes",
                                DEFAULT_SUNSET_OFFSET_MINUTES,
                            ),
                        ): _number(-120, 120, 5, "min"),
                    }
                )
            if configure_temperature and self._venetian_only(room):
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
            elif configure_temperature:
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
        execution = {
            vol.Required(
                "command_stagger_seconds",
                default=room.get(
                    "command_stagger_seconds", DEFAULT_STAGGER_SECONDS
                ),
            ): _number(0, 60, 0.5, "s", mode="box"),
            vol.Required(
                "stagger_scope",
                default=current_stagger_scope,
            ): self._choice(STAGGER_SCOPE_OPTIONS, "stagger_scope"),
            vol.Required(
                "safety_bypasses_stagger",
                default=current_safety_bypasses_stagger,
            ): selector.BooleanSelector(),
            vol.Required(
                "target_verification_enabled",
                default=room.get("target_verification_enabled", False),
            ): selector.BooleanSelector(),
            vol.Required(
                "verification_retries",
                default=room.get(
                    "verification_retries", DEFAULT_VERIFICATION_RETRIES
                ),
            ): _number(0, 5, 1, "", mode="box"),
            vol.Required(
                "movement_seconds",
                default=room.get("movement_seconds", DEFAULT_MOVEMENT_SECONDS),
            ): _number(0, 900, 1, "s", mode="box"),
            vol.Required(
                "settling_seconds",
                default=room.get("settling_seconds", DEFAULT_SETTLING_SECONDS),
            ): _number(0, 120, 1, "s", mode="box"),
            vol.Required(
                "source_stale_seconds",
                default=room.get(
                    "source_stale_seconds", DEFAULT_SOURCE_STALE_SECONDS
                ),
            ): _number(0, 86400, 30, "s", mode="box"),
        }
        if configure_execution:
            sections[vol.Required("execution_settings")] = section(
                self._form_schema(
                    vol.Schema(execution), submitted_values, errors
                ),
                {"collapsed": True},
            )
        description_placeholders = self._feature_context_placeholders(
            scope or FEATURE_SCHEDULE
        )
        description_placeholders["temperature_behavior"] = (
            self._temperature_behavior_text(room)
            if temperature_selected
            else ""
        )
        return self.async_show_form(
            step_id="manage_automation",
            data_schema=self._form_schema(
                vol.Schema(sections), user_input, errors
            ),
            errors=errors,
            description_placeholders=description_placeholders,
        )

    async def async_step_manage_night(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure Night before any Night-dependent pause is offered."""
        if not self.advanced_mode:
            return await self.async_step_room_hub()
        if not self._feature_enabled(FEATURE_NIGHT):
            return await self.async_step_advanced_features_hub()
        room = self.room()
        room["night_enabled"] = True
        errors: dict[str, str] = {}
        stored_source = str(room.get("night_source", "entity"))
        current_source = stored_source if stored_source in {"entity", "sun"} else "entity"
        if user_input is not None:
            values = _flatten_sections(user_input)
            source = str(values.get("night_source", current_source))
            if source not in {"entity", "sun"}:
                errors["base"] = "option_not_available"
            elif source != current_source:
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
            elif source == "entity" and not values.get("night_entity"):
                errors["base"] = "night_entity_required"
            if not errors:
                room.update(values)
                room["night_enabled"] = True
                self._night_just_enabled = False
                return await self._finish_feature_step()
        night: dict[Any, Any] = {
            vol.Required("night_source", default=current_source): self._choice(
                ["entity", "sun"], "night_source"
            )
        }
        if current_source == "entity":
            night[
                _optional_marker(
                    "night_entity", room.get("night_entity", "")
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
            description_placeholders=self._feature_context_placeholders(
                FEATURE_NIGHT
            ),
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
            description_placeholders=self._feature_context_placeholders(
                FEATURE_NIGHT if prefix == "night_" else FEATURE_SAFETY
            ),
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

    async def async_step_manage_safety(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._conditions_feature_scope = FEATURE_SAFETY
        return await self.async_step_manage_conditions(user_input)

    async def async_step_manage_weather_conditions(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._conditions_feature_scope = FEATURE_CONDITIONS
        return await self.async_step_manage_conditions(user_input)

    async def _rerender_conditions_feature(self) -> ConfigFlowResult:
        if getattr(self, "_conditions_feature_scope", None) == FEATURE_SAFETY:
            return await self.async_step_manage_safety()
        if getattr(self, "_conditions_feature_scope", None) == FEATURE_CONDITIONS:
            return await self.async_step_manage_weather_conditions()
        return await self.async_step_manage_conditions()

    async def async_step_manage_conditions(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show only conditions supported by the selected sources and profiles."""
        if not self.advanced_mode:
            return await self.async_step_room_hub()
        scope = getattr(self, "_conditions_feature_scope", None)
        configure_safety = (
            self._feature_enabled(FEATURE_SAFETY)
            and scope in (None, FEATURE_SAFETY)
        )
        configure_conditions = (
            self._feature_enabled(FEATURE_CONDITIONS)
            and scope in (None, FEATURE_CONDITIONS)
        )
        if not (configure_safety or configure_conditions):
            return await self.async_step_advanced_features_hub()
        room = self.room()
        errors: dict[str, str] = {}
        source_keys = (
            "irradiance_sensor",
            "cloud_cover_sensor",
            "weather_permission",
            "occupancy_sensor",
        )
        safety_relevant = (
            configure_safety
            and self._uses_exterior_safety(room)
        )
        safety_target_layers = (
            self._layers_with_function_targets("safety_")
            if safety_relevant
            else []
        )
        inline_safety_target = (
            safety_target_layers[0]
            if getattr(self, "_initial_setup", False)
            and len(safety_target_layers) == 1
            else None
        )
        if user_input is not None:
            values = _flatten_sections(user_input)
            occupancy_sensor = (
                str(values.get("occupancy_sensor") or "")
                if configure_conditions
                else str(room.get("occupancy_sensor") or "")
            )
            if (
                configure_conditions
                and values.get("comfort_requires_occupancy", False)
                and not occupancy_sensor
            ):
                errors["base"] = "occupancy_source_required"
            if not errors:
                selected_safety = (
                    list(values.get("safety_blockers") or [])
                    if safety_relevant
                    else list(room.get("safety_blockers", []))
                )
                if configure_safety:
                    room["safety_blockers"] = selected_safety
                    if "safety_behavior" in values:
                        room["safety_behavior"] = values["safety_behavior"]
                    if not room.get("safety_blockers"):
                        room["safety_behavior"] = "move_safe"
                if configure_conditions:
                    for key in source_keys:
                        selected = str(values.get(key) or "")
                        room[key] = selected
                    for key in (
                        "irradiance_minimum",
                        "cloud_cover_maximum",
                        "weather_logic",
                        "heat_ignores_weather",
                        "heat_requires_sun",
                        "comfort_requires_occupancy",
                    ):
                        if key in values:
                            room[key] = values[key]
                if configure_conditions and not room.get("occupancy_sensor"):
                    room["comfort_requires_occupancy"] = False
                if inline_safety_target is not None:
                    _, layer, target_keys = inline_safety_target
                    for key in target_keys:
                        if key in values:
                            layer[key] = float(values[key])
                if getattr(self, "_initial_setup", False):
                    return await self._complete_initial_feature()
                return await self.async_step_room_hub()
        fields: dict[Any, Any] = {}
        if safety_relevant:
            fields[_optional_marker(
                "safety_blockers", room.get("safety_blockers", [])
            )] = _entity("binary_sensor", multiple=True)
        if configure_conditions:
            fields[_optional_marker(
                "irradiance_sensor", room.get("irradiance_sensor", "")
            )] = _entity("sensor")
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
            fields[vol.Required(
                "cloud_cover_maximum",
                default=room.get("cloud_cover_maximum", 85.0),
            )] = _number(0, 100, 1, "%")
            fields[_optional_marker(
                "weather_permission", room.get("weather_permission", "")
            )] = _entity("binary_sensor")
            fields[_optional_marker(
                "occupancy_sensor", room.get("occupancy_sensor", "")
            )] = _entity("binary_sensor")

            fields[vol.Required(
                "weather_logic", default=room.get("weather_logic", "all")
            )] = self._choice(["all", "any"], "weather_logic")
            fields[vol.Required(
                "comfort_requires_occupancy",
                default=room.get("comfort_requires_occupancy", False),
            )] = selector.BooleanSelector()
        if safety_relevant:
            fields[vol.Required(
                "safety_behavior",
                default=room.get("safety_behavior", "move_safe"),
            )] = self._choice(["move_safe", "block"], "safety_behavior")
            if inline_safety_target is not None:
                _, layer, target_keys = inline_safety_target
                profile = str(layer.get("profile", DEVICE_VENETIAN))
                for key in target_keys:
                    fields[
                        vol.Required(
                            key,
                            default=layer.get(
                                key,
                                PROFILE_DEFAULTS[profile].get(key, 0.0),
                            ),
                        )
                    ] = _number(0, 100, 1, "%")
        if (
            configure_conditions
            and str(room.get("indoor_temperature") or "").strip()
        ):
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
            description_placeholders=self._feature_context_placeholders(
                scope or (
                    FEATURE_SAFETY
                    if configure_safety
                    else FEATURE_CONDITIONS
                )
            ),
        )

    async def async_step_initial_safety_targets(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer safe targets only after move-to-safe protection is enabled."""
        return await self._async_step_initial_function_targets(
            prefix="safety_",
            step_id="initial_safety_targets",
            next_step="complete_initial_feature",
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

    async def async_step_add_protected_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create one Advanced-only glare-protection zone for this sector."""
        if not self.advanced_mode or not self._feature_enabled(FEATURE_GLARE_PROTECTION):
            return await self.async_step_sector_hub()
        errors: dict[str, str] = {}
        if user_input is not None:
            values = _flatten_sections(user_input)
            zone_values, errors = self._validated_protected_zone_values(values)
            if not errors and zone_values is not None:
                zone_values["id"] = _new_id(zone_values["name"])
                self._pending_protected_zone = {
                    "action": "add",
                    "values": zone_values,
                }
                return await self.async_step_confirm_protected_zone()
        pending = getattr(self, "_pending_protected_zone", None)
        seed = (
            dict(pending.get("values", {}))
            if isinstance(pending, dict)
            and pending.get("action") == "add"
            else {}
        )
        return self.async_show_form(
            step_id="add_protected_zone",
            data_schema=self._form_schema(
                vol.Schema(
                    self._protected_zone_form_sections(
                        seed, include_maintenance=False
                    )
                ),
                user_input,
                errors,
            ),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_manage_protected_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit a stable Advanced-only protected zone."""
        if not self.advanced_mode or not self._feature_enabled(FEATURE_GLARE_PROTECTION):
            return await self.async_step_sector_hub()
        try:
            zone = self.protected_zone()
        except StopIteration:
            return await self.async_step_protected_zones_hub()
        pending = getattr(self, "_pending_protected_zone", None)
        form_zone = (
            dict(pending.get("values", {}))
            if isinstance(pending, dict)
            and pending.get("action") == "manage"
            and isinstance(pending.get("values"), dict)
            else zone
        )
        errors: dict[str, str] = {}
        if user_input is not None:
            values = _flatten_sections(user_input)
            if values.get("delete_protected_zone", False):
                return await self.async_step_delete_protected_zone()
            zone_values, errors = self._validated_protected_zone_values(values)
            if not errors and zone_values is not None:
                zone_id = str(zone["id"])
                self._pending_protected_zone = {
                    "action": "manage",
                    "values": {"id": zone_id, **zone_values},
                }
                return await self.async_step_confirm_protected_zone()
        return self.async_show_form(
            step_id="manage_protected_zone",
            data_schema=self._form_schema(
                vol.Schema(
                    self._protected_zone_form_sections(
                        form_zone, include_maintenance=True
                    )
                ),
                user_input,
                errors,
            ),
            errors=errors,
            description_placeholders=self._option_placeholders(),
        )

    async def async_step_confirm_protected_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show a calculation check before a protected zone is persisted."""
        pending = getattr(self, "_pending_protected_zone", None)
        if not isinstance(pending, dict) or not isinstance(
            pending.get("values"), dict
        ):
            return await self.async_step_protected_zones_hub()
        values = dict(pending["values"])
        action = str(pending.get("action") or "")
        if user_input is not None:
            if not user_input.get("confirm_protected_zone", True):
                return (
                    await self.async_step_manage_protected_zone()
                    if action == "manage"
                    else await self.async_step_add_protected_zone()
                )
            if action == "manage":
                try:
                    zone = self.protected_zone()
                except StopIteration:
                    self._pending_protected_zone = None
                    return await self.async_step_protected_zones_hub()
                zone.clear()
                zone.update(values)
            else:
                self.protected_zones().append(values)
                self._zone_id = str(values["id"])
            self._pending_protected_zone = None
            if action == "add" and getattr(
                self, "_after_protected_zone_step", None
            ):
                return await self._go_to_saved_step(
                    "_after_protected_zone_step",
                    fallback="protected_zones_hub",
                )
            return await self.async_step_protected_zones_hub()
        return self.async_show_form(
            step_id="confirm_protected_zone",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "confirm_protected_zone", default=True
                    ): selector.BooleanSelector()
                }
            ),
            description_placeholders=self._protected_zone_preview(values),
        )

    async def async_step_delete_protected_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Require an explicit confirmation before deleting the stable zone."""
        if not self.advanced_mode or not self._feature_enabled(FEATURE_GLARE_PROTECTION):
            return await self.async_step_sector_hub()
        try:
            zone = self.protected_zone()
        except StopIteration:
            return await self.async_step_protected_zones_hub()
        if user_input is not None:
            if user_input.get("confirm_delete_protected_zone", False):
                zone_id = str(zone["id"])
                self.sector()["protected_zones"] = [
                    item
                    for item in self.protected_zones()
                    if item["id"] != zone_id
                ]
                self._zone_id = None
                return await self.async_step_protected_zones_hub()
            return await self.async_step_manage_protected_zone()
        return self.async_show_form(
            step_id="delete_protected_zone",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "confirm_delete_protected_zone", default=False
                    ): selector.BooleanSelector()
                }
                ),
                description_placeholders=self._feature_context_placeholders(
                    FEATURE_GLARE_PROTECTION
                ),
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
                self._remember_optional_feature_availability()
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
                # One complete sector does not imply a complete room. Let the
                # customer add every sector, group and cover before optional
                # features are selected for that full structure.
                return await self.async_step_structure_hub()
            return await self.async_step_after_room()
        return await self._finish_structure_change(fallback="sector_hub")

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
                    if self.advanced_mode and profile_supports_tilt(profile):
                        layer["opening_order"] = DEFAULT_OPENING_ORDER
                    else:
                        layer.pop("opening_order", None)
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
        stored_opening_order = str(layer.get("opening_order") or "")
        current_opening_order = (
            stored_opening_order
            if stored_opening_order in OPENING_ORDER_OPTIONS
            else DEFAULT_OPENING_ORDER
        )
        errors: dict[str, str] = {}
        rerender_custom_curve = False
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
            opening_order = str(
                values.get(
                    "opening_order",
                    current_opening_order,
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
            if (
                not errors
                and self.advanced_mode
                and has_tilt
                and opening_order not in OPENING_ORDER_OPTIONS
            ):
                errors["base"] = "option_not_available"
            if not errors:
                if self.advanced_mode and has_tilt:
                    layer["opening_order"] = opening_order
                else:
                    layer.pop("opening_order", None)
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
                    # Night targets belong to the physical group profile,
                    # regardless of whether the room-level Night feature is
                    # already enabled.
                    night=True,
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
            if self.advanced_mode:
                behavior[
                    vol.Required(
                        "opening_order",
                        default=current_opening_order,
                    )
                ] = self._choice(OPENING_ORDER_OPTIONS, "opening_order")
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
                    night=True,
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
            self._remember_optional_feature_availability()
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
        return await self._finish_structure_change(fallback="group_hub")

    async def async_step_manage_cover(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit one cover using only settings supported by its group."""
        covers = self.layer().get("covers", [])
        cover = covers[self._cover_index]
        profile = str(self.layer().get("profile", DEVICE_VENETIAN))
        errors: dict[str, str] = {}
        # This is intentionally an Advanced-only ownership policy.  Strip a
        # crafted beta value while an Easy flow is open so saving options can
        # never preserve an invisible automatic-reversal behavior.
        if not self.advanced_mode:
            cover.pop("allow_automatic_reverse", None)
        stored_automatic_reverse = cover.get(
            "allow_automatic_reverse", DEFAULT_ALLOW_AUTOMATIC_REVERSE
        )
        current_automatic_reverse = (
            stored_automatic_reverse
            if isinstance(stored_automatic_reverse, bool)
            else DEFAULT_ALLOW_AUTOMATIC_REVERSE
        )
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
            if self.advanced_mode and str(
                values.get(
                    "feedback_quality", cover.get("feedback_quality", "trusted")
                )
            ) not in FEEDBACK_QUALITY_OPTIONS:
                errors["base"] = "option_not_available"
            if not errors:
                cover["name"] = str(values.get("name") or cover.get("name", "Cover"))
                cover["short"] = str(values.get("short") or cover.get("short", ""))
                if self.advanced_mode:
                    cover["lock"] = values.get("lock", "")
                    cover["window"] = values.get("window", "")
                    for key in (
                        "window_safe_state", "window_policy",
                        CONF_WINDOW_RETURNS_TO_AUTOMATION, "invert_position",
                        "feedback_quality", "verify_target",
                        "allow_automatic_reverse",
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
                vol.Required("feedback_quality", default=cover.get("feedback_quality", "trusted")): self._choice(FEEDBACK_QUALITY_OPTIONS, "feedback_quality"),
                vol.Required("verify_target", default=cover.get("verify_target", False)): selector.BooleanSelector(),
                vol.Required(
                    "allow_automatic_reverse",
                    default=current_automatic_reverse,
                ): selector.BooleanSelector(),
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
        if (
            not self.advanced_mode
            or not self._feature_enabled(FEATURE_MAXIMUM_OPENING)
            or not profile_supports_position(profile)
        ):
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
            if "max_open_position" in user_input:
                cover["max_open_position"] = float(
                    user_input["max_open_position"]
                )
            return await self._go_to_saved_step(
                "_special_return_step", fallback="cover_settings_hub"
            )
        fields: dict[Any, Any] = {
            vol.Required(
                "enforce_max_open_position", default=current_enabled
            ): selector.BooleanSelector(),
            vol.Required(
                "max_open_position",
                default=cover.get("max_open_position", 100.0),
            ): _number(0, 100, 1, "%"),
        }
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
            return await self.async_step_choose_advanced_features()
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
                self._remember_optional_feature_availability()
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
        self._strip_easy_issue79_execution_fields()
        return self.async_create_entry(title="", data=editable_options(self._working))
