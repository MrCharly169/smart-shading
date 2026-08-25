"""Pure decision primitives for Smart Shading.

This module intentionally has no Home Assistant imports and does not execute
services.  It is the seam between Home Assistant state collection and the
later command planner/executor:

``InputSnapshot -> DecisionPipeline -> DecisionResult``

The engine can construct a normalized :class:`InputSnapshot` from live states,
feed it together with room/sector facts into :class:`DecisionContext`, and use
the result to plan commands.  The same pipeline is used for simulations and
day previews, which prevents a second, approximate decision implementation
from drifting away from production behaviour.

The public dataclasses use immutable tuples and copied read-only mappings for
outputs.  Callers may therefore safely retain traces for diagnostics, exports
or later command verification without changing the decision that produced
them.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from enum import Enum, IntEnum
from math import atan2, cos, degrees, isfinite, radians, tan
from types import MappingProxyType
from typing import Any, Iterable, Mapping


# Keep mode values independent from Home Assistant and ``const.py``.  They are
# deliberately the stable public strings already exposed by Smart Shading.
MODE_DISABLED = "disabled"
MODE_PAUSED = "paused"
MODE_SAFETY = "safety"
MODE_IDLE = "idle"
MODE_OPEN = "open"
MODE_COMFORT = "comfort"
MODE_SOLAR = "solar"
MODE_GLARE = "glare"
MODE_HEAT = "heat"
MODE_NIGHT = "night"


class QualityState(str, Enum):
    """Normalized health of one configured input.

    ``VALID`` is the only state that may begin ordinary solar/comfort action.
    The engine decides which inputs are required for a given room and passes
    them through :attr:`DecisionContext.normal_input_keys`.
    """

    VALID = "valid"
    PENDING = "pending"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    INVALID_VALUE = "invalid_value"
    CONTRADICTORY = "contradictory"
    NOT_CONFIGURED = "not_configured"


class InputKind(str, Enum):
    """Expected normalized shape for :func:`normalize_input`."""

    ANY = "any"
    NUMBER = "number"
    BOOLEAN = "boolean"
    TEXT = "text"


class DecisionPriority(IntEnum):
    """Central, immutable Smart Shading decision ordering.

    These values are product priorities, never user-configurable numbers.  A
    candidate-provided priority is normalized by :class:`DecisionResolver` so
    rules in separate modules cannot accidentally override Safety.
    """

    FALLBACK = 0
    IDLE = 100
    OPEN = 200
    COMFORT = 300
    SOLAR = 400
    GLARE = 425
    INPUT_HOLD = 450
    HEAT = 500
    NIGHT = 600
    NIGHT_SOURCE_HOLD = 650
    SAFETY_SOURCE_HOLD = 675
    MANUAL = 700
    SAFETY = 800


class CommandResultStatus(str, Enum):
    """Execution outcome vocabulary shared by traces and future executors."""

    NOT_PLANNED = "not_planned"
    PLANNED = "planned"
    SIMULATED = "simulated"
    SENT = "sent"
    QUEUED = "queued"
    SUPPRESSED = "suppressed"
    BLOCKED = "blocked"
    TARGET_REACHED = "target_reached"
    FAILED = "failed"
    TARGET_NOT_REACHED = "target_not_reached"
    CANCELLED = "cancelled"


class ProtectedZoneStatus(str, Enum):
    """Validation and geometric result state for a protected zone."""

    VALID = "valid"
    INVALID = "invalid"
    INACTIVE = "inactive"
    MISS = "miss"
    HIT = "hit"


class TraceOutcome(str, Enum):
    """How one candidate participated in the final resolver result."""

    WINNER = "winner"
    REJECTED = "rejected"


def _freeze_mapping(values: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
    """Copy a mapping into a shallow immutable diagnostic payload."""

    return MappingProxyType(dict(values or {}))


def _enum_value(value: Any, enum_type: type[Enum], default: Enum) -> Enum:
    if isinstance(value, enum_type):
        return value
    # Adapters intentionally use independent enums (for example the execution
    # planner's lifecycle enum).  Enum.__str__ is ``Class.MEMBER`` rather than
    # its wire value, so always unwrap another Enum before normalizing it.
    if isinstance(value, Enum):
        value = value.value
    try:
        return enum_type(str(value))
    except (TypeError, ValueError):
        return default


def _as_float(value: Any) -> float | None:
    """Parse localized finite numeric input without Home Assistant helpers."""

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
        return parsed if isfinite(parsed) else None
    if not isinstance(value, str):
        return None
    text = value.strip().replace("\u00a0", "").replace(" ", "")
    if not text:
        return None
    # Support both ``12.345,67`` and ``12,345.67`` in exported/simulated
    # values.  The right-most separator is considered the decimal separator.
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed if isfinite(parsed) else None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value == 1:
            return True
        if value == 0:
            return False
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"on", "true", "yes", "1"}:
            return True
        if normalized in {"off", "false", "no", "0"}:
            return False
    return None


def _unavailable_raw(value: Any) -> bool:
    return value is None or (
        isinstance(value, str)
        and value.strip().lower() in {"", "none", "null", "unknown", "unavailable"}
    )


def _duration(value: timedelta | float | int | None) -> timedelta | None:
    if value is None:
        return None
    if isinstance(value, timedelta):
        return value
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return timedelta(seconds=seconds) if isfinite(seconds) and seconds >= 0 else None


@dataclass(frozen=True)
class InputValue:
    """One source value after parsing, unit normalization and health grading."""

    key: str
    entity_id: str | None
    raw_value: Any
    value: float | bool | str | None
    quality: QualityState
    unit: str | None = None
    observed_at: datetime | None = None
    reason_code: str = "input_not_configured"
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", str(self.key))
        object.__setattr__(self, "entity_id", self.entity_id or None)
        object.__setattr__(
            self,
            "quality",
            _enum_value(self.quality, QualityState, QualityState.INVALID_VALUE),
        )
        object.__setattr__(self, "details", _freeze_mapping(self.details))

    @property
    def valid(self) -> bool:
        """Whether this input is safe to begin normal automation."""

        return self.quality is QualityState.VALID

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "entity_id": self.entity_id,
            "raw_value": self.raw_value,
            "value": self.value,
            "quality": self.quality.value,
            "unit": self.unit,
            "observed_at": _serialize_datetime(self.observed_at),
            "reason_code": self.reason_code,
            "details": _serialize_mapping(self.details),
        }


def normalize_input(
    key: str,
    *,
    raw_value: Any = None,
    entity_id: str | None = None,
    expected: InputKind | str = InputKind.ANY,
    unit: str | None = None,
    observed_at: datetime | None = None,
    evaluated_at: datetime | None = None,
    max_age: timedelta | float | int | None = None,
    quality: QualityState | str | None = None,
    configured: bool | None = None,
    details: Mapping[str, Any] | None = None,
) -> InputValue:
    """Normalize a raw source without consulting Home Assistant.

    ``quality`` may preserve an upstream state such as ``pending`` or
    ``contradictory``.  An unavailable or unparseable raw value still wins over
    a mistakenly supplied ``valid`` quality.  ``max_age`` accepts either a
    :class:`datetime.timedelta` or seconds and produces ``stale`` only when
    both timestamps are supplied by the caller.

    With no explicit ``configured`` flag, a raw virtual value counts as
    configured.  This makes deterministic simulations possible without fake
    Home Assistant entity IDs; a missing entity and missing raw value becomes
    ``not_configured``.
    """

    kind = _enum_value(expected, InputKind, InputKind.ANY)
    explicit_quality = (
        _enum_value(quality, QualityState, QualityState.INVALID_VALUE)
        if quality is not None
        else None
    )
    inferred_configured = bool(entity_id) or raw_value is not None
    is_configured = inferred_configured if configured is None else bool(configured)
    base_details = dict(details or {})
    base_details.update({"expected": kind.value})

    if not is_configured:
        return InputValue(
            key=key,
            entity_id=entity_id,
            raw_value=raw_value,
            value=None,
            quality=QualityState.NOT_CONFIGURED,
            unit=unit,
            observed_at=observed_at,
            reason_code="input_not_configured",
            details=base_details,
        )

    if _unavailable_raw(raw_value):
        return InputValue(
            key=key,
            entity_id=entity_id,
            raw_value=raw_value,
            value=None,
            quality=QualityState.UNAVAILABLE,
            unit=unit,
            observed_at=observed_at,
            reason_code="input_unavailable",
            details=base_details,
        )

    if kind is InputKind.NUMBER:
        normalized: float | bool | str | None = _as_float(raw_value)
    elif kind is InputKind.BOOLEAN:
        normalized = _as_bool(raw_value)
    elif kind is InputKind.TEXT:
        normalized = str(raw_value).strip()
    else:
        normalized = raw_value

    if normalized is None or (kind is InputKind.TEXT and normalized == ""):
        return InputValue(
            key=key,
            entity_id=entity_id,
            raw_value=raw_value,
            value=None,
            quality=QualityState.INVALID_VALUE,
            unit=unit,
            observed_at=observed_at,
            reason_code="input_invalid_value",
            details=base_details,
        )

    # A caller may deliberately model a Lux debounce as pending, or a source
    # disagreement as contradictory.  Keep those states visible in the trace.
    if explicit_quality is not None and explicit_quality is not QualityState.VALID:
        base_details["quality_source"] = "explicit"
        return InputValue(
            key=key,
            entity_id=entity_id,
            raw_value=raw_value,
            value=normalized,
            quality=explicit_quality,
            unit=unit,
            observed_at=observed_at,
            reason_code=f"input_{explicit_quality.value}",
            details=base_details,
        )

    allowed_age = _duration(max_age)
    if allowed_age is not None:
        base_details["max_age_seconds"] = allowed_age.total_seconds()
    if (
        allowed_age is not None
        and observed_at is not None
        and evaluated_at is not None
        and observed_at + allowed_age < evaluated_at
    ):
        age = (evaluated_at - observed_at).total_seconds()
        base_details.update(
            {"quality_source": "freshness", "age_seconds": age}
        )
        return InputValue(
            key=key,
            entity_id=entity_id,
            raw_value=raw_value,
            value=normalized,
            quality=QualityState.STALE,
            unit=unit,
            observed_at=observed_at,
            reason_code="input_stale",
            details=base_details,
        )

    base_details.setdefault("quality_source", "normalized")
    return InputValue(
        key=key,
        entity_id=entity_id,
        raw_value=raw_value,
        value=normalized,
        quality=QualityState.VALID,
        unit=unit,
        observed_at=observed_at,
        reason_code="input_valid",
        details=base_details,
    )


@dataclass(frozen=True)
class InputSnapshot:
    """A timestamped, normalized collection of inputs for one evaluation."""

    evaluated_at: datetime
    inputs: Mapping[str, InputValue] = field(default_factory=dict)
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        copied: dict[str, InputValue] = {}
        for key, value in dict(self.inputs).items():
            if not isinstance(value, InputValue):
                raise TypeError(f"InputSnapshot input {key!r} must be an InputValue")
            copied[str(key)] = value
        object.__setattr__(self, "inputs", _freeze_mapping(copied))
        object.__setattr__(self, "details", _freeze_mapping(self.details))

    @classmethod
    def empty(cls, evaluated_at: datetime) -> "InputSnapshot":
        """Create an explicit empty snapshot for deterministic tests."""

        return cls(evaluated_at=evaluated_at)

    def get(self, key: str) -> InputValue:
        """Return a synthetic ``not_configured`` value when the key is absent."""

        value = self.inputs.get(key)
        if value is not None:
            return value
        return InputValue(
            key=key,
            entity_id=None,
            raw_value=None,
            value=None,
            quality=QualityState.NOT_CONFIGURED,
            reason_code="input_not_configured",
        )

    def quality(self, key: str) -> QualityState:
        return self.get(key).quality

    def quality_failures(self, keys: Iterable[str]) -> Mapping[str, QualityState]:
        """Return every required key that is not ``valid``."""

        return _freeze_mapping(
            {
                str(key): self.get(str(key)).quality
                for key in keys
                if not self.get(str(key)).valid
            }
        )

    def with_overrides(
        self, overrides: Mapping[str, InputValue | Any]
    ) -> "InputSnapshot":
        """Return a new snapshot for a virtual simulation, never mutate self."""

        copied = dict(self.inputs)
        for key, override in dict(overrides).items():
            token = str(key)
            if isinstance(override, InputValue):
                copied[token] = override
                continue
            existing = copied.get(token)
            copied[token] = normalize_input(
                token,
                raw_value=override,
                entity_id=existing.entity_id if existing else None,
                expected=(existing.details.get("expected", InputKind.ANY.value)
                          if existing else InputKind.ANY),
                unit=existing.unit if existing else None,
                observed_at=self.evaluated_at,
                evaluated_at=self.evaluated_at,
                configured=True,
            )
        return InputSnapshot(
            evaluated_at=self.evaluated_at,
            inputs=copied,
            details=self.details,
        )

    def refreshed_at(self, evaluated_at: datetime) -> "InputSnapshot":
        """Regrade every retained source at a virtual evaluation instant.

        Preview used to change only the snapshot timestamp.  That left a
        previously-valid source valid forever even if its configured max age
        had elapsed.  Replaying normalization preserves raw values and
        explicit upstream quality while recalculating freshness deterministically.
        """
        refreshed: dict[str, InputValue] = {}
        for key, input_value in self.inputs.items():
            details = dict(input_value.details)
            expected = details.get("expected", InputKind.ANY.value)
            max_age = details.get("max_age_seconds")
            explicit_quality = (
                input_value.quality
                if details.get("quality_source") == "explicit"
                else None
            )
            refreshed[key] = normalize_input(
                key,
                raw_value=input_value.raw_value,
                entity_id=input_value.entity_id,
                expected=expected,
                unit=input_value.unit,
                observed_at=input_value.observed_at,
                evaluated_at=evaluated_at,
                max_age=max_age,
                quality=explicit_quality,
                configured=input_value.quality is not QualityState.NOT_CONFIGURED,
                details=details,
            )
        return InputSnapshot(
            evaluated_at=evaluated_at,
            inputs=refreshed,
            details=self.details,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "evaluated_at": _serialize_datetime(self.evaluated_at),
            "inputs": {key: value.as_dict() for key, value in self.inputs.items()},
            "details": _serialize_mapping(self.details),
        }


def _validate_percent(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    parsed = _as_float(value)
    if parsed is None or not 0.0 <= parsed <= 100.0:
        raise ValueError(f"{field_name} must be a finite percentage between 0 and 100")
    return parsed


@dataclass(frozen=True)
class Target:
    """Logical cover target in Smart Shading's established semantics.

    Position uses Home Assistant semantics (``0`` closed, ``100`` open).
    Tilt uses the KNX closedness scale (``0`` open, ``100`` closed).  Thus a
    lower position and a higher tilt are more protective for a protected zone.
    """

    position: float | None = None
    tilt: float | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "position", _validate_percent(self.position, "position"))
        object.__setattr__(self, "tilt", _validate_percent(self.tilt, "tilt"))
        object.__setattr__(self, "details", _freeze_mapping(self.details))

    def as_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "tilt": self.tilt,
            "details": _serialize_mapping(self.details),
        }


@dataclass(frozen=True)
class SunGeometry:
    """Geometric inputs used by the protected-zone calculation.

    ``window_lower_height_m`` and ``window_upper_height_m`` describe the
    vertical aperture at the façade.  A zone is hit when its reverse-projected
    vertical ray intersects that aperture.  Azimuth/facade azimuth are
    optional; if both are supplied their relative angle also produces a
    lateral ray offset.
    """

    elevation_degrees: float | None
    azimuth_degrees: float | None = None
    facade_azimuth_degrees: float | None = None
    window_lower_height_m: float = 0.0
    window_upper_height_m: float = 2.4
    direct_sun: bool = True
    sector_azimuth_active: bool = True


@dataclass(frozen=True)
class ProtectedZone:
    """Advanced-only geometry and target adjustment for a protected area.

    ``cover_entity`` scopes a calculated zone to one physical cover.  The
    legacy ``group_ids`` scope remains readable for pre-migration records.
    ``target_position`` and ``target_tilt`` are optional; a geometrically hit
    zone without either still appears in traces but does not alter the target.
    """

    zone_id: str
    name: str
    sector_id: str
    distance_m: float | None
    lower_height_m: float | None
    upper_height_m: float | None
    group_ids: tuple[str, ...] = ()
    cover_entity: str = ""
    enabled: bool = True
    lateral_min_m: float | None = None
    lateral_max_m: float | None = None
    target_position: float | None = None
    target_tilt: float | None = None
    calculation_mode: str = "fixed"
    window_width_m: float | None = None
    window_height_m: float | None = None
    window_sill_height_m: float | None = None
    object_distance_m: float | None = None
    object_center_height_m: float | None = None
    object_height_m: float | None = None
    object_lateral_center_m: float | None = None
    object_width_m: float | None = None
    target_lateral_center_m: float | None = None
    target_lateral_width_m: float | None = None
    condition_count: int = 0
    conditions_met: bool | None = True
    sun_confirmation_enabled: bool = True
    minimum_sun_elevation_degrees: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "zone_id", str(self.zone_id or ""))
        object.__setattr__(self, "name", str(self.name or ""))
        object.__setattr__(self, "sector_id", str(self.sector_id or ""))
        object.__setattr__(
            self, "cover_entity", str(self.cover_entity or "")
        )
        object.__setattr__(
            self,
            "group_ids",
            tuple(str(group) for group in (self.group_ids or ()) if str(group)),
        )

    @classmethod
    def from_config(
        cls,
        values: Mapping[str, Any],
        *,
        sector_id: str | None = None,
    ) -> "ProtectedZone":
        """Create a zone from the persisted Options-flow dictionary.

        The wizard stores ``id`` while the pure contract calls the same stable
        identity ``zone_id``.  Passing ``sector_id`` is useful for older
        entries whose nested sector owns the zone but did not serialize that
        redundant field yet.
        """

        sun_confirmation_enabled = _as_bool(
            values.get("sun_confirmation_enabled", True)
        )
        return cls(
            zone_id=str(values.get("id") or values.get("zone_id") or ""),
            name=str(values.get("name") or ""),
            sector_id=str(sector_id or values.get("sector_id") or ""),
            distance_m=values.get("distance_m"),
            lower_height_m=values.get("lower_height_m"),
            upper_height_m=values.get("upper_height_m"),
            group_ids=tuple(values.get("group_ids") or ()),
            cover_entity=str(values.get("cover_entity") or ""),
            enabled=bool(values.get("enabled", True)),
            lateral_min_m=values.get("lateral_min_m"),
            lateral_max_m=values.get("lateral_max_m"),
            target_position=values.get("target_position"),
            target_tilt=values.get("target_tilt"),
            calculation_mode=str(values.get("calculation_mode") or "fixed"),
            window_width_m=values.get("window_width_m"),
            window_height_m=values.get("window_height_m"),
            window_sill_height_m=values.get("window_sill_height_m"),
            object_distance_m=values.get("object_distance_m"),
            object_center_height_m=values.get("object_center_height_m"),
            object_height_m=values.get("object_height_m"),
            object_lateral_center_m=values.get(
                "object_lateral_center_m"
            ),
            object_width_m=values.get("object_width_m"),
            target_lateral_center_m=values.get("target_lateral_center_m"),
            target_lateral_width_m=values.get("target_lateral_width_m"),
            condition_count=len(values.get("conditions") or ()),
            conditions_met=(True if not values.get("conditions") else None),
            sun_confirmation_enabled=(
                True
                if sun_confirmation_enabled is None
                else sun_confirmation_enabled
            ),
            minimum_sun_elevation_degrees=values.get(
                "minimum_sun_elevation_degrees"
            ),
        )


@dataclass(frozen=True)
class ProtectedZoneValidation:
    """Result of validating persisted protected-zone geometry."""

    zone_id: str
    status: ProtectedZoneStatus
    reason_code: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", _freeze_mapping(self.details))

    @property
    def valid(self) -> bool:
        return self.status is ProtectedZoneStatus.VALID


@dataclass(frozen=True)
class ProtectedZoneEvaluation:
    """One zone's validation, scope and ray-intersection result."""

    zone_id: str
    name: str
    sector_id: str
    status: ProtectedZoneStatus
    reason_code: str
    target: Target | None = None
    projected_height_range_m: tuple[float, float] | None = None
    lateral_offset_m: float | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", _freeze_mapping(self.details))

    @property
    def hit(self) -> bool:
        return self.status is ProtectedZoneStatus.HIT

    def as_dict(self) -> dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "name": self.name,
            "sector_id": self.sector_id,
            "status": self.status.value,
            "reason_code": self.reason_code,
            "target": self.target.as_dict() if self.target else None,
            "projected_height_range_m": list(self.projected_height_range_m)
            if self.projected_height_range_m
            else None,
            "lateral_offset_m": self.lateral_offset_m,
            "details": _serialize_mapping(self.details),
        }


