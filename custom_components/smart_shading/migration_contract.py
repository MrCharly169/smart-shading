"""Dependency-free migration helpers covered by the fast test suite."""

from __future__ import annotations

from typing import Any


def normalize_sector_sun_source(sector: dict[str, Any]) -> str:
    """Migrate legacy optional fields to exactly one authoritative source."""
    if sector.get("sun_presence_entity"):
        sector["sun_source"] = "external"
        sector["lux_sensor"] = ""
    elif sector.get("lux_sensor"):
        sector["sun_source"] = "lux"
        sector["sun_presence_entity"] = ""
    else:
        sector["sun_source"] = "geometry"
        sector["lux_sensor"] = ""
        sector["sun_presence_entity"] = ""
    return str(sector["sun_source"])
