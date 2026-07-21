from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ADVANCED_MODE,
    CONF_DIAGNOSTIC_LEVEL,
    CONF_EVALUATION_INTERVAL,
    CONF_EXTERNAL_MOVEMENT_DETECTION,
    CONF_SUN_PRESENCE_ENTITY,
    CONF_ROOMS,
    CONF_TEST_MODE,
    CONF_WINDOW_RETURNS_TO_AUTOMATION,
    DAY_WINDOW_ALL_DAY,
    DEFAULT_EVALUATION_INTERVAL,
    DEFAULT_EVENING_RELEASE_TIME,
    DEFAULT_SUNSET_OFFSET_MINUTES,
    DEFAULT_WINDOW_RETURNS_TO_AUTOMATION,
    DOMAIN,
    PLATFORMS,
    PROFILE_DEFAULTS,
    ROOM_DEFAULTS,
    SUN_PRESETS,
    TILT_CURVE_PRESETS,
    TILT_PRESET_BALANCED,
    profile_supports_position,
    profile_supports_tilt,
    profile_uses_exterior_safety,
)
from .controller import SmartShadingEngine
from .flow_contract import (
    editable_options,
    legacy_effective_config,
    locked_advanced_mode,
    sun_source_for_sector,
)
from .logic import migrate_slat_config
from .storage import RuntimeStore


type SmartShadingConfigEntry = ConfigEntry[SmartShadingEngine]