@dataclass(frozen=True)
class ProtectedTargetAdjustment:
    """Result of applying every relevant hit zone to a solar target."""

    target: Target | None
    hit_zone_ids: tuple[str, ...] = ()
    applied_zone_ids: tuple[str, ...] = ()
    reason_code: str = "no_protected_zone_hit"
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "hit_zone_ids", tuple(self.hit_zone_ids))
        object.__setattr__(self, "applied_zone_ids", tuple(self.applied_zone_ids))
        object.__setattr__(self, "details", _freeze_mapping(self.details))


def _finite_measurement(value: Any) -> float | None:
    parsed = _as_float(value)
    return parsed if parsed is not None and isfinite(parsed) else None


def validate_protected_zone(zone: ProtectedZone) -> ProtectedZoneValidation:
    """Validate a persisted protected zone without rejecting normal Solar.

    The caller should retain an invalid evaluation in the decision trace while
    simply ignoring it for target adjustment.  This is the deliberate safe
    fallback required for incomplete customer geometry.
    """

    errors: list[str] = []
    if not zone.zone_id:
        errors.append("zone_id_required")
    if not zone.name:
        errors.append("zone_name_required")
    if not zone.sector_id:
        errors.append("sector_id_required")

    distance = _finite_measurement(zone.distance_m)
    lower = _finite_measurement(zone.lower_height_m)
    upper = _finite_measurement(zone.upper_height_m)
    if distance is None or distance < 0:
        errors.append("distance_invalid")
    if lower is None or upper is None or lower >= upper:
        errors.append("height_range_invalid")

    lateral_min = _finite_measurement(zone.lateral_min_m)
    lateral_max = _finite_measurement(zone.lateral_max_m)
    if (zone.lateral_min_m is None) != (zone.lateral_max_m is None):
        errors.append("lateral_range_incomplete")
    elif zone.lateral_min_m is not None and (
        lateral_min is None or lateral_max is None or lateral_min > lateral_max
    ):
        errors.append("lateral_range_invalid")

    for key, raw in (
        ("target_position", zone.target_position),
        ("target_tilt", zone.target_tilt),
    ):
        if raw is None:
            continue
        parsed = _finite_measurement(raw)
        if parsed is None or not 0.0 <= parsed <= 100.0:
            errors.append(f"{key}_invalid")

    calculation_mode = str(zone.calculation_mode or "fixed")
    if calculation_mode not in {
        "fixed",
        "top_down",
        "curtain",
        "curtain_closes_left_to_right",
        "curtain_closes_right_to_left",
        "binary",
        "vertical_slats",
    }:
        errors.append("calculation_mode_invalid")
    window_width = _finite_measurement(zone.window_width_m)
    window_height = _finite_measurement(zone.window_height_m)
    window_sill = (
        _finite_measurement(zone.window_sill_height_m)
        if zone.window_sill_height_m is not None
        else 0.0
    )
    lateral_center = _finite_measurement(zone.target_lateral_center_m)
    lateral_width = _finite_measurement(zone.target_lateral_width_m)
    if calculation_mode != "fixed":
        if not zone.cover_entity and len(zone.group_ids) != 1:
            errors.append("calculated_zone_cover_required")
        if window_width is None or not 0.1 <= window_width <= 30:
            errors.append("window_width_invalid")
        if window_height is None or not 0.1 <= window_height <= 15:
            errors.append("window_height_invalid")
        if (
            window_sill is None
            or not 0 <= window_sill <= 10
            or (
                window_height is not None
                and window_sill + window_height > 15
            )
        ):
            errors.append("window_sill_height_invalid")
        if lateral_center is None or not -30 <= lateral_center <= 30:
            errors.append("target_lateral_center_invalid")
        if lateral_width is None or not 0.0 <= lateral_width <= 30:
            errors.append("target_lateral_width_invalid")
    minimum_elevation = _finite_measurement(
        zone.minimum_sun_elevation_degrees
    )
    if zone.minimum_sun_elevation_degrees is not None and (
        minimum_elevation is None or not 0.0 <= minimum_elevation <= 90.0
    ):
        errors.append("minimum_sun_elevation_invalid")

    details = {
        "distance_m": distance,
        "lower_height_m": lower,
        "upper_height_m": upper,
        "lateral_min_m": lateral_min,
        "lateral_max_m": lateral_max,
        "calculation_mode": calculation_mode,
        "window_width_m": window_width,
        "window_height_m": window_height,
        "window_sill_height_m": window_sill,
        "target_lateral_center_m": lateral_center,
        "target_lateral_width_m": lateral_width,
        "sun_confirmation_enabled": zone.sun_confirmation_enabled,
        "minimum_sun_elevation_degrees": minimum_elevation,
    }
    if errors:
        return ProtectedZoneValidation(
            zone_id=zone.zone_id,
            status=ProtectedZoneStatus.INVALID,
            reason_code="protected_zone_invalid",
            details={**details, "errors": tuple(errors)},
        )
    return ProtectedZoneValidation(
        zone_id=zone.zone_id,
        status=ProtectedZoneStatus.VALID,
        reason_code="protected_zone_valid",
        details=details,
    )


