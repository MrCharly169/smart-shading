from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class CommandMemory:
    position: float | None = None
    position_at: datetime | None = None
    tilt: float | None = None
    tilt_at: datetime | None = None
    last_activity_at: datetime | None = None


@dataclass(slots=True)
class SectorSunRuntime:
    sector_id: str
    is_on: bool = False
    current_lux: float | None = None
    pending_target: bool | None = None
    pending_since: datetime | None = None
    pending_until: datetime | None = None
    last_transition: datetime | None = None
    reason: str = "Not evaluated"
    status: str = "not_evaluated"
    status_reason: str = "Not evaluated"
    geometry_active: bool = False
    shading_active: bool = False
    mode: str = "idle"


@dataclass(slots=True)
class RoomRuntime:
    room_id: str
    name: str
    mode: str = "idle"
    reason: str = "Not evaluated"
    active_sectors: list[str] = field(default_factory=list)
    targets: list[dict[str, Any]] = field(default_factory=list)
    last_evaluation: datetime | None = None
    last_command: datetime | None = None
    sent_commands: int = 0
    suppressed_commands: int = 0
    heat_active: bool = False
    shading_active: bool = False
    finished_today: bool = False
    pause_mode: str = "auto"
    pause_hours: float = 2.0
    pause_until: datetime | None = None
    enabled: bool = True
    schedule_active: bool = True
    schedule_reason: str = "Not evaluated"
    next_schedule_change: datetime | None = None


@dataclass(slots=True)
class CoverPauseRuntime:
    cover_id: str
    entity_id: str
    room_id: str
    active: bool = False
    until: datetime | None = None
    reason: str = ""
    lock_owned: bool = False
    started_at: datetime | None = None
