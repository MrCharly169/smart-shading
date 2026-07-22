"""Executable UI contract for the Smart Shading setup and options flows.

This module deliberately has no Home Assistant dependencies.  It is imported by
the production config flow and can therefore be exercised in the fast test
suite to catch Easy/Advanced and cover-profile inconsistencies before an HA lab
is started.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping


EASY_ROOM_FIELDS = ("name", "outdoor_temperature")
ADVANCED_ROOM_FIELDS = (
    "name",
    "outdoor_temperature",
    "indoor_temperature",
    "safety_blockers",
)
ADVANCED_ROOM_EDIT_FIELDS = ADVANCED_ROOM_FIELDS + (
    "indoor_temperature_name",
    "outdoor_temperature_name",
)

SECTOR_IDENTITY_FIELDS = ("direction", "name", "short", "sun_source")
LUX_CONFIRMATION_FIELDS = ("lux_sensor", "sun_preset")
EXTERNAL_CONFIRMATION_FIELDS = ("sun_presence_entity",)

EASY_SCHEDULE_FIELDS = ("schedule_profile", "default_pause_mode")
ADVANCED_SCHEDULE_FIELDS = EASY_SCHEDULE_FIELDS + ("heat_during_pause",)

BASE_COVER_FIELDS = (
    "name",
    "short",
    "lock",
    "window",
    "window_safe_state",
    "window_policy",
)
POSITION_COVER_FIELDS = ("max_open_position", "invert_position")
TILT_COVER_FIELDS = ("invert_tilt",)


def room_fields(advanced: bool, *, editing: bool = False) -> tuple[str, ...]:
    """Return the only fields allowed on the room page."""
    if not advanced:
        return EASY_ROOM_FIELDS
    return ADVANCED_ROOM_EDIT_FIELDS if editing else ADVANCED_ROOM_FIELDS


def customer_options(options: Iterable[str], advanced: bool) -> list[str]:
    """Hide every free-form Custom choice in Easy."""
    values = list(options)
    return values if advanced else [value for value in values if value != "custom"]


def schedule_fields(advanced: bool) -> tuple[str, ...]:
    """Heat-specific schedule controls belong to Advanced only."""
    return ADVANCED_SCHEDULE_FIELDS if advanced else EASY_SCHEDULE_FIELDS


def layer_has_advanced_settings(
    advanced: bool, capabilities: Mapping[str, bool]
) -> bool:
    """Binary covers never expose meaningless percentage target pages."""
    return advanced and not bool(capabilities.get("binary"))


def cover_fields(capabilities: Mapping[str, bool]) -> tuple[str, ...]:
    """Return fields supported by one physical cover profile."""
    fields = list(BASE_COVER_FIELDS)
    if capabilities.get("supports_position"):
        fields.extend(POSITION_COVER_FIELDS)
    if capabilities.get("supports_tilt"):
        fields.extend(TILT_COVER_FIELDS)
    return tuple(fields)