def _validate_sun_geometry(
    geometry: SunGeometry | None,
) -> tuple[bool, str, Mapping[str, Any]]:
    if geometry is None:
        return False, "sun_geometry_missing", _freeze_mapping()
    elevation = _finite_measurement(geometry.elevation_degrees)
    if elevation is None:
        return False, "sun_elevation_invalid", _freeze_mapping()
    lower = _finite_measurement(geometry.window_lower_height_m)
    upper = _finite_measurement(geometry.window_upper_height_m)
    if lower is None or upper is None or lower >= upper:
        return False, "window_aperture_invalid", _freeze_mapping()
    for label, raw in (
        ("azimuth_degrees", geometry.azimuth_degrees),
        ("facade_azimuth_degrees", geometry.facade_azimuth_degrees),
    ):
        if raw is not None and _finite_measurement(raw) is None:
            return False, f"{label}_invalid", _freeze_mapping()
    return True, "sun_geometry_valid", _freeze_mapping(
        {
            "elevation_degrees": elevation,
            "window_lower_height_m": lower,
            "window_upper_height_m": upper,
        }
    )


def _relative_azimuth(sun: float, facade: float) -> float:
    """Return the signed angular offset from a façade's outward normal."""

    return ((sun - facade + 180.0) % 360.0) - 180.0


def _zone_target(zone: ProtectedZone) -> Target | None:
    if zone.target_position is None and zone.target_tilt is None:
        return None
    # ``validate_protected_zone`` has already checked ranges before this is
    # called.  Conversion nevertheless keeps the output canonical floats.
    return Target(position=zone.target_position, tilt=zone.target_tilt)


