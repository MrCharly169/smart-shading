"""Pure navigation builders for the Smart Shading options flow."""

from __future__ import annotations

from typing import Any


def _name(item: dict[str, Any], fallback: str) -> str:
    """Return a trimmed customer-facing name."""
    return str(item.get("name") or fallback).strip()


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
    room: dict[str, Any], *, german: bool
) -> list[dict[str, Any]]:
    """Return every editable object for one room and no other room."""
    room_id = room["id"]
    room_name = _name(room, "Raum" if german else "Room")
    routes: list[dict[str, Any]] = [
        {
            "label": (
                f"Raumeinstellungen · {room_name}"
                if german
                else f"Room settings · {room_name}"
            ),
            "action": "manage_room",
            "room_id": room_id,
        },
        {
            "label": "+ Sonnensektor hinzufügen" if german else "+ Add sun sector",
            "action": "add_sector_flat",
            "room_id": room_id,
        },
    ]

    sector_fallback = "Sonnensektor" if german else "Sun sector"
    group_fallback = "Behanggruppe" if german else "Cover group"
    cover_fallback = "Behang" if german else "Cover"

    for sector in room.get("sectors", []):
        sector_name = _name(sector, sector_fallback)
        sector_context = {
            "room_id": room_id,
            "sector_id": sector["id"],
        }
        routes.extend(
            (
                {
                    "label": f"{sector_fallback} · {sector_name}",
                    "action": "manage_sector",
                    **sector_context,
                },
                {
                    "label": (
                        f"+ Behanggruppe hinzufügen · {sector_name}"
                        if german
                        else f"+ Add cover group · {sector_name}"
                    ),
                    "action": "add_layer_flat",
                    **sector_context,
                },
            )
        )

        for layer in sector.get("layers", []):
            layer_name = _name(layer, group_fallback)
            layer_context = {
                **sector_context,
                "layer_id": layer["id"],
            }
            routes.extend(
                (
                    {
                        "label": f"{group_fallback} · {sector_name} / {layer_name}",
                        "action": "manage_layer",
                        **layer_context,
                    },
                    {
                        "label": (
                            f"+ Behänge hinzufügen · {layer_name}"
                            if german
                            else f"+ Add covers · {layer_name}"
                        ),
                        "action": "add_covers_flat",
                        **layer_context,
                    },
                )
            )

            for cover_index, cover in enumerate(layer.get("covers", [])):
                cover_name = _name(
                    cover,
                    str(cover.get("entity") or f"{cover_fallback} {cover_index + 1}"),
                )
                routes.append(
                    {
                        "label": (
                            f"{cover_fallback} · {layer_name} / {cover_name}"
                        ),
                        "action": "manage_cover",
                        **layer_context,
                        "cover_index": cover_index,
                    }
                )

    return routes
