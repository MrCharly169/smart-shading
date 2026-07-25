from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    ADVANCED_FEATURES,
    ADVANCED_EXECUTION_ROOM_DEFAULTS,
    CONF_ADVANCED_MODE,
    CONF_ADVANCED_FEATURES,
    CONF_DIAGNOSTIC_LEVEL,
    DEFAULT_EVALUATION_DEBOUNCE_SECONDS,
    CONF_EVALUATION_INTERVAL,
    CONF_EXTERNAL_MOVEMENT_DETECTION,
    CONF_SUN_ENTITY,
    CONF_SUN_PRESENCE_ENTITY,
    CONF_ROOMS,
    CONF_TEST_MODE,
    CONF_WINDOW_RETURNS_TO_AUTOMATION,
    DAY_WINDOW_ALL_DAY,
    DEFAULT_EVALUATION_INTERVAL,
    DEFAULT_ALLOW_AUTOMATIC_REVERSE,
    DEFAULT_EVENING_RELEASE_TIME,
    DEFAULT_OPENING_ORDER,
    DEFAULT_SAFETY_BYPASSES_STAGGER,
    DEFAULT_STAGGER_SCOPE,
    DEFAULT_SUNSET_OFFSET_MINUTES,
    DEFAULT_SUN_ENTITY,
    DEFAULT_WINDOW_RETURNS_TO_AUTOMATION,
    DOMAIN,
    FEATURE_CONDITIONS,
    FEATURE_GLARE_PROTECTION,
    FEATURE_MAXIMUM_OPENING,
    FEATURE_NIGHT,
    FEATURE_SAFETY,
    FEATURE_SCHEDULE,
    FEATURE_TEMPERATURE,
    PLATFORMS,
    OPENING_ORDER_OPTIONS,
    PROFILE_DEFAULTS,
    ROOM_DEFAULTS,
    SUN_PRESETS,
    STAGGER_SCOPE_OPTIONS,
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


_ENGINE_REGISTRY = f"{DOMAIN}_engines"
SERVICE_PREVIEW_DAY = "preview_day"


async def _async_preview_day_service(hass: HomeAssistant, call) -> None:
    """Run a selected-date preview without exposing the executor.

    This is deliberately the single narrow card-facing service for Issue #79:
    it accepts only a persisted room identity and a calendar date, then calls
    the same non-actuating preview adapter as the diagnostic button.  No
    target, mode, or physical-command override is accepted here.
    """
    room_id = str(call.data["room_id"])
    entry_id = str(call.data.get("entry_id") or "")
    engines = hass.data.get(_ENGINE_REGISTRY, {})
    candidates = (
        [engines.get(entry_id)] if entry_id else list(engines.values())
    )
    for engine in candidates:
        if engine is None or room_id not in getattr(engine, "rooms", {}):
            continue
        preview = getattr(engine, "async_preview_room_day", None)
        if not callable(preview):
            break
        await preview(room_id, date=call.data.get("date"))
        return
    raise ServiceValidationError(
        f"No loaded Smart Shading room matches entry_id={entry_id!r}, room_id={room_id!r}"
    )