def _calculated_zone_target(
    zone: ProtectedZone,
    *,
    projected_height_range: tuple[float, float],
    lateral_offset: float | None,
) -> tuple[Target | None, dict[str, Any]]:
    """Calculate a least-restrictive target for an object-protection zone.

    The configuration is deliberately local to the window: heights are
    measured from its lower edge and lateral values from its centre.  A
    top-down cover only needs to cover the *lowest* projected sun ray.  The
    remaining aperture therefore stays as large as possible while the whole
    protected rectangle is in shade.
    """
    mode = str(zone.calculation_mode or "fixed")
    if mode == "fixed":
        return _zone_target(zone), {"calculation": "fixed_target"}

    width = _finite_measurement(zone.window_width_m)
    height = _finite_measurement(zone.window_height_m)
    center = _finite_measurement(zone.target_lateral_center_m)
    target_width = _finite_measurement(zone.target_lateral_width_m)
    if None in {width, height, center, target_width, lateral_offset}:
        return None, {"calculation": "geometry_incomplete"}
    assert width is not None and height is not None
    assert center is not None and target_width is not None and lateral_offset is not None
    sill = _finite_measurement(zone.window_sill_height_m) or 0.0

    projected_lateral = (
        center - target_width / 2.0 + lateral_offset,
        center + target_width / 2.0 + lateral_offset,
    )
    window_lateral = (-width / 2.0, width / 2.0)
    if max(projected_lateral[0], window_lateral[0]) > min(
        projected_lateral[1], window_lateral[1]
    ):
        return None, {
            "calculation": "object_ray_outside_window",
            "projected_lateral_range_m": projected_lateral,
            "window_lateral_range_m": window_lateral,
        }

    details: dict[str, Any] = {
        "calculation": mode,
        "projected_lateral_range_m": projected_lateral,
        "window_lateral_range_m": window_lateral,
    }
    clipped_lateral = (
        max(projected_lateral[0], window_lateral[0]),
        min(projected_lateral[1], window_lateral[1]),
    )
    details["clipped_lateral_range_m"] = clipped_lateral
    if mode == "top_down":
        # Home Assistant position semantics are 0 = closed, 100 = open.  A
        # top-down blind covers from the upper edge down to the aperture edge.
        aperture_edge = max(
            0.0,
            min(height, projected_height_range[0] - sill),
        )
        position = max(0.0, min(100.0, aperture_edge / height * 100.0))
        details["open_aperture_edge_m"] = aperture_edge
        details["calculated_position"] = position
        return Target(position=position), details
    if mode == "curtain":
        # A two-panel curtain is treated as opening symmetrically from the
        # centre.  The free central aperture may extend only up to the nearer
        # edge of the projected protected area.
        nearest_edge = max(
            0.0,
            abs((projected_lateral[0] + projected_lateral[1]) / 2.0)
            - target_width / 2.0,
        )
        position = max(0.0, min(100.0, nearest_edge / (width / 2.0) * 100.0))
        details["central_opening_half_width_m"] = nearest_edge
        details["calculated_position"] = position
        return Target(position=position), details
    if mode == "curtain_closes_left_to_right":
        # Material enters from the left and its moving edge follows the right
        # edge of the ray footprint clipped to the real window aperture.
        # At first contact this produces a small movement; the target closes
        # progressively as the sun footprint travels across the window.
        movement_edge = clipped_lateral[1]
        position = max(
            0.0,
            min(100.0, (window_lateral[1] - movement_edge) / width * 100.0),
        )
        details["curtain_closing_direction"] = "left_to_right"
        details["curtain_movement_edge_m"] = movement_edge
        details["geometry_driven_target"] = True
        details["calculated_position"] = position
        return Target(position=position), details
    if mode == "curtain_closes_right_to_left":
        # Material enters from the right; the moving edge follows the left
        # edge of the clipped ray footprint.  This is the mirror image of the
        # left-to-right calculation and remains monotonic during a sun sweep.
        movement_edge = clipped_lateral[0]
        position = max(
            0.0,
            min(100.0, (movement_edge - window_lateral[0]) / width * 100.0),
        )
        details["curtain_closing_direction"] = "right_to_left"
        details["curtain_movement_edge_m"] = movement_edge
        details["geometry_driven_target"] = True
        details["calculated_position"] = position
        return Target(position=position), details
    if mode == "binary":
        details["calculated_position"] = 0.0
        return Target(position=0.0), details
    if mode == "vertical_slats":
        # This is intentionally a test-capable geometrical baseline.  Real
        # vane dimensions and actuator calibration can refine it later; the
        # normal component of direct sun determines the protective tilt.
        relative = abs(degrees(atan2(lateral_offset, max(0.001, zone.distance_m or 0.001))))
        tilt = max(0.0, min(100.0, (1.0 - relative / 90.0) * 100.0))
        details["calculated_tilt"] = tilt
        return Target(tilt=tilt), details
    return None, {"calculation": "geometry_mode_not_supported"}


