"""Pure customer-facing navigation builders for the options flow."""

from __future__ import annotations

from typing import Any


def _name(item: dict[str, Any], fallback: str) -> str:
    """Return a trimmed customer-facing name."""
    return str(item.get("name") or fallback).strip()


def _counts(room: dict[str, Any]) -> tuple[int, int, int]:
    sectors = list(room.get("sectors", []))
    layers = [layer for sector in sectors for layer in sector.get("layers", [])]
    covers = [cover for layer in layers for cover in layer.get("covers", [])]
    return len(sectors), len(layers), len(covers)


def _cover_count(count: int, *, german: bool) -> str:
    if german:
        return f"{count} Behang" if count == 1 else f"{count} Behänge"
    return f"{count} cover" if count == 1 else f"{count} covers"


def build_main_room_routes(
    rooms: list[dict[str, Any]], *, german: bool
) -> list[dict[str, Any]]:
    """Return exactly one main-menu route for every configured room."""
    room_label = "Raum" if german else "Room"
    fallback = "Raum" if german else "Room"
    return [
        {
            "label": f"{room_label} · {_name(room, fallback)}",
            "action": "room_hub",
            "room_id": room["id"],
        }
        for room in rooms
    ]


def build_room_routes(
    room: dict[str, Any], *, german: bool, full: bool
) -> list[dict[str, Any]]:
    """Return task categories for one room, never its internal object tree."""
    room_id = room["id"]
    room_name = _name(room, "Raum" if german else "Room")
    sectors, groups, covers = _counts(room)
    if german:
        sector_label = f"{sectors} Sektor" if sectors == 1 else f"{sectors} Sektoren"
        group_label = f"{groups} Gruppe" if groups == 1 else f"{groups} Gruppen"
        labels = [
            (f"Raumdaten · {room_name}", "manage_room_details"),
            (
                f"Beschattungsstruktur · {sector_label} · "
                f"{group_label} · {_cover_count(covers, german=True)}",
                "structure_hub",
            ),
        ]
        if full:
            labels.extend(
                [
                    ("Automatik", "manage_automation"),
                    ("Nachtfunktion", "manage_night"),
                    ("Pause und manuelle Bedienung", "manage_pause"),
                    ("Sicherheit und Bedingungen", "manage_conditions"),
                ]
            )
        labels.append(("Raum entfernen", "manage_room_maintenance"))
    else:
        sector_label = f"{sectors} sector" if sectors == 1 else f"{sectors} sectors"
        group_label = f"{groups} group" if groups == 1 else f"{groups} groups"
        labels = [
            (f"Room details · {room_name}", "manage_room_details"),
            (
                f"Shading structure · {sector_label} · "
                f"{group_label} · {_cover_count(covers, german=False)}",
                "structure_hub",
            ),
        ]
        if full:
            labels.extend(
                [
                    ("Automation", "manage_automation"),
                    ("Night function", "manage_night"),
                    ("Pause and manual control", "manage_pause"),
                    ("Safety and conditions", "manage_conditions"),
                ]
            )
        labels.append(("Remove room", "manage_room_maintenance"))
    return [
        {"label": label, "action": action, "room_id": room_id}
        for label, action in labels
    ]


def build_structure_routes(
    room: dict[str, Any], *, german: bool
) -> list[dict[str, Any]]:
    """Return complete sector branches followed by one creation action."""
    room_id = room["id"]
    fallback = "Sonnensektor" if german else "Sun sector"
    routes: list[dict[str, Any]] = []
    for sector in room.get("sectors", []):
        layers = list(sector.get("layers", []))
        cover_count = sum(len(layer.get("covers", [])) for layer in layers)
        group_count = len(layers)
        group_label = (
            f"{group_count} Gruppe" if german and group_count == 1
            else f"{group_count} Gruppen" if german
            else f"{group_count} group" if group_count == 1
            else f"{group_count} groups"
        )
        suffix = f"{group_label} · {_cover_count(cover_count, german=german)}"
        routes.append(
            {
                "label": f"{_name(sector, fallback)} · {suffix}",
                "action": "sector_hub",
                "room_id": room_id,
                "sector_id": sector["id"],
            }
        )
    routes.append(
        {
            "label": (
                "+ Vollständigen Beschattungsbereich hinzufügen"
                if german
                else "+ Add complete shading area"
            ),
            "action": "add_sector_flat",
            "room_id": room_id,
            "placement": "bottom",
        }
    )
    return routes