def _normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    """Add V4 defaults while preserving existing entity assignments."""
    result = deepcopy(config)
    result.setdefault(CONF_ROOMS, [])
    result.setdefault(CONF_ADVANCED_MODE, False)
    result.setdefault(
        CONF_DIAGNOSTIC_LEVEL,
        "events" if result.get(CONF_TEST_MODE, False) else "off",
    )
    result.pop(CONF_TEST_MODE, None)
    result.setdefault(CONF_EVALUATION_INTERVAL, DEFAULT_EVALUATION_INTERVAL)
    result.pop("weather_entity", None)
    legacy_evening_release = result.pop(
        "evening_release_time", DEFAULT_EVENING_RELEASE_TIME
    )
    legacy_sunset_offset = result.pop(
        "sunset_offset_minutes", DEFAULT_SUNSET_OFFSET_MINUTES
    )
    for obsolete in (
        "position_tolerance",
        "tilt_tolerance",
        "command_cooldown",
        "unknown_feedback_policy",
    ):
        result.pop(obsolete, None)
    # An obsolete pre-V4 curve after conversion to the KNX slat scale.
    old_curve = [(10.0, 10.0), (20.0, 50.0), (40.0, 85.0), (60.0, 90.0)]

    for room in result[CONF_ROOMS]:
        room.pop("easy_temperature_gate", None)
        for obsolete in (
            "indoor_temperature_name",
            "display_name",
            "outdoor_temperature_name",
        ):
            room.pop(obsolete, None)
        if room.get("day_window") == "sector_sun":
            room["day_window"] = DAY_WINDOW_ALL_DAY
        if "schedule_enabled" not in room:
            room["schedule_enabled"] = bool(
                room.get("schedule_profile", "year_round") != "year_round"
                or room.get("day_window", DAY_WINDOW_ALL_DAY)
                != DAY_WINDOW_ALL_DAY
                or list(room.get("active_months", range(1, 13)))
                != list(range(1, 13))
                or list(room.get("active_weekdays", range(7)))
                != list(range(7))
            )
        if "evening_release_time" not in room:
            room["evening_release_time"] = legacy_evening_release
        if "sunset_offset_minutes" not in room:
            room["sunset_offset_minutes"] = legacy_sunset_offset
        for key, value in ROOM_DEFAULTS.items():
            room.setdefault(key, deepcopy(value))
        room.setdefault("normal_shading_temperature", room.get("comfort_temperature", 23.5))
        room.setdefault("sectors", [])
        room["active_months"] = [int(v) for v in room.get("active_months", range(1, 13))]
        room["active_weekdays"] = [int(v) for v in room.get("active_weekdays", range(7))]

        for sector in room.get("sectors", []):
            sector.setdefault("enabled", True)
            sector.setdefault(CONF_SUN_PRESENCE_ENTITY, "")
            source = sun_source_for_sector(
                sector, advanced=bool(result.get(CONF_ADVANCED_MODE, False))
            )
            sector["sun_source"] = source
            if source != "lux":
                sector["lux_sensor"] = ""
            if source != "external":
                sector[CONF_SUN_PRESENCE_ENTITY] = ""
            preset = str(sector.get("sun_preset", "medium"))
            if not result.get(CONF_ADVANCED_MODE, False) and preset == "custom":
                preset = "medium"
                sector["sun_preset"] = preset
            if preset in SUN_PRESETS:
                sector.update(deepcopy(SUN_PRESETS[preset]))
            sector.setdefault("layers", [])
            for layer in sector.get("layers", []):
                profile = str(layer.get("profile", "venetian"))
                if profile not in PROFILE_DEFAULTS:
                    profile = "venetian"
                layer["profile"] = profile
                defaults = PROFILE_DEFAULTS.get(profile, PROFILE_DEFAULTS["venetian"])
                legacy_heat_close_enabled = layer.pop(
                    "heat_close_enabled", None
                )
                layer.pop("safety_position_override", None)
                profile_keys = {
                    key
                    for values in PROFILE_DEFAULTS.values()
                    for key in values
                }
                for key in profile_keys:
                    if key not in defaults:
                        layer.pop(key, None)
                for key, value in defaults.items():
                    if key in {"supports_position", "supports_tilt", "adaptive_tilt"}:
                        layer[key] = deepcopy(value)
                    else:
                        layer.setdefault(key, deepcopy(value))
                # The old curtain switch made the visible heat-position field
                # ineffective while disabled. Preserve that effective target
                # once, then keep only the single position customers edit.
                if (
                    profile == "curtain"
                    and legacy_heat_close_enabled is not None
                    and not bool(legacy_heat_close_enabled)
                ):
                    layer["heat_position"] = layer.get(
                        "solar_position", defaults["solar_position"]
                    )
                layer.setdefault("covers", [])
                curve = [
                    (float(point.get("elevation", 0)), float(point.get("tilt", 0)))
                    for point in layer.get("tilt_curve", [])
                ]
                if profile in {"venetian", "vertical_blind"} and (
                    not curve or curve == old_curve
                ):
                    layer["tilt_preset"] = TILT_PRESET_BALANCED
                    layer["tilt_curve"] = deepcopy(
                        TILT_CURVE_PRESETS[TILT_PRESET_BALANCED]
                    )
                for cover in layer.get("covers", []):
                    cover.setdefault("name", "")
                    cover.setdefault("short", "")
                    cover.setdefault("lock", "")
                    cover.setdefault("window", "")
                    cover.setdefault("window_safe_state", "on")
                    cover.setdefault("window_policy", "block_closing")
                    cover.setdefault(
                        CONF_WINDOW_RETURNS_TO_AUTOMATION,
                        DEFAULT_WINDOW_RETURNS_TO_AUTOMATION,
                    )
                    cover.setdefault("invert_position", False)
                    cover.setdefault("invert_tilt", False)
                    cover.setdefault("max_open_position", 100.0)
                    cover.setdefault("enforce_max_open_position", False)
                    if not profile_supports_tilt(profile):
                        cover["invert_tilt"] = False
                    if not profile_supports_position(profile):
                        cover["max_open_position"] = 100.0
                        cover["enforce_max_open_position"] = False
        room_profiles = {
            str(layer.get("profile", "venetian"))
            for sector in room.get("sectors", [])
            for layer in sector.get("layers", [])
        }
        if not any(profile_uses_exterior_safety(profile) for profile in room_profiles):
            room["safety_blockers"] = []
    return result


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the bundled frontend once."""
    if not hass.data.get(f"{DOMAIN}_frontend_registered"):
        frontend = Path(__file__).parent / "frontend"
        await hass.http.async_register_static_paths(
            [StaticPathConfig("/smart_shading", str(frontend), False)]
        )
        hass.data[f"{DOMAIN}_frontend_registered"] = True
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate earlier beta entries to the current Smart Shading data model."""
    if entry.version >= 15:
        return True
    raw_data = dict(entry.data)
    raw_options = dict(entry.options)
    # Entry data owns the original one-time choice. A stale beta option must
    # never legitimize a later mode switch; it is only a fallback for entries
    # old enough not to contain the flag in data at all.
    fixed_advanced_mode = locked_advanced_mode(raw_data, raw_options)
    if entry.version < 10:
        data_source = migrate_slat_config(raw_data)
        option_source = migrate_slat_config(raw_options) if raw_options else {}
    else:
        # The beta.8 KNX slat migration must run exactly once. Version 10
        # entries only receive the new Night Mode defaults.
        data_source = raw_data
        option_source = raw_options
    data = _normalize_config(data_source)
    # Merge raw legacy values before adding defaults. This supports both the
    # old partial options format and the later full-snapshot format without an
    # injected ``rooms=[]`` masking the entry data.
    effective = _normalize_config(
        legacy_effective_config(data_source, option_source)
    )
    data[CONF_ADVANCED_MODE] = fixed_advanced_mode
    effective[CONF_ADVANCED_MODE] = fixed_advanced_mode
    options = editable_options(effective) if raw_options else {}
    # Earlier beta versions defaulted to 120 seconds. Move untouched defaults
    # to the new customer-friendly 20-minute interval.
    if int(data.get(CONF_EVALUATION_INTERVAL, 120)) == 120:
        data[CONF_EVALUATION_INTERVAL] = DEFAULT_EVALUATION_INTERVAL
    if options and int(options.get(CONF_EVALUATION_INTERVAL, 120)) == 120:
        options[CONF_EVALUATION_INTERVAL] = DEFAULT_EVALUATION_INTERVAL
    # Existing Advanced installations keep their established pause behavior.
    # New rooms default to opt-in detection; Easy Mode always disables it.
    for config in (data, options):
        if not config:
            continue
        for room in config.get(CONF_ROOMS, []):
            room[CONF_EXTERNAL_MOVEMENT_DETECTION] = bool(
                room.get(CONF_EXTERNAL_MOVEMENT_DETECTION, fixed_advanced_mode)
            ) if fixed_advanced_mode else False
    hass.config_entries.async_update_entry(
        entry, data=data, options=options, version=15
    )
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: SmartShadingConfigEntry
) -> bool:
    engine = SmartShadingEngine(hass, entry)
    entry.runtime_data = engine
    await engine.async_initialize()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await engine.async_start()
    return True

async def async_unload_entry(
    hass: HomeAssistant, entry: SmartShadingConfigEntry
) -> bool:
    entry.runtime_data.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove persistent card notifications when the integration is deleted."""
    store = RuntimeStore(hass, entry.entry_id)
    await store.async_load()
    notification_ids = [
        *store.card_notification_ids(),
        f"smart_shading_sun_{entry.entry_id}",
    ]
    for notification_id in notification_ids:
        await hass.services.async_call(
            "persistent_notification",
            "dismiss",
            {"notification_id": notification_id},
            blocking=False,
        )