def evaluate_protected_zone(
    zone: ProtectedZone,
    geometry: SunGeometry | None,
    *,
    sector_id: str | None = None,
    group_id: str | None = None,
    cover_entity: str | None = None,
) -> ProtectedZoneEvaluation:
    """Evaluate one protected zone with no side effects.

    A ray is reverse-projected from the protected height range to the window
    aperture.  This keeps the calculation useful with a simple customer
    measurement (distance + lower/upper protected height) while making every
    assumption explicit in the returned details.
    """

    validation = validate_protected_zone(zone)
    if not validation.valid:
        return ProtectedZoneEvaluation(
            zone_id=zone.zone_id,
            name=zone.name,
            sector_id=zone.sector_id,
            status=ProtectedZoneStatus.INVALID,
            reason_code=validation.reason_code,
            details=validation.details,
        )
    if not zone.enabled:
        return ProtectedZoneEvaluation(
            zone_id=zone.zone_id,
            name=zone.name,
            sector_id=zone.sector_id,
            status=ProtectedZoneStatus.INACTIVE,
            reason_code="protected_zone_disabled",
        )
    # A zone is nested below a sector in persisted configuration.  Applying it
    # without a concrete sector context would turn that scope into a wildcard,
    # which is unsafe for a real multi-facade installation.  Group scope was
    # already fail-closed; sector scope must be too.
    if sector_id is None:
        return ProtectedZoneEvaluation(
            zone_id=zone.zone_id,
            name=zone.name,
            sector_id=zone.sector_id,
            status=ProtectedZoneStatus.INACTIVE,
            reason_code="protected_zone_sector_context_required",
        )
    if str(sector_id) != zone.sector_id:
        return ProtectedZoneEvaluation(
            zone_id=zone.zone_id,
            name=zone.name,
            sector_id=zone.sector_id,
            status=ProtectedZoneStatus.INACTIVE,
            reason_code="protected_zone_other_sector",
            details={"requested_sector_id": str(sector_id)},
        )
    if zone.cover_entity:
        if cover_entity is None:
            return ProtectedZoneEvaluation(
                zone_id=zone.zone_id,
                name=zone.name,
                sector_id=zone.sector_id,
                status=ProtectedZoneStatus.INACTIVE,
                reason_code="protected_zone_cover_context_required",
                details={"cover_entity": zone.cover_entity},
            )
        if str(cover_entity) != zone.cover_entity:
            return ProtectedZoneEvaluation(
                zone_id=zone.zone_id,
                name=zone.name,
                sector_id=zone.sector_id,
                status=ProtectedZoneStatus.INACTIVE,
                reason_code="protected_zone_other_cover",
                details={
                    "requested_cover_entity": str(cover_entity),
                    "cover_entity": zone.cover_entity,
                },
            )
    elif zone.group_ids:
        if group_id is None:
            return ProtectedZoneEvaluation(
                zone_id=zone.zone_id,
                name=zone.name,
                sector_id=zone.sector_id,
                status=ProtectedZoneStatus.INACTIVE,
                reason_code="protected_zone_group_context_required",
                details={"group_ids": zone.group_ids},
            )
        if str(group_id) not in zone.group_ids:
            return ProtectedZoneEvaluation(
                zone_id=zone.zone_id,
                name=zone.name,
                sector_id=zone.sector_id,
                status=ProtectedZoneStatus.INACTIVE,
                reason_code="protected_zone_other_group",
                details={"requested_group_id": str(group_id), "group_ids": zone.group_ids},
            )

    if zone.condition_count and zone.conditions_met is not True:
        return ProtectedZoneEvaluation(
            zone_id=zone.zone_id,
            name=zone.name,
            sector_id=zone.sector_id,
            status=ProtectedZoneStatus.INACTIVE,
            reason_code=(
                "protected_zone_conditions_not_met"
                if zone.conditions_met is False
                else "protected_zone_conditions_unavailable"
            ),
            details={
                "condition_count": zone.condition_count,
                "conditions_met": zone.conditions_met,
            },
        )

    geometry_valid, geometry_reason, geometry_details = _validate_sun_geometry(geometry)
    if not geometry_valid:
        return ProtectedZoneEvaluation(
            zone_id=zone.zone_id,
            name=zone.name,
            sector_id=zone.sector_id,
            status=ProtectedZoneStatus.INACTIVE,
            reason_code=geometry_reason,
            details=geometry_details,
        )
    assert geometry is not None  # Narrowed by _validate_sun_geometry.
    elevation = _finite_measurement(geometry.elevation_degrees)
    assert elevation is not None
    if elevation <= 0.0:
        return ProtectedZoneEvaluation(
            zone_id=zone.zone_id,
            name=zone.name,
            sector_id=zone.sector_id,
            status=ProtectedZoneStatus.MISS,
            reason_code="protected_zone_sun_below_horizon",
            details=geometry_details,
        )
    if not geometry.sector_azimuth_active:
        return ProtectedZoneEvaluation(
            zone_id=zone.zone_id,
            name=zone.name,
            sector_id=zone.sector_id,
            status=ProtectedZoneStatus.INACTIVE,
            reason_code="protected_zone_sector_azimuth_inactive",
            details=geometry_details,
        )
    minimum_elevation = (
        _finite_measurement(zone.minimum_sun_elevation_degrees) or 0.0
    )
    if elevation < minimum_elevation:
        return ProtectedZoneEvaluation(
            zone_id=zone.zone_id,
            name=zone.name,
            sector_id=zone.sector_id,
            status=ProtectedZoneStatus.MISS,
            reason_code="protected_zone_below_minimum_sun_elevation",
            details={
                **dict(geometry_details),
                "minimum_sun_elevation_degrees": minimum_elevation,
            },
        )
    if zone.sun_confirmation_enabled and not geometry.direct_sun:
        return ProtectedZoneEvaluation(
            zone_id=zone.zone_id,
            name=zone.name,
            sector_id=zone.sector_id,
            status=ProtectedZoneStatus.INACTIVE,
            reason_code="protected_zone_direct_sun_inactive",
            details={
                **dict(geometry_details),
                "sun_confirmation_enabled": True,
            },
        )

    distance = _finite_measurement(zone.distance_m)
    lower = _finite_measurement(zone.lower_height_m)
    upper = _finite_measurement(zone.upper_height_m)
    calculated_mode = str(zone.calculation_mode or "fixed") != "fixed"
    window_lower = (
        (
            _finite_measurement(zone.window_sill_height_m)
            if zone.window_sill_height_m is not None
            else 0.0
        )
        if calculated_mode
        else _finite_measurement(geometry.window_lower_height_m)
    )
    window_upper = (
        (
            float(window_lower)
            + float(_finite_measurement(zone.window_height_m) or 0.0)
        )
        if calculated_mode
        else _finite_measurement(geometry.window_upper_height_m)
    )
    assert None not in {distance, lower, upper, window_lower, window_upper}
    vertical_drop = float(distance) * tan(radians(elevation))
    projected = (float(lower) + vertical_drop, float(upper) + vertical_drop)
    details: dict[str, Any] = {
        **geometry_details,
        "distance_m": distance,
        "protected_height_range_m": (lower, upper),
        "window_height_range_m": (window_lower, window_upper),
        "projected_height_range_m": projected,
        "vertical_drop_m": vertical_drop,
    }

    lateral_offset: float | None = None
    sun_azimuth = _finite_measurement(geometry.azimuth_degrees)
    facade_azimuth = _finite_measurement(geometry.facade_azimuth_degrees)
    lateral_bounds_configured = (
        zone.lateral_min_m is not None or zone.lateral_max_m is not None
    )
    if (lateral_bounds_configured or calculated_mode) and (
        sun_azimuth is None or facade_azimuth is None
    ):
        # A customer supplied a lateral protected range, so applying it with
        # unknown lateral ray geometry would silently make it a full-width
        # wildcard.  Keep ordinary solar behaviour and expose the missing fact.
        return ProtectedZoneEvaluation(
            zone_id=zone.zone_id,
            name=zone.name,
            sector_id=zone.sector_id,
            status=ProtectedZoneStatus.INACTIVE,
            reason_code=(
                "protected_zone_lateral_geometry_required"
                if lateral_bounds_configured
                else "calculated_zone_lateral_geometry_required"
            ),
            projected_height_range_m=projected,
            details=details,
        )
    if sun_azimuth is not None and facade_azimuth is not None:
        relative = _relative_azimuth(sun_azimuth, facade_azimuth)
        details["relative_azimuth_degrees"] = relative
        if abs(relative) >= 90.0:
            return ProtectedZoneEvaluation(
                zone_id=zone.zone_id,
                name=zone.name,
                sector_id=zone.sector_id,
                status=ProtectedZoneStatus.MISS,
                reason_code="protected_zone_sun_behind_facade",
                projected_height_range_m=projected,
                details=details,
            )
        # ``tan(±90°)`` and the corresponding zero normal component are
        # intentionally avoided by the grazing-sun check above.
        lateral_offset = float(distance) * tan(radians(relative))
        details["lateral_offset_m"] = lateral_offset
        lateral_min = _finite_measurement(zone.lateral_min_m)
        lateral_max = _finite_measurement(zone.lateral_max_m)
        if lateral_min is not None and lateral_max is not None and not (
            lateral_min <= lateral_offset <= lateral_max
        ):
            return ProtectedZoneEvaluation(
                zone_id=zone.zone_id,
                name=zone.name,
                sector_id=zone.sector_id,
                status=ProtectedZoneStatus.MISS,
                reason_code="protected_zone_lateral_miss",
                projected_height_range_m=projected,
                lateral_offset_m=lateral_offset,
                details=details,
            )

        # ``distance`` is measured perpendicular to the facade plane.  At an
        # oblique azimuth, the ray travels further before crossing that plane,
        # so its vertical projection must be scaled by ``1 / cos(relative)``.
        normal_component = cos(radians(relative))
        assert normal_component > 0.0
        vertical_drop = float(distance) * tan(radians(elevation)) / normal_component
        projected = (float(lower) + vertical_drop, float(upper) + vertical_drop)
        details["projected_height_range_m"] = projected
        details["vertical_drop_m"] = vertical_drop

    vertical_overlap = max(projected[0], float(window_lower)) <= min(
        projected[1], float(window_upper)
    )
    if not vertical_overlap:
        return ProtectedZoneEvaluation(
            zone_id=zone.zone_id,
            name=zone.name,
            sector_id=zone.sector_id,
            status=ProtectedZoneStatus.MISS,
            reason_code="protected_zone_vertical_miss",
            projected_height_range_m=projected,
            lateral_offset_m=lateral_offset,
            details=details,
        )

    target, calculation_details = _calculated_zone_target(
        zone,
        projected_height_range=projected,
        lateral_offset=lateral_offset,
    )
    details.update(calculation_details)
    if calculated_mode and target is None:
        reason = str(calculation_details.get("calculation") or "geometry_incomplete")
        return ProtectedZoneEvaluation(
            zone_id=zone.zone_id,
            name=zone.name,
            sector_id=zone.sector_id,
            status=(
                ProtectedZoneStatus.MISS
                if reason == "object_ray_outside_window"
                else ProtectedZoneStatus.INACTIVE
            ),
            reason_code=f"calculated_zone_{reason}",
            projected_height_range_m=projected,
            lateral_offset_m=lateral_offset,
            details=details,
        )

    return ProtectedZoneEvaluation(
        zone_id=zone.zone_id,
        name=zone.name,
        sector_id=zone.sector_id,
        status=ProtectedZoneStatus.HIT,
        reason_code="protected_zone_direct_sun_hit",
        target=target,
        projected_height_range_m=projected,
        lateral_offset_m=lateral_offset,
        details=details,
    )


def evaluate_protected_zones(
    zones: Iterable[ProtectedZone],
    geometry: SunGeometry | None,
    *,
    sector_id: str | None = None,
    group_id: str | None = None,
    cover_entity: str | None = None,
) -> tuple[ProtectedZoneEvaluation, ...]:
    """Evaluate all configured zones, retaining inactive/invalid trace facts."""

    return tuple(
        evaluate_protected_zone(
            zone,
            geometry,
            sector_id=sector_id,
            group_id=group_id,
            cover_entity=cover_entity,
        )
        for zone in zones
    )


def apply_protected_zones(
    ordinary_target: Target | None,
    evaluations: Iterable[ProtectedZoneEvaluation],
) -> ProtectedTargetAdjustment:
    """Apply all hit zone adjustments using deterministic protective semantics.

    Position is minimized (more closed) and tilt is maximized (more closed).
    This means several simultaneous zones naturally select the most protective
    valid target without introducing another top-level decision mode.
    """

    hits = sorted(
        (evaluation for evaluation in evaluations if evaluation.hit),
        key=lambda evaluation: evaluation.zone_id,
    )
    hit_ids = tuple(evaluation.zone_id for evaluation in hits)
    if not hits:
        return ProtectedTargetAdjustment(
            target=ordinary_target,
            reason_code="no_protected_zone_hit",
        )

    positions = [
        target.position
        for target in [ordinary_target, *(hit.target for hit in hits)]
        if target is not None and target.position is not None
    ]
    tilts = [
        target.tilt
        for target in [ordinary_target, *(hit.target for hit in hits)]
        if target is not None and target.tilt is not None
    ]
    position = min(positions) if positions else None
    tilt = max(tilts) if tilts else None

    applied: list[str] = []
    baseline_position = ordinary_target.position if ordinary_target else None
    baseline_tilt = ordinary_target.tilt if ordinary_target else None
    for evaluation in hits:
        zone_target = evaluation.target
        if zone_target is None:
            continue
        position_determines = (
            zone_target.position is not None
            and position == zone_target.position
            and position != baseline_position
        )
        tilt_determines = (
            zone_target.tilt is not None
            and tilt == zone_target.tilt
            and tilt != baseline_tilt
        )
        if position_determines or tilt_determines:
            applied.append(evaluation.zone_id)

    if not applied:
        # A geometric hit alone must not change semantic target equality.  In
        # particular, retain existing details so Day Preview does not show a
        # phantom transition for a zone without a stricter target.
        return ProtectedTargetAdjustment(
            target=ordinary_target,
            hit_zone_ids=hit_ids,
            applied_zone_ids=(),
            reason_code="protected_zone_hit_no_stricter_target",
            details={
                "ordinary_target": ordinary_target.as_dict()
                if ordinary_target
                else None,
            },
        )

    details = dict(ordinary_target.details) if ordinary_target is not None else {}
    details["protected_zone_hit_ids"] = hit_ids
    target = Target(position=position, tilt=tilt, details=details)
    return ProtectedTargetAdjustment(
        target=target,
        hit_zone_ids=hit_ids,
        applied_zone_ids=tuple(applied),
        reason_code="protected_zone_target_adjusted",
        details={"ordinary_target": ordinary_target.as_dict() if ordinary_target else None},
    )