def build_sector_routes(
    room: dict[str, Any], sector: dict[str, Any], *, german: bool,
    advanced: bool = False,
) -> list[dict[str, Any]]:
    """Return sector settings and its direct child groups."""
    room_id = room["id"]
    sector_id = sector["id"]
    source = str(sector.get("sun_source", "geometry"))
    source_labels = {
        "geometry": "Nur Sonnenstand" if german else "Sun position only",
        "lux": "Lokaler Lux-Sensor" if german else "Local Lux sensor",
        "external": "Externer Ein/Aus-Sensor" if german else "External on/off sensor",
    }
    routes: list[dict[str, Any]] = [
        {
            "label": "Sektoreinstellungen" if german else "Sector settings",
            "action": "manage_sector",
            "room_id": room_id,
            "sector_id": sector_id,
        },
        {
            "label": (
                f"Sonnenquelle · {source_labels.get(source, source)}"
                if german
                else f"Sun source · {source_labels.get(source, source)}"
            ),
            "action": "manage_sector_source",
            "room_id": room_id,
            "sector_id": sector_id,
        },
    ]
    if advanced:
        zone_count = len(
            [zone for zone in sector.get("protected_zones", []) if isinstance(zone, dict)]
        )
        routes.append(
            {
                "label": (
                    f"Blendschutz · {zone_count} Zone"
                    if german and zone_count == 1
                    else f"Blendschutz · {zone_count} Zonen"
                    if german
                    else f"Glare protection · {zone_count} zone"
                    if zone_count == 1
                    else f"Glare protection · {zone_count} zones"
                ),
                "action": "protected_zones_hub",
                "room_id": room_id,
                "sector_id": sector_id,
            }
        )
    group_fallback = "Behanggruppe" if german else "Cover group"
    for layer in sector.get("layers", []):
        count = len(layer.get("covers", []))
        suffix = _cover_count(count, german=german)
        routes.append(
            {
                "label": f"{_name(layer, group_fallback)} · {suffix}",
                "action": "group_hub",
                "room_id": room_id,
                "sector_id": sector_id,
                "layer_id": layer["id"],
            }
        )
    routes.append(
        {
            "label": "+ Behanggruppe hinzufügen" if german else "+ Add cover group",
            "action": "add_layer_flat",
            "room_id": room_id,
            "sector_id": sector_id,
            "placement": "bottom",
        }
    )
    return routes


def build_protected_zone_routes(
    room: dict[str, Any], sector: dict[str, Any], *, german: bool
) -> list[dict[str, Any]]:
    """Return one stable route per Advanced-only protected zone."""
    room_id = room["id"]
    sector_id = sector["id"]
    fallback = "Schutzzone" if german else "Protected zone"
    routes: list[dict[str, Any]] = []
    for index, zone in enumerate(sector.get("protected_zones", [])):
        if not isinstance(zone, dict):
            continue
        zone_id = str(zone.get("id") or "").strip()
        if not zone_id:
            continue
        enabled = bool(zone.get("enabled", True))
        state = (
            "Aktiv" if german and enabled else "Inaktiv" if german else
            "Active" if enabled else "Inactive"
        )
        routes.append(
            {
                "label": f"{_name(zone, f'{fallback} {index + 1}')} · {state}",
                "action": "manage_protected_zone",
                "room_id": room_id,
                "sector_id": sector_id,
                "zone_id": zone_id,
            }
        )
    routes.append(
        {
            "label": "+ Schutzzone hinzufügen" if german else "+ Add protected zone",
            "action": "add_protected_zone",
            "room_id": room_id,
            "sector_id": sector_id,
            "placement": "bottom",
        }
    )
    return routes


def build_group_routes(
    room: dict[str, Any], sector: dict[str, Any], layer: dict[str, Any], *, german: bool
) -> list[dict[str, Any]]:
    """Return group settings, its covers and one scoped add action."""
    room_id = room["id"]
    sector_id = sector["id"]
    layer_id = layer["id"]
    routes: list[dict[str, Any]] = [
        {
            "label": "Gruppe und Behangtyp" if german else "Group and cover type",
            "action": "manage_layer",
            "room_id": room_id,
            "sector_id": sector_id,
            "layer_id": layer_id,
        },
        {
            "label": "Profileinstellungen" if german else "Profile settings",
            "action": "manage_layer_profile",
            "room_id": room_id,
            "sector_id": sector_id,
            "layer_id": layer_id,
        },
    ]
    cover_fallback = "Behang" if german else "Cover"
    for cover_index, cover in enumerate(layer.get("covers", [])):
        cover_name = _name(cover, f"{cover_fallback} {cover_index + 1}")
        routes.append(
            {
                "label": cover_name,
                "action": "cover_settings_hub",
                "room_id": room_id,
                "sector_id": sector_id,
                "layer_id": layer_id,
                "cover_index": cover_index,
                "cover_entity": cover.get("entity", ""),
            }
        )
    routes.append(
        {
            "label": "+ Behänge hinzufügen" if german else "+ Add covers",
            "action": "add_covers_flat",
            "room_id": room_id,
            "sector_id": sector_id,
            "layer_id": layer_id,
            "placement": "bottom",
        }
    )
    return routes


def build_cover_routes(room: dict[str, Any], *, german: bool) -> list[dict[str, Any]]:
    """Return legacy room-wide cover routes without duplicate add actions."""
    routes: list[dict[str, Any]] = []
    for sector in room.get("sectors", []):
        for layer in sector.get("layers", []):
            routes.extend(
                route
                for route in build_group_routes(room, sector, layer, german=german)
                if route["action"] == "cover_settings_hub"
            )
    return routes


def night_is_configured(room: dict[str, Any]) -> bool:
    """Return whether a next-Night-end pause has a reliable release source."""
    if not bool(room.get("night_enabled", False)):
        return False
    source = str(room.get("night_source", "entity"))
    if source == "sun":
        return True
    return source == "entity" and bool(str(room.get("night_entity", "")).strip())


def pause_modes_for_room(room: dict[str, Any]) -> list[str]:
    """Return only pause choices that can actually finish in this room."""
    modes = ["next_sunrise", "next_sunset", "timed", "manual"]
    if night_is_configured(room):
        modes.insert(2, "next_night_end")
    return modes
