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
    CONF_ROOMS,
    CONF_TEST_MODE,
    DEFAULT_EVALUATION_INTERVAL,
    DOMAIN,
    PLATFORMS,
    PROFILE_DEFAULTS,
    ROOM_DEFAULTS,
    SUN_PRESETS,
    TILT_CURVE_PRESETS,
    TILT_PRESET_BALANCED,
)
from .controller import SmartShadingEngine
from .storage import RuntimeStore


type SmartShadingConfigEntry = ConfigEntry[SmartShadingEngine]


def _normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    """Add V4 defaults while preserving existing entity assignments."""
    result = deepcopy(config)
    result.setdefault(CONF_ROOMS, [])
    result.setdefault(CONF_ADVANCED_MODE, False)
    result.setdefault(CONF_DIAGNOSTIC_LEVEL, "events" if result.get(CONF_TEST_MODE, False) else "off")
    result.setdefault(CONF_EVALUATION_INTERVAL, DEFAULT_EVALUATION_INTERVAL)
    result.setdefault("invert_tilt_globally", False)
    old_curve = [(10.0, 90.0), (20.0, 50.0), (40.0, 15.0), (60.0, 10.0)]

    for room in result[CONF_ROOMS]:
        for key, value in ROOM_DEFAULTS.items():
            room.setdefault(key, deepcopy(value))
        room.setdefault("normal_shading_temperature", room.get("comfort_temperature", 23.5))
        room.setdefault("sectors", [])
        room["active_months"] = [int(v) for v in room.get("active_months", range(1, 13))]
        room["active_weekdays"] = [int(v) for v in room.get("active_weekdays", range(7))]

        for sector in room.get("sectors", []):
            sector.setdefault("enabled", True)
            preset = str(sector.get("sun_preset", "medium"))
            if preset in SUN_PRESETS:
                sector.update(deepcopy(SUN_PRESETS[preset]))
            sector.setdefault("layers", [])
            for layer in sector.get("layers", []):
                profile = layer.get("profile", "venetian")
                defaults = PROFILE_DEFAULTS.get(profile, PROFILE_DEFAULTS["venetian"])
                for key, value in defaults.items():
                    layer.setdefault(key, deepcopy(value))
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
                    cover.setdefault("invert_position", False)
                    cover.setdefault("invert_tilt", False)
                    cover.setdefault("max_open_position", 100.0)
                    cover.setdefault("safety_position_override", None)
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
    if entry.version >= 9:
        return True
    data = _normalize_config(dict(entry.data))
    options = _normalize_config(dict(entry.options)) if entry.options else {}
    # Earlier beta versions defaulted to 120 seconds. Move untouched defaults
    # to the new customer-friendly 20-minute interval.
    if int(data.get(CONF_EVALUATION_INTERVAL, 120)) == 120:
        data[CONF_EVALUATION_INTERVAL] = DEFAULT_EVALUATION_INTERVAL
    if options and int(options.get(CONF_EVALUATION_INTERVAL, 120)) == 120:
        options[CONF_EVALUATION_INTERVAL] = DEFAULT_EVALUATION_INTERVAL
    hass.config_entries.async_update_entry(
        entry, data=data, options=options, version=9
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