# An explicit alias makes the domain rule discoverable to callers that only
# care about the final merge, while keeping the trace-rich API above available.
most_protective_target = apply_protected_zones


@dataclass(frozen=True)
class DecisionCandidate:
    """A normalized rule outcome before central priority resolution."""

    rule: str
    matched: bool
    mode: str
    reason_code: str
    target: Target | None = None
    priority: int | None = None
    details: Mapping[str, Any] = field(default_factory=dict)
    valid_until: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule", str(self.rule))
        object.__setattr__(self, "mode", str(self.mode))
        object.__setattr__(self, "reason_code", str(self.reason_code))
        object.__setattr__(self, "details", _freeze_mapping(self.details))

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "matched": self.matched,
            "mode": self.mode,
            "priority": self.priority,
            "reason_code": self.reason_code,
            "target": self.target.as_dict() if self.target else None,
            "details": _serialize_mapping(self.details),
            "valid_until": _serialize_datetime(self.valid_until),
        }


@dataclass(frozen=True)
class CommandResult:
    """Execution information attached after a decision or simulation."""

    status: CommandResultStatus
    reason_code: str
    target: Target | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "status",
            _enum_value(self.status, CommandResultStatus, CommandResultStatus.FAILED),
        )
        object.__setattr__(self, "details", _freeze_mapping(self.details))

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reason_code": self.reason_code,
            "target": self.target.as_dict() if self.target else None,
            "details": _serialize_mapping(self.details),
        }


@dataclass(frozen=True)
class TraceEntry:
    """One candidate's final position in a structured decision trace."""

    candidate: DecisionCandidate
    outcome: TraceOutcome
    resolution_reason_code: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "outcome",
            _enum_value(self.outcome, TraceOutcome, TraceOutcome.REJECTED),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.as_dict(),
            "outcome": self.outcome.value,
            "resolution_reason_code": self.resolution_reason_code,
        }


@dataclass(frozen=True)
class DecisionTrace:
    """Full explainable resolution, including rejected rule candidates."""

    entries: tuple[TraceEntry, ...]
    winner: DecisionCandidate
    rejected: tuple[DecisionCandidate, ...]
    command_result: CommandResult
    protected_zones: tuple[ProtectedZoneEvaluation, ...] = ()
    input_snapshot: InputSnapshot | None = None
    context_details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "context_details", _freeze_mapping(self.context_details))

    def as_dict(self) -> dict[str, Any]:
        return {
            "winner": self.winner.as_dict(),
            "rejected": [candidate.as_dict() for candidate in self.rejected],
            "entries": [entry.as_dict() for entry in self.entries],
            "command_result": self.command_result.as_dict(),
            "protected_zones": [zone.as_dict() for zone in self.protected_zones],
            "input_snapshot": self.input_snapshot.as_dict() if self.input_snapshot else None,
            "context_details": _serialize_mapping(self.context_details),
        }


@dataclass(frozen=True)
class DecisionResolution:
    """Resolver-only result used by :class:`DecisionPipeline`."""

    winner: DecisionCandidate
    normalized_candidates: tuple[DecisionCandidate, ...]
    rejected: tuple[DecisionCandidate, ...]
    entries: tuple[TraceEntry, ...]


class DecisionResolver:
    """Apply the immutable Smart Shading priority contract deterministically."""

    _RULE_PRIORITIES: Mapping[str, DecisionPriority] = MappingProxyType(
        {
            "safety": DecisionPriority.SAFETY,
            "manual_master_override": DecisionPriority.MANUAL,
            "room_pause": DecisionPriority.MANUAL,
            "local_cover_pause": DecisionPriority.MANUAL,
            "manual_override": DecisionPriority.MANUAL,
            "safety_source_hold": DecisionPriority.SAFETY_SOURCE_HOLD,
            "night_source_hold": DecisionPriority.NIGHT_SOURCE_HOLD,
            "night": DecisionPriority.NIGHT,
            "heat_protection": DecisionPriority.HEAT,
            "heat": DecisionPriority.HEAT,
            "schedule_hold": DecisionPriority.INPUT_HOLD,
            "input_quality_hold": DecisionPriority.INPUT_HOLD,
            "glare_protection": DecisionPriority.GLARE,
            "solar": DecisionPriority.SOLAR,
            "comfort": DecisionPriority.COMFORT,
            "open": DecisionPriority.OPEN,
            "idle": DecisionPriority.IDLE,
        }
    )
    _MODE_PRIORITIES: Mapping[str, DecisionPriority] = MappingProxyType(
        {
            MODE_SAFETY: DecisionPriority.SAFETY,
            MODE_DISABLED: DecisionPriority.MANUAL,
            MODE_PAUSED: DecisionPriority.MANUAL,
            MODE_NIGHT: DecisionPriority.NIGHT,
            MODE_HEAT: DecisionPriority.HEAT,
            MODE_GLARE: DecisionPriority.GLARE,
            MODE_SOLAR: DecisionPriority.SOLAR,
            MODE_COMFORT: DecisionPriority.COMFORT,
            MODE_OPEN: DecisionPriority.OPEN,
            MODE_IDLE: DecisionPriority.IDLE,
        }
    )
    _RULE_ORDER: Mapping[str, int] = MappingProxyType(
        {
            "safety": 0,
            "manual_master_override": 10,
            "room_pause": 20,
            "local_cover_pause": 30,
            "manual_override": 40,
            "safety_source_hold": 42,
            "night_source_hold": 45,
            "night": 50,
            "heat_protection": 60,
            "heat": 70,
            "schedule_hold": 75,
            "input_quality_hold": 80,
            "glare_protection": 90,
            "solar": 100,
            "comfort": 110,
            "open": 120,
            "idle": 130,
        }
    )
    _RULE_MODES: Mapping[str, str] = MappingProxyType(
        {
            "safety": MODE_SAFETY,
            "manual_master_override": MODE_DISABLED,
            "room_pause": MODE_PAUSED,
            "local_cover_pause": MODE_PAUSED,
            "manual_override": MODE_DISABLED,
            "safety_source_hold": MODE_IDLE,
            "night_source_hold": MODE_IDLE,
            "night": MODE_NIGHT,
            "heat_protection": MODE_HEAT,
            "heat": MODE_HEAT,
            "schedule_hold": MODE_IDLE,
            "input_quality_hold": MODE_IDLE,
            "glare_protection": MODE_GLARE,
            "solar": MODE_SOLAR,
            "comfort": MODE_COMFORT,
            "open": MODE_OPEN,
            "idle": MODE_IDLE,
        }
    )

    @classmethod
    def priority_for(cls, candidate: DecisionCandidate) -> DecisionPriority:
        """Return the central priority; never trust a supplied numeric value."""

        return cls._RULE_PRIORITIES.get(
            candidate.rule,
            cls._MODE_PRIORITIES.get(candidate.mode, DecisionPriority.FALLBACK),
        )

    @classmethod
    def _normalize_candidate(cls, candidate: DecisionCandidate) -> DecisionCandidate:
        """Fail closed when a public rule claims an incompatible mode."""
        expected_mode = cls._RULE_MODES.get(candidate.rule)
        if expected_mode is None or candidate.mode == expected_mode:
            return replace(candidate, priority=int(cls.priority_for(candidate)))
        details = dict(candidate.details)
        details.update(
            {
                "expected_mode": expected_mode,
                "received_mode": candidate.mode,
            }
        )
        return replace(
            candidate,
            matched=False,
            priority=int(DecisionPriority.FALLBACK),
            reason_code="rule_mode_mismatch",
            details=details,
        )

    @classmethod
    def _sort_key(
        cls, item: tuple[int, DecisionCandidate]
    ) -> tuple[int, int, str, str, int]:
        index, candidate = item
        # Lower tuple wins.  Rule text makes unknown candidates deterministic;
        # original order is a final stable tiebreaker only.
        return (
            -int(candidate.priority or DecisionPriority.FALLBACK),
            cls._RULE_ORDER.get(candidate.rule, 10_000),
            candidate.rule,
            candidate.mode,
            index,
        )

    def resolve(self, candidates: Iterable[DecisionCandidate]) -> DecisionResolution:
        """Choose exactly one matching candidate and retain every rejection."""

        normalized = tuple(self._normalize_candidate(candidate) for candidate in candidates)
        matches = [
            (index, candidate)
            for index, candidate in enumerate(normalized)
            if candidate.matched
        ]
        if not matches:
            fallback = DecisionCandidate(
                rule="idle",
                matched=True,
                mode=MODE_IDLE,
                priority=int(DecisionPriority.IDLE),
                reason_code="no_decision_rule_matched",
            )
            normalized = (*normalized, fallback)
            matches = [(len(normalized) - 1, fallback)]
        winner_index, winner = min(matches, key=self._sort_key)
        rejected = tuple(
            candidate
            for index, candidate in enumerate(normalized)
            if index != winner_index
        )
        entries: list[TraceEntry] = []
        for index, candidate in enumerate(normalized):
            if index == winner_index:
                entries.append(
                    TraceEntry(
                        candidate=candidate,
                        outcome=TraceOutcome.WINNER,
                        resolution_reason_code="highest_matching_priority",
                    )
                )
            elif not candidate.matched:
                entries.append(
                    TraceEntry(
                        candidate=candidate,
                        outcome=TraceOutcome.REJECTED,
                        resolution_reason_code="rule_not_matched",
                    )
                )
            else:
                same_priority = candidate.priority == winner.priority
                tie_reason = (
                    "same_priority_tiebreaker_rule_order"
                    if same_priority
                    and self._RULE_ORDER.get(candidate.rule, 10_000)
                    != self._RULE_ORDER.get(winner.rule, 10_000)
                    else "same_priority_tiebreaker_stable_order"
                    if same_priority
                    else f"lower_priority_than_{winner.rule}"
                )
                entries.append(
                    TraceEntry(
                        candidate=candidate,
                        outcome=TraceOutcome.REJECTED,
                        resolution_reason_code=tie_reason,
                    )
                )
        return DecisionResolution(
            winner=winner,
            normalized_candidates=normalized,
            rejected=rejected,
            entries=tuple(entries),
        )


