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
        labels = [
            (f"Raumdaten · {room_name}", "manage_room_details"),
            (f"Sonnensektoren · {sectors}", "sector_hub"),
            (f"Behanggruppen · {groups}", "group_hub"),
            (f"Einzelne Behänge · {covers}", "cover_hub"),
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
        labels = [
            (f"Room details · {room_name}", "manage_room_details"),
            (f"Sun sectors · {sectors}", "sector_hub"),
            (f"Cover groups · {groups}", "group_hub"),
            (f"Individual covers · {covers}", "cover_hub"),
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


def build_sector_routes(
    room: dict[str, Any], *, german: bool
) -> list[dict[str, Any]]:
    """Return an add action followed by every configured sector."""
    room_id = room["id"]
    fallback = "Sonnensektor" if german else "Sun sector"
    routes = [
        {
            "label": "+ Sonnensektor hinzufügen" if german else "+ Add sun sector",
            "action": "add_sector_flat",
            "room_id": room_id,
        }
    ]
    routes.extend(
        {
            "label": _name(sector, fallback),
            "action": "manage_sector",
            "room_id": room_id,
            "sector_id": sector["id"],
        }
        for sector in room.get("sectors", [])
    )
    if len(routes) > 1:
        bottom_add = dict(routes[0])
        bottom_add["placement"] = "bottom"
        routes.append(bottom_add)
    return routes


def build_group_routes(
    room: dict[str, Any], *, german: bool
) -> list[dict[str, Any]]:
    """Return one add action and every group, including its sector context."""
    room_id = room["id"]
    routes = [
        {
            "label": "+ Behanggruppe hinzufügen" if german else "+ Add cover group",
            "action": "choose_sector_for_group",
            "room_id": room_id,
        }
    ]
    sector_fallback = "Sonnensektor" if german else "Sun sector"
    group_fallback = "Behanggruppe" if german else "Cover group"
    for sector in room.get("sectors", []):
        sector_name = _name(sector, sector_fallback)
        for layer in sector.get("layers", []):
            routes.append(
                {
                    "label": f"{_name(layer, group_fallback)} · {sector_name}",
                    "action": "manage_layer",
                    "room_id": room_id,
                    "sector_id": sector["id"],
                    "layer_id": layer["id"],
                }
            )
    if len(routes) > 1:
        bottom_add = dict(routes[0])
        bottom_add["placement"] = "bottom"
        routes.append(bottom_add)
    return routes


def build_cover_routes(
    room: dict[str, Any], *, german: bool
) -> list[dict[str, Any]]:
    """Return one add action and every cover with its group context."""
    room_id = room["id"]
    routes = [
        {
            "label": "+ Behänge hinzufügen" if german else "+ Add covers",
            "action": "choose_group_for_covers",
            "room_id": room_id,
        }
    ]
    group_fallback = "Behanggruppe" if german else "Cover group"
    cover_fallback = "Behang" if german else "Cover"
    for sector in room.get("sectors", []):
        for layer in sector.get("layers", []):
            group_name = _name(layer, group_fallback)
            for cover_index, cover in enumerate(layer.get("covers", [])):
                cover_name = _name(
                    cover,
                    f"{cover_fallback} {cover_index + 1}",
                )
                routes.append(
                    {
                        "label": f"{cover_name} · {group_name}",
                        "action": "manage_cover",
                        "room_id": room_id,
                        "sector_id": sector["id"],
                        "layer_id": layer["id"],
                        "cover_index": cover_index,
                        "cover_entity": cover.get("entity", ""),
                    }
                )
    if len(routes) > 1:
        bottom_add = dict(routes[0])
        bottom_add["placement"] = "bottom"
        routes.append(bottom_add)
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
