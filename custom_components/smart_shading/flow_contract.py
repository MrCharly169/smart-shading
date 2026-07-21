"""Mode contract shared by initial setup, options and migrations.

The customer chooses the setup variant exactly once.  Later options may change
the configuration inside that variant, but they must never replace the variant
stored in the config entry data.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Mapping


CONF_ADVANCED_MODE = "advanced_mode"
SETUP_EASY = "simple"
SETUP_ADVANCED = "complete"
SETUP_TYPES = (SETUP_EASY, SETUP_ADVANCED)

IMMUTABLE_OPTION_KEYS = frozenset({CONF_ADVANCED_MODE})


def setup_is_advanced(setup_type: str) -> bool:
    """Translate the one-time setup choice to the runtime mode flag."""
    if setup_type not in SETUP_TYPES:
        raise ValueError(f"Unsupported setup type: {setup_type}")
    return setup_type == SETUP_ADVANCED


def locked_advanced_mode(
    data: Mapping[str, Any], options: Mapping[str, Any] | None = None
) -> bool:
    """Return the immutable mode, with a legacy fallback for old beta entries.

    Schema 14 stores the authoritative value in ``data``.  Older beta entries
    sometimes copied it into ``options``; that fallback is used only when the
    data entry does not contain the flag yet.
    """
    if CONF_ADVANCED_MODE in data:
        return bool(data[CONF_ADVANCED_MODE])
    return bool((options or {}).get(CONF_ADVANCED_MODE, False))


def legacy_effective_advanced_mode(
    data: Mapping[str, Any], options: Mapping[str, Any] | None = None
) -> bool:
    """Return the mode that a pre-v14 entry actually used at runtime.

    Before schema 14, Home Assistant options were merged over entry data.  An
    explicitly stored option therefore won, while partial options without that
    key left the original entry choice intact.  Migration freezes that effective
    value once and then removes the option-level override.
    """
    if options and CONF_ADVANCED_MODE in options:
        return bool(options[CONF_ADVANCED_MODE])
    return bool(data.get(CONF_ADVANCED_MODE, False))


def legacy_effective_config(
    data: Mapping[str, Any], options: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Recreate a pre-v14 effective snapshot without inventing option defaults.

    Some early beta options payloads were partial while newer ones were full
    snapshots.  Migrations must merge the raw mappings first and normalize only
    afterwards; normalizing a partial options mapping on its own would inject an
    empty room list and mask the rooms stored in entry data.
    """
    result = deepcopy(dict(data))
    result.update(deepcopy(dict(options or {})))
    return result


def working_config(
    data: Mapping[str, Any], options: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Merge editable options while preserving the mode from entry data."""
    result = deepcopy(dict(data))
    result.update(
        {
            key: deepcopy(value)
            for key, value in dict(options or {}).items()
            if key not in IMMUTABLE_OPTION_KEYS
        }
    )
    result[CONF_ADVANCED_MODE] = locked_advanced_mode(data, options)
    return result


def editable_options(config: Mapping[str, Any]) -> dict[str, Any]:
    """Return an options payload without immutable setup properties."""
    return {
        key: deepcopy(value)
        for key, value in dict(config).items()
        if key not in IMMUTABLE_OPTION_KEYS
    }


def sun_source_for_sector(
    sector: Mapping[str, Any], *, advanced: bool
) -> str:
    """Return the single customer-selected source used by a sector.

    Older entries predate the explicit marker.  Lux remains available in both
    setup variants; an external on/off confirmation belongs to the Easy
    contract because the Advanced engine evaluates geometry plus Lux only.
    """
    allowed = {"geometry", "lux"} if advanced else {"geometry", "lux", "external"}
    stored = str(sector.get("sun_source") or "")
    if stored in allowed:
        return stored
    if not advanced and str(sector.get("sun_presence_entity") or "").strip():
        return "external"
    if str(sector.get("lux_sensor") or "").strip():
        return "lux"
    return "geometry"


def easy_temperature_source_configured(
    config: Mapping[str, Any], room: Mapping[str, Any]
) -> bool:
    """Return whether an enabled outdoor-temperature gate can read a source.

    A room-specific temperature sensor takes priority at runtime.  The optional
    house weather entity is the documented fallback and therefore also makes
    the gate complete.  Availability is intentionally not checked here: a
    temporarily unavailable source fails open at runtime instead of disabling
    the basic sun-position controller.
    """
    return bool(
        str(room.get("outdoor_temperature") or "").strip()
        or str(config.get("weather_entity") or "").strip()
    )


def config_with_runtime_overrides(
    config: Mapping[str, Any], overrides: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Fold entity-level configuration overrides into one editable snapshot.

    Home Assistant number/select entities persist their values separately so
    they can take effect immediately. The options wizard must display those
    effective values and save them back as the new base configuration instead
    of letting an invisible override win after the customer presses Save.
    """
    result = deepcopy(dict(config))
    scopes = dict(overrides or {})

    def scope(name: str) -> Mapping[str, Any]:
        values = scopes.get(name, {})
        return values if isinstance(values, Mapping) else {}

    house_values = scope("house").get("house", {})
    if isinstance(house_values, Mapping):
        for key, value in house_values.items():
            if key not in IMMUTABLE_OPTION_KEYS:
                result[str(key)] = deepcopy(value)

    def apply_values(
        target: dict[str, Any], values: Any, *, layer: bool = False
    ) -> None:
        if not isinstance(values, Mapping):
            return
        curve_updates: dict[int, dict[str, Any]] = {}
        for key, value in values.items():
            match = None
            if layer and isinstance(key, str):
                match = re.fullmatch(r"tilt_(elevation|value)_(\d+)", key)
            if match:
                point = curve_updates.setdefault(int(match.group(2)) - 1, {})
                point[
                    "elevation" if match.group(1) == "elevation" else "tilt"
                ] = deepcopy(value)
            else:
                target[str(key)] = deepcopy(value)
        if curve_updates:
            curve = deepcopy(list(target.get("tilt_curve", [])))
            required = max(curve_updates) + 1
            while len(curve) < required:
                curve.append({"elevation": 0.0, "tilt": 0.0})
            for index, point_values in curve_updates.items():
                curve[index].update(point_values)
            target["tilt_curve"] = curve

    room_values = scope("room")
    sector_values = scope("sector")
    layer_values = scope("layer")
    for room in result.get("rooms", []):
        apply_values(room, room_values.get(str(room.get("id")), {}))
        for sector in room.get("sectors", []):
            apply_values(
                sector, sector_values.get(str(sector.get("id")), {})
            )
            for layer_config in sector.get("layers", []):
                apply_values(
                    layer_config,
                    layer_values.get(str(layer_config.get("id")), {}),
                    layer=True,
                )
    return result