@dataclass(frozen=True)
class DecisionContext:
    """Pure room/sector facts supplied to one decision evaluation.

    ``targets`` is intentionally profile-mapped input for now.  The future
    profile mapper can populate it before this layer, or replace it with a
    dedicated target-mapping call without changing the resolver contract.
    """

    snapshot: InputSnapshot
    safety_active: bool = False
    manual_override_active: bool = False
    room_pause_active: bool = False
    local_pause_active: bool = False
    safety_source_hold_active: bool = False
    night_active: bool = False
    night_source_hold_active: bool = False
    heat_active: bool = False
    schedule_hold_active: bool = False
    glare_allowed: bool = False
    solar_active: bool = False
    comfort_active: bool = False
    # The original public pipeline treated Open as an unconditional fallback.
    # Keeping that default preserves callers that only pass the higher-priority
    # facts, while adapters can explicitly describe a deliberate Idle hold.
    open_active: bool = True
    idle_active: bool = False
    normal_input_keys: tuple[str, ...] = ()
    hold_on_invalid_normal_inputs: bool = True
    targets: Mapping[str, Target] = field(default_factory=dict)
    sector_id: str | None = None
    group_id: str | None = None
    cover_entity: str | None = None
    sun_geometry: SunGeometry | None = None
    protected_zones: tuple[ProtectedZone, ...] = ()
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        target_copy: dict[str, Target] = {}
        for key, value in dict(self.targets).items():
            if not isinstance(value, Target):
                raise TypeError(f"Decision target {key!r} must be a Target")
            target_copy[str(key)] = value
        object.__setattr__(self, "targets", _freeze_mapping(target_copy))
        object.__setattr__(
            self,
            "normal_input_keys",
            tuple(str(key) for key in self.normal_input_keys),
        )
        object.__setattr__(self, "protected_zones", tuple(self.protected_zones))
        object.__setattr__(self, "details", _freeze_mapping(self.details))

    def target_for(self, mode: str) -> Target | None:
        return self.targets.get(mode)


@dataclass(frozen=True)
class DecisionResult:
    """Final pure decision with a complete trace and no executor side effect."""

    context: DecisionContext
    winner: DecisionCandidate
    trace: DecisionTrace
    simulation: bool = False

    @property
    def mode(self) -> str:
        return self.winner.mode

    @property
    def target(self) -> Target | None:
        return self.winner.target

    def with_command_result(self, command_result: CommandResult) -> "DecisionResult":
        """Attach planner/executor output without recalculating the decision."""

        return replace(
            self,
            trace=replace(self.trace, command_result=command_result),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "simulation": self.simulation,
            "mode": self.mode,
            "target": self.target.as_dict() if self.target else None,
            "trace": self.trace.as_dict(),
        }


class DecisionPipeline:
    """Build standard candidates, resolve them, and produce a diagnostic trace."""

    def __init__(self, resolver: DecisionResolver | None = None) -> None:
        self.resolver = resolver or DecisionResolver()

    @staticmethod
    def _quality_details(context: DecisionContext) -> Mapping[str, str]:
        return {
            key: quality.value
            for key, quality in context.snapshot.quality_failures(
                context.normal_input_keys
            ).items()
        }

    def _build_candidates(
        self,
        context: DecisionContext,
        glare_adjustment: ProtectedTargetAdjustment,
        solar_adjustment: ProtectedTargetAdjustment,
        comfort_adjustment: ProtectedTargetAdjustment,
        quality_failures: Mapping[str, str],
    ) -> tuple[DecisionCandidate, ...]:
        quality_hold = bool(quality_failures) and context.hold_on_invalid_normal_inputs
        glare_target = glare_adjustment.target
        solar_target = (
            solar_adjustment.target or context.target_for(MODE_SOLAR)
        )
        comfort_target = (
            comfort_adjustment.target or context.target_for(MODE_COMFORT)
        )
        solar_reason = (
            "solar_glare_target_adjusted"
            if solar_adjustment.applied_zone_ids
            else "solar_conditions_met"
        )
        comfort_reason = (
            "comfort_glare_target_adjusted"
            if comfort_adjustment.applied_zone_ids
            else "comfort_active"
        )
        candidates = (
            DecisionCandidate(
                rule="safety",
                matched=context.safety_active,
                mode=MODE_SAFETY,
                target=context.target_for(MODE_SAFETY),
                reason_code="safety_active" if context.safety_active else "safety_inactive",
            ),
            DecisionCandidate(
                rule="manual_master_override",
                matched=context.manual_override_active,
                mode=MODE_DISABLED,
                reason_code=(
                    "manual_master_override_active"
                    if context.manual_override_active
                    else "manual_master_override_inactive"
                ),
            ),
            DecisionCandidate(
                rule="room_pause",
                matched=context.room_pause_active,
                mode=MODE_PAUSED,
                reason_code="room_pause_active" if context.room_pause_active else "room_pause_inactive",
            ),
            DecisionCandidate(
                rule="local_cover_pause",
                matched=context.local_pause_active,
                mode=MODE_PAUSED,
                reason_code=(
                    "local_cover_pause_active"
                    if context.local_pause_active
                    else "local_cover_pause_inactive"
                ),
            ),
            DecisionCandidate(
                rule="safety_source_hold",
                matched=context.safety_source_hold_active,
                mode=MODE_IDLE,
                reason_code=(
                    "safety_source_unavailable_hold"
                    if context.safety_source_hold_active
                    else "safety_source_available"
                ),
            ),
            DecisionCandidate(
                rule="night_source_hold",
                matched=context.night_source_hold_active,
                mode=MODE_IDLE,
                reason_code=(
                    "night_source_unavailable_hold"
                    if context.night_source_hold_active
                    else "night_source_available"
                ),
            ),
            DecisionCandidate(
                rule="night",
                matched=context.night_active,
                mode=MODE_NIGHT,
                target=context.target_for(MODE_NIGHT),
                reason_code="night_active" if context.night_active else "night_inactive",
            ),
            DecisionCandidate(
                rule="heat_protection",
                matched=context.heat_active,
                mode=MODE_HEAT,
                target=context.target_for(MODE_HEAT),
                reason_code="heat_protection_active" if context.heat_active else "heat_protection_inactive",
            ),
            DecisionCandidate(
                rule="schedule_hold",
                matched=context.schedule_hold_active,
                mode=MODE_IDLE,
                reason_code=(
                    "schedule_outside_hold"
                    if context.schedule_hold_active
                    else "schedule_active"
                ),
            ),
            DecisionCandidate(
                rule="input_quality_hold",
                matched=quality_hold,
                mode=MODE_IDLE,
                reason_code=(
                    "normal_input_quality_invalid_hold"
                    if quality_hold
                    else "normal_input_quality_valid"
                ),
                details={"quality_failures": dict(quality_failures)},
            ),
            DecisionCandidate(
                rule="glare_protection",
                matched=(
                    context.glare_allowed
                    and bool(glare_adjustment.applied_zone_ids)
                    and not quality_hold
                ),
                mode=MODE_GLARE,
                target=glare_target,
                reason_code=(
                    "glare_blocked_by_input_quality"
                    if (
                        context.glare_allowed
                        and glare_adjustment.applied_zone_ids
                        and quality_hold
                    )
                    else "protected_zone_target_adjusted"
                    if (
                        context.glare_allowed
                        and glare_adjustment.applied_zone_ids
                    )
                    else "protected_zone_inactive"
                ),
                details={
                    "protected_zone_hit_ids": glare_adjustment.hit_zone_ids,
                    "protected_zone_applied_ids": (
                        glare_adjustment.applied_zone_ids
                    ),
                    "protected_zone_reason": glare_adjustment.reason_code,
                    "ordinary_target": glare_adjustment.details.get(
                        "ordinary_target"
                    ),
                    "protected_zone_determining_ids": (
                        glare_adjustment.applied_zone_ids
                    ),
                },
            ),
            DecisionCandidate(
                rule="solar",
                matched=context.solar_active and not quality_hold,
                mode=MODE_SOLAR,
                target=solar_target,
                reason_code=(
                    "solar_blocked_by_input_quality"
                    if context.solar_active and quality_hold
                    else solar_reason if context.solar_active else "solar_inactive"
                ),
                details={
                    "protected_zone_hit_ids": solar_adjustment.hit_zone_ids,
                    "protected_zone_applied_ids": (
                        solar_adjustment.applied_zone_ids
                    ),
                    "protected_zone_reason": solar_adjustment.reason_code,
                    # Keep both sides of the glare/protected-zone merge in
                    # the production trace: consumers must not have to infer
                    # the ordinary profile target from a later command.
                    "ordinary_target": solar_adjustment.details.get(
                        "ordinary_target"
                    ),
                    "protected_zone_determining_ids": (
                        solar_adjustment.applied_zone_ids
                    ),
                },
            ),
            DecisionCandidate(
                rule="comfort",
                matched=context.comfort_active and not quality_hold,
                mode=MODE_COMFORT,
                target=comfort_target,
                reason_code=(
                    "comfort_blocked_by_input_quality"
                    if context.comfort_active and quality_hold
                    else comfort_reason
                    if context.comfort_active
                    else "comfort_inactive"
                ),
                details={
                    "protected_zone_hit_ids": comfort_adjustment.hit_zone_ids,
                    "protected_zone_applied_ids": (
                        comfort_adjustment.applied_zone_ids
                    ),
                    "protected_zone_reason": comfort_adjustment.reason_code,
                    "ordinary_target": comfort_adjustment.details.get(
                        "ordinary_target"
                    ),
                    "protected_zone_determining_ids": (
                        comfort_adjustment.applied_zone_ids
                    ),
                },
            ),
            DecisionCandidate(
                rule="open",
                matched=context.open_active and not quality_hold,
                mode=MODE_OPEN,
                target=context.target_for(MODE_OPEN),
                reason_code=(
                    "open_blocked_by_input_quality"
                    if quality_hold
                    else "open_fallback" if context.open_active else "open_inactive"
                ),
            ),
            DecisionCandidate(
                rule="idle",
                matched=context.idle_active,
                mode=MODE_IDLE,
                reason_code="idle_hold_active" if context.idle_active else "idle_inactive",
            ),
        )
        return candidates

    def evaluate(
        self, context: DecisionContext, *, simulation: bool = False
    ) -> DecisionResult:
        """Run the full pure pipeline once; it never sends a cover service."""

        zone_evaluations = evaluate_protected_zones(
            context.protected_zones,
            context.sun_geometry,
            sector_id=context.sector_id,
            group_id=context.group_id,
            cover_entity=context.cover_entity,
        )
        glare_baseline = (
            context.target_for(MODE_SOLAR)
            if context.solar_active
            else context.target_for(MODE_COMFORT)
            if context.comfort_active
            else context.target_for(MODE_OPEN)
        )
        glare_adjustment = apply_protected_zones(
            glare_baseline, zone_evaluations
        )
        solar_adjustment = apply_protected_zones(
            context.target_for(MODE_SOLAR), zone_evaluations
        )
        comfort_adjustment = apply_protected_zones(
            context.target_for(MODE_COMFORT), zone_evaluations
        )
        quality_failures = self._quality_details(context)
        resolution = self.resolver.resolve(
            self._build_candidates(
                context,
                glare_adjustment,
                solar_adjustment,
                comfort_adjustment,
                quality_failures,
            )
        )
        command_result = CommandResult(
            status=(
                CommandResultStatus.SIMULATED
                if simulation
                else CommandResultStatus.NOT_PLANNED
            ),
            reason_code=(
                "simulation_never_executes_services"
                if simulation
                else "pure_decision_requires_command_planner"
            ),
            target=resolution.winner.target,
        )
        trace = DecisionTrace(
            entries=resolution.entries,
            winner=resolution.winner,
            rejected=resolution.rejected,
            command_result=command_result,
            protected_zones=zone_evaluations,
            input_snapshot=context.snapshot,
            context_details=context.details,
        )
        return DecisionResult(
            context=context,
            winner=resolution.winner,
            trace=trace,
            simulation=simulation,
        )


