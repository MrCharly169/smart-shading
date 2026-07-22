from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class SunPresenceStep:
    is_on: bool
    pending_target: bool | None
    pending_since: datetime | None
    pending_until: datetime | None
    transitioned: bool
    reason: str


def azimuth_inside(value: float, start: float, end: float) -> bool:
    """Return whether azimuth is inside a normal or north-wrapping range."""
    if start <= end:
        return start <= value <= end
    return value >= start or value <= end


def clamp_percent(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


_SLAT_TARGET_KEYS = {
    "open_tilt",
    "comfort_tilt",
    "solar_tilt",
    "heat_tilt",
    "safety_tilt",
}


def _migrated_slat_value(value):
    """Convert the legacy opening percentage to KNX slat closedness."""
    if isinstance(value, bool):
        return value
    try:
        return 100.0 - clamp_percent(float(value))
    except (TypeError, ValueError):
        return value


def migrate_slat_config(config: dict) -> dict:
    """Convert stored tilt targets from opening to KNX closedness semantics."""
    result = deepcopy(config)
    for room in result.get("rooms", []):
        for sector in room.get("sectors", []):
            for layer in sector.get("layers", []):
                profile = str(layer.get("profile", "venetian"))
                if profile not in {"venetian", "vertical_blind"}:
                    continue
                for key in _SLAT_TARGET_KEYS:
                    if key in layer:
                        layer[key] = _migrated_slat_value(layer[key])
                for point in layer.get("tilt_curve", []):
                    if isinstance(point, dict) and "tilt" in point:
                        point["tilt"] = _migrated_slat_value(point["tilt"])
    return result


def migrate_slat_overrides(overrides: dict) -> dict:
    """Convert persisted layer number overrides to KNX slat semantics."""
    if not isinstance(overrides, dict):
        return {}
    result = deepcopy(overrides)
    layers = result.get("layer", {})
    if not isinstance(layers, dict):
        return result
    for values in layers.values():
        if not isinstance(values, dict):
            continue
        for key, value in list(values.items()):
            if key in _SLAT_TARGET_KEYS or key.startswith("tilt_value_"):
                values[key] = _migrated_slat_value(value)
    return result


def sun_presence_step(
    *,
    now: datetime,
    lux: float | None,
    is_on: bool,
    pending_target: bool | None,
    pending_since: datetime | None,
    on_lux: float,
    off_lux: float,
    on_delay_minutes: float,
    off_delay_minutes: float,
) -> SunPresenceStep:
    """Advance lux hysteresis and delay state without Home Assistant dependencies."""
    if lux is None:
        return SunPresenceStep(
            is_on=is_on,
            pending_target=None,
            pending_since=None,
            pending_until=None,
            transitioned=False,
            reason="Lux sensor unavailable",
        )

    desired: bool | None = None
    if not is_on and lux >= on_lux:
        desired = True
    elif is_on and lux <= off_lux:
        desired = False

    if desired is None:
        return SunPresenceStep(
            is_on=is_on,
            pending_target=None,
            pending_since=None,
            pending_until=None,
            transitioned=False,
            reason="Inside hysteresis / stable",
        )

    delay = on_delay_minutes if desired else off_delay_minutes
    if pending_target != desired or pending_since is None:
        since = now
    else:
        since = pending_since
    until = since + timedelta(minutes=max(0.0, delay))

    if now >= until:
        return SunPresenceStep(
            is_on=desired,
            pending_target=None,
            pending_since=None,
            pending_until=None,
            transitioned=desired != is_on,
            reason="Sun ON delay completed" if desired else "Sun OFF delay completed",
        )

    return SunPresenceStep(
        is_on=is_on,
        pending_target=desired,
        pending_since=since,
        pending_until=until,
        transitioned=False,
        reason="Waiting for Sun ON delay" if desired else "Waiting for Sun OFF delay",
    )


def adaptive_tilt(elevation: float, fallback: float, points: list[dict]) -> float:
    result = float(fallback)
    for point in sorted(points, key=lambda item: float(item.get("elevation", 0))):
        if elevation >= float(point.get("elevation", 0)):
            result = float(point.get("tilt", result))
    return clamp_percent(result)


def finalize_sector_identity(
    sector: dict,
    *,
    name: str,
    short: str,
    id_factory,
) -> dict:
    """Return a sector config with a guaranteed internal identity.

    This helper is deliberately independent of Home Assistant so the compact
    wizard can be regression-tested without loading the frontend or Core.
    """
    result = dict(sector)
    clean_name = str(name or result.get("name") or "Sun sector").strip()
    clean_short = str(short or result.get("short") or "S").strip().upper()
    result["name"] = clean_name
    result["short"] = clean_short
    result["id"] = str(result.get("id") or id_factory(clean_name))
    result.setdefault("layers", [])
    return result


def needs_custom_sun_settings(*, preset: str, lux_sensor: str | None) -> bool:
    """Return whether the custom lux detail page must be shown."""
    return str(preset) == "custom" and bool(lux_sensor)


@dataclass(frozen=True, slots=True)
class CoverFeedbackDecision:
    """Classification of a cover state change against the last own target."""

    changed: bool
    expected: bool
    manual: bool
    position_complete: bool
    tilt_complete: bool
    reason: str


def parse_numeric_value(value) -> float | None:
    """Parse a Home Assistant numeric state without silently turning errors into zero.

    Home Assistant normally exposes machine-readable decimal strings, but some
    custom integrations may use localized separators. This parser accepts the
    common forms ``26398.72``, ``26,398.72``, ``26.398,72`` and ``26 398,72``.
    Invalid or non-finite values return ``None``.
    """
    import math
    import re

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None

    raw = str(value).strip()
    if not raw or raw.lower() in {"unknown", "unavailable", "none", "nan", "inf", "+inf", "-inf"}:
        return None

    raw = raw.replace("\u00a0", "").replace("\u202f", "").replace(" ", "").replace("'", "")
    match = re.match(r"^[+-]?[0-9][0-9.,]*", raw)
    if not match:
        return None
    token = match.group(0)

    if "," in token and "." in token:
        # The right-most separator is the decimal separator; the other one is grouping.
        if token.rfind(",") > token.rfind("."):
            token = token.replace(".", "").replace(",", ".")
        else:
            token = token.replace(",", "")
    elif "," in token:
        groups = token.split(",")
        if len(groups) > 2:
            token = "".join(groups)
        elif len(groups) == 2 and len(groups[1]) == 3 and 1 <= len(groups[0].lstrip("+-")) <= 3:
            token = "".join(groups)
        else:
            token = token.replace(",", ".")
    elif token.count(".") > 1:
        groups = token.split(".")
        if all(len(group) == 3 for group in groups[1:]):
            token = "".join(groups)
        else:
            return None

    try:
        number = float(token)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def classify_cover_feedback(
    *,
    old_position: float | None,
    new_position: float | None,
    old_tilt: float | None,
    new_tilt: float | None,
    old_state: str | None,
    new_state: str | None,
    target_position: float | None,
    target_tilt: float | None,
    command_age_seconds: float | None,
    position_tolerance: float = 2.0,
    tilt_tolerance: float = 3.0,
    command_timeout_seconds: float = 180.0,
    position_change_threshold: float = 2.0,
    tilt_change_threshold: float = 3.0,
) -> CoverFeedbackDecision:
    """Classify numeric cover feedback without trusting the cover state string.

    ``opening``, ``closing``, ``open`` and ``closed`` are informational only.
    Some integrations derive those values from command telegrams and configured
    travel times even when no physical movement occurred. Only numeric position
    or tilt feedback may therefore count as a relevant change here.
    """

    def changed(old: float | None, new: float | None, threshold: float) -> bool:
        return (
            old is not None
            and new is not None
            and abs(float(new) - float(old)) >= max(0.5, float(threshold))
        )

    position_changed = changed(old_position, new_position, position_change_threshold)
    tilt_changed = changed(old_tilt, new_tilt, tilt_change_threshold)
    state_changed = old_state != new_state
    any_changed = position_changed or tilt_changed
    if not any_changed:
        reason = "state_only_change_ignored" if state_changed else "no_relevant_change"
        return CoverFeedbackDecision(False, False, False, False, False, reason)

    fresh = command_age_seconds is not None and 0 <= command_age_seconds <= command_timeout_seconds
    position_complete = (
        target_position is not None
        and new_position is not None
        and abs(float(new_position) - float(target_position)) <= position_tolerance
    )
    tilt_complete = (
        target_tilt is not None
        and new_tilt is not None
        and abs(float(new_tilt) - float(target_tilt)) <= tilt_tolerance
    )
    if not fresh:
        return CoverFeedbackDecision(True, False, True, position_complete, tilt_complete, "no_fresh_own_command")

    checks: list[bool] = []
    if position_changed:
        if target_position is None:
            checks.append(False)
        else:
            old_distance = abs(float(old_position) - float(target_position))
            new_distance = abs(float(new_position) - float(target_position))
            checks.append(position_complete or new_distance < old_distance - 0.1)
    if tilt_changed:
        if target_tilt is None:
            checks.append(False)
        else:
            old_distance = abs(float(old_tilt) - float(target_tilt))
            new_distance = abs(float(new_tilt) - float(target_tilt))
            checks.append(tilt_complete or new_distance < old_distance - 0.1)

    expected = bool(checks) and all(checks)
    return CoverFeedbackDecision(
        changed=True,
        expected=expected,
        manual=not expected,
        position_complete=position_complete,
        tilt_complete=tilt_complete,
        reason="toward_own_target" if expected else "movement_away_from_or_without_own_target",
    )