def _normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    """Add V4 defaults while preserving existing entity assignments."""
    result = deepcopy(config)
    result[CONF_SUN_ENTITY] = DEFAULT_SUN_ENTITY
    result.setdefault(CONF_ROOMS, [])
    result.setdefault(CONF_ADVANCED_MODE, False)
    result.setdefault(
        CONF_DIAGNOSTIC_LEVEL,
        "events" if result.get(CONF_TEST_MODE, False) else "off",
    )
    result.pop(CONF_TEST_MODE, None)
    result.setdefault(CONF_EVALUATION_INTERVAL, DEFAULT_EVALUATION_INTERVAL)
    # The interval is a recovery watchdog only.  Runtime input changes use a
    # small, persisted-as-config debounce to collapse one physical event burst
    # into one deterministic evaluation.
    result.setdefault("evaluation_debounce_seconds", DEFAULT_EVALUATION_DEBOUNCE_SECONDS)
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
    advanced_mode = bool(result.get(CONF_ADVANCED_MODE, False))

    for room in result[CONF_ROOMS]:
        room.pop("easy_temperature_gate", None)
        # Heat protection is a daytime function and is now always gated by
        # the room's general shading schedule. Discard the former bypass
        # instead of silently retaining winter/off-hours activation.
        room.pop("heat_outside_schedule", None)
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
        if advanced_mode:
            for key, value in ADVANCED_EXECUTION_ROOM_DEFAULTS.items():
                room.setdefault(key, deepcopy(value))
            # Do not let a malformed persisted value create an accidental
            # cross-room queue or silently change whether Safety bypasses it.
            scope = str(room.get("stagger_scope") or "")
            room["stagger_scope"] = (
                scope if scope in STAGGER_SCOPE_OPTIONS else DEFAULT_STAGGER_SCOPE
            )
            bypasses_stagger = room.get(
                "safety_bypasses_stagger", DEFAULT_SAFETY_BYPASSES_STAGGER
            )
            room["safety_bypasses_stagger"] = (
                bypasses_stagger
                if isinstance(bypasses_stagger, bool)
                else DEFAULT_SAFETY_BYPASSES_STAGGER
            )
            # Issue #79 originally made every diagnostic and experimental
            # capability visible for every Advanced room.  Preserve existing
            # configured behaviour, but migrate those capabilities into an
            # explicit per-room selection.  Test/support tools deliberately
            # remain off for legacy rooms: they never changed automation and
            # must not suddenly clutter a customer's dashboard.
            raw_features = room.get(CONF_ADVANCED_FEATURES)
            if isinstance(raw_features, (list, tuple, set)):
                room[CONF_ADVANCED_FEATURES] = [
                    feature
                    for feature in dict.fromkeys(str(value) for value in raw_features)
                    if feature in ADVANCED_FEATURES
                ]
            else:
                inferred: list[str] = []
                if room.get("schedule_enabled"):
                    inferred.append(FEATURE_SCHEDULE)
                if any(
                    str(room.get(key) or "").strip()
                    for key in ("indoor_temperature", "outdoor_temperature")
                ):
                    inferred.append(FEATURE_TEMPERATURE)
                if room.get("night_enabled"):
                    inferred.append(FEATURE_NIGHT)
                if room.get("safety_blockers"):
                    inferred.append(FEATURE_SAFETY)
                if any(
                    room.get(key)
                    for key in (
                        "irradiance_sensor",
                        "cloud_cover_sensor",
                        "weather_permission",
                        "occupancy_sensor",
                        "glare_sensor",
                    )
                ):
                    inferred.append(FEATURE_CONDITIONS)
                if any(
                    sector.get("protected_zones")
                    for sector in room.get("sectors", [])
                    if isinstance(sector, dict)
                ):
                    inferred.append(FEATURE_GLARE_PROTECTION)
                room[CONF_ADVANCED_FEATURES] = inferred
            if (
                any(
                    bool(cover.get("enforce_max_open_position", False))
                    for sector in room.get("sectors", [])
                    if isinstance(sector, dict)
                    for layer in sector.get("layers", [])
                    if isinstance(layer, dict)
                    for cover in layer.get("covers", [])
                    if isinstance(cover, dict)
                )
                and FEATURE_MAXIMUM_OPENING
                not in room[CONF_ADVANCED_FEATURES]
            ):
                room[CONF_ADVANCED_FEATURES].append(
                    FEATURE_MAXIMUM_OPENING
                )
        else:
            # Issue #79 execution controls are an Advanced-only contract.
            # Remove crafted or beta-era values as well as avoiding new
            # defaults, so an Easy entry has no hidden execution surface.
            for key in ADVANCED_EXECUTION_ROOM_DEFAULTS:
                room.pop(key, None)
            room.pop(CONF_ADVANCED_FEATURES, None)
        room.setdefault("normal_shading_temperature", room.get("comfort_temperature", 23.5))
        room.setdefault("sectors", [])
        room["active_months"] = [int(v) for v in room.get("active_months", range(1, 13))]
        room["active_weekdays"] = [int(v) for v in room.get("active_weekdays", range(7))]

        for sector in room.get("sectors", []):
            sector.setdefault("enabled", True)
            sector.setdefault(CONF_SUN_PRESENCE_ENTITY, "")
            source = sun_source_for_sector(
                sector, advanced=advanced_mode
            )
            sector["sun_source"] = source
            if source != "lux":
                sector["lux_sensor"] = ""
            if source != "external":
                sector[CONF_SUN_PRESENCE_ENTITY] = ""
            preset = str(sector.get("sun_preset", "medium"))
            if not advanced_mode and preset == "custom":
                preset = "medium"
                sector["sun_preset"] = preset
            if preset in SUN_PRESETS:
                sector.update(deepcopy(SUN_PRESETS[preset]))
            sector.setdefault("layers", [])
            # Protected zones are intentionally an Advanced-only capability.
            # Strip beta-era or crafted values from Easy entries rather than
            # retaining a hidden runtime surface outside the wizard contract.
            if advanced_mode:
                zones = sector.get("protected_zones", [])
                sector["protected_zones"] = (
                    [dict(zone) for zone in zones if isinstance(zone, dict)]
                    if isinstance(zones, list)
                    else []
                )
            else:
                sector.pop("protected_zones", None)
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
                if advanced_mode:
                    layer.setdefault(
                        "movement_seconds", room["movement_seconds"]
                    )
                    layer.setdefault(
                        "settling_seconds", room["settling_seconds"]
                    )
                else:
                    layer.pop("movement_seconds", None)
                    layer.pop("settling_seconds", None)
                if advanced_mode and profile_supports_tilt(profile):
                    opening_order = str(layer.get("opening_order") or "")
                    layer["opening_order"] = (
                        opening_order
                        if opening_order in OPENING_ORDER_OPTIONS
                        else DEFAULT_OPENING_ORDER
                    )
                else:
                    # The command-order override makes sense only for
                    # Advanced slatted profiles.  Never leave a hidden value
                    # behind on Easy or height-only cover groups.
                    layer.pop("opening_order", None)
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
                    if advanced_mode:
                        cover.setdefault("feedback_quality", "trusted")
                        cover.setdefault("verify_target", False)
                        automatic_reverse = cover.get(
                            "allow_automatic_reverse",
                            DEFAULT_ALLOW_AUTOMATIC_REVERSE,
                        )
                        cover["allow_automatic_reverse"] = (
                            automatic_reverse
                            if isinstance(automatic_reverse, bool)
                            else DEFAULT_ALLOW_AUTOMATIC_REVERSE
                        )
                    else:
                        cover.pop("feedback_quality", None)
                        cover.pop("verify_target", None)
                        cover.pop("allow_automatic_reverse", None)
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
    if not hass.services.has_service(DOMAIN, SERVICE_PREVIEW_DAY):
        async def async_handle_preview_day(call) -> None:
            await _async_preview_day_service(hass, call)

        hass.services.async_register(
            DOMAIN,
            SERVICE_PREVIEW_DAY,
            async_handle_preview_day,
            schema=vol.Schema(
                {
                    vol.Required("room_id"): str,
                    vol.Optional("date"): str,
                    vol.Optional("entry_id"): str,
                }
            ),
        )
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate earlier beta entries to the current Smart Shading data model."""
    if entry.version >= 20:
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
    # Normalize both snapshots under the immutable entry-data mode.  An old
    # option payload may contain a stale or crafted mode value, and must not
    # decide whether Advanced-only fields are retained or stripped.
    data_source = dict(data_source)
    data_source[CONF_ADVANCED_MODE] = fixed_advanced_mode
    effective_source = legacy_effective_config(data_source, option_source)
    effective_source[CONF_ADVANCED_MODE] = fixed_advanced_mode
    # v4.6.2 already used entry schema 15. Schema 16 normalized that stable
    # baseline, schema 17 persists each Advanced room's selected
    # customer capabilities. Existing glare rules are inferred so an update
    # never silently removes established protection. Schema 18 removes the
    # obsolete customer-selectable Sun entity and always uses ``sun.sun``.
    # Schema 19 removes the former heat-outside-schedule exception because
    # the general shading schedule now gates every daytime automation.
    # Schema 20 promotes the hard maximum opening into an explicit selected
    # Advanced feature while preserving every existing opt-in cover limit.
    data = _normalize_config(data_source)
    # Merge raw legacy values before adding defaults. This supports both the
    # old partial options format and the later full-snapshot format without an
    # injected ``rooms=[]`` masking the entry data.
    effective = _normalize_config(effective_source)
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
        entry, data=data, options=options, version=20
    )
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: SmartShadingConfigEntry
) -> bool:
    engine = SmartShadingEngine(hass, entry)
    entry.runtime_data = engine
    try:
        await engine.async_initialize()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        await engine.async_start()
    except Exception:
        # The selected-date service must never discover a half-initialized
        # engine after a setup failure.
        engine.async_stop()
        raise
    hass.data.setdefault(_ENGINE_REGISTRY, {})[entry.entry_id] = engine
    return True

async def async_unload_entry(
    hass: HomeAssistant, entry: SmartShadingConfigEntry
) -> bool:
    entry.runtime_data.async_stop()
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    # The engine is stopped regardless of platform-unload outcome, so do not
    # leave a stale service target reachable during retry/reload handling.
    hass.data.get(_ENGINE_REGISTRY, {}).pop(entry.entry_id, None)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove integration-owned notifications and registry records."""
    hass.data.get(_ENGINE_REGISTRY, {}).pop(entry.entry_id, None)
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
    device_registry = dr.async_get(hass)
    owned_devices = {
        device.id: device
        for device in dr.async_entries_for_config_entry(
            device_registry, entry.entry_id
        )
    }
    # HA removes the ConfigEntry itself before calling this hook. Depending on
    # cleanup timing, the device may already have lost its registry ownership;
    # our stable identifier still proves that it belongs to this entry.
    identifier_prefix = f"{entry.entry_id}_"
    for device in device_registry.devices.values():
        if any(
            domain == DOMAIN
            and (
                identifier == entry.entry_id
                or identifier.startswith(identifier_prefix)
            )
            for domain, identifier in device.identifiers
        ):
            owned_devices[device.id] = device
    entity_registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(
        entity_registry, entry.entry_id
    ):
        entity_registry.async_remove(entity.entity_id)
    for device in owned_devices.values():
        device_registry.async_remove_device(device.id)