def simulate(
    context: DecisionContext,
    *,
    overrides: Mapping[str, InputValue | Any] | None = None,
    pipeline: DecisionPipeline | None = None,
) -> DecisionResult:
    """Run the production decision pipeline with virtual input overrides.

    The function accepts no service callback and intentionally has no mutation
    path.  It is consequently safe for customer-facing simulation and tests.
    """

    selected_pipeline = pipeline or DecisionPipeline()
    simulated_context = context
    if overrides:
        simulated_context = replace(
            context,
            snapshot=context.snapshot.with_overrides(overrides),
        )
    return selected_pipeline.evaluate(simulated_context, simulation=True)


@dataclass(frozen=True)
class PreviewPoint:
    """One deterministic virtual instant for :func:`preview_day`."""

    at: datetime
    context: DecisionContext
    label: str = ""


@dataclass(frozen=True)
class DayPreviewSample:
    """One simulated decision retained in chronological day-preview output."""

    at: datetime
    result: DecisionResult
    label: str = ""


@dataclass(frozen=True)
class PreviewTransition:
    """A logical target/mode change between two adjacent preview samples."""

    at: datetime
    previous_mode: str
    mode: str
    previous_target: Target | None
    target: Target | None
    reason_code: str


@dataclass(frozen=True)
class DayPreview:
    """Chronological non-executing forecast generated by the same pipeline."""

    day: date | None
    samples: tuple[DayPreviewSample, ...]
    transitions: tuple[PreviewTransition, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "day": self.day.isoformat() if self.day else None,
            "samples": [
                {
                    "at": _serialize_datetime(sample.at),
                    "label": sample.label,
                    "result": sample.result.as_dict(),
                }
                for sample in self.samples
            ],
            "transitions": [
                {
                    "at": _serialize_datetime(transition.at),
                    "previous_mode": transition.previous_mode,
                    "mode": transition.mode,
                    "previous_target": transition.previous_target.as_dict()
                    if transition.previous_target
                    else None,
                    "target": transition.target.as_dict() if transition.target else None,
                    "reason_code": transition.reason_code,
                }
                for transition in self.transitions
            ],
        }


def preview_day(
    points: Iterable[PreviewPoint], *, pipeline: DecisionPipeline | None = None
) -> DayPreview:
    """Simulate chronological day points through :func:`simulate`.

    Callers choose the points (sector boundaries, tilt stages, schedule or
    Night transitions) so the output can be exact rather than minute-polled.
    Every point reuses the production :class:`DecisionPipeline` instance.
    """

    selected_pipeline = pipeline or DecisionPipeline()
    ordered = sorted(tuple(points), key=lambda point: point.at)
    samples: list[DayPreviewSample] = []
    transitions: list[PreviewTransition] = []
    previous: DayPreviewSample | None = None
    for point in ordered:
        # Keep the raw input values but regrade freshness at the virtual time.
        # A stale source must produce the same hold in preview as it would in a
        # live evaluation at that instant.
        snapshot = point.context.snapshot.refreshed_at(point.at)
        context = replace(point.context, snapshot=snapshot)
        result = simulate(context, pipeline=selected_pipeline)
        sample = DayPreviewSample(at=point.at, result=result, label=point.label)
        samples.append(sample)
        if previous and (
            previous.result.mode != result.mode
            or previous.result.target != result.target
        ):
            transitions.append(
                PreviewTransition(
                    at=point.at,
                    previous_mode=previous.result.mode,
                    mode=result.mode,
                    previous_target=previous.result.target,
                    target=result.target,
                    reason_code="decision_changed",
                )
            )
        previous = sample
    return DayPreview(
        day=ordered[0].at.date() if ordered else None,
        samples=tuple(samples),
        transitions=tuple(transitions),
    )


# A slightly more descriptive alias for callers that use a command-style API.
build_day_preview = preview_day


def _serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _serialize_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON-friendly shallow copy for diagnostic consumers."""

    result: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, Enum):
            result[key] = value.value
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        elif isinstance(value, Mapping):
            result[key] = _serialize_mapping(value)
        elif isinstance(value, tuple):
            result[key] = [
                item.value if isinstance(item, Enum) else item for item in value
            ]
        else:
            result[key] = value
    return result


__all__ = [
    "CommandResult",
    "CommandResultStatus",
    "DayPreview",
    "DayPreviewSample",
    "DecisionCandidate",
    "DecisionContext",
    "DecisionPipeline",
    "DecisionPriority",
    "DecisionResolution",
    "DecisionResolver",
    "DecisionResult",
    "DecisionTrace",
    "InputKind",
    "InputSnapshot",
    "InputValue",
    "MODE_COMFORT",
    "MODE_DISABLED",
    "MODE_HEAT",
    "MODE_IDLE",
    "MODE_NIGHT",
    "MODE_OPEN",
    "MODE_PAUSED",
    "MODE_SAFETY",
    "MODE_SOLAR",
    "PreviewPoint",
    "PreviewTransition",
    "ProtectedTargetAdjustment",
    "ProtectedZone",
    "ProtectedZoneEvaluation",
    "ProtectedZoneStatus",
    "ProtectedZoneValidation",
    "QualityState",
    "SunGeometry",
    "Target",
    "TraceEntry",
    "TraceOutcome",
    "apply_protected_zones",
    "build_day_preview",
    "evaluate_protected_zone",
    "evaluate_protected_zones",
    "most_protective_target",
    "normalize_input",
    "preview_day",
    "simulate",
    "validate_protected_zone",
]
