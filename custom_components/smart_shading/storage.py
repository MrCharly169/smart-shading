from __future__ import annotations

from copy import deepcopy
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    PAUSE_DURATION_MAX_HOURS,
    PAUSE_DURATION_MIN_HOURS,
    STORAGE_VERSION,
)
from .logic import migrate_slat_overrides

_LOGGER = logging.getLogger(__name__)


class RuntimeStore:
    """Persist adjustable test-mode values and runtime state."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}"
        )
        self.data: dict[str, Any] = {
            "overrides": {},
            "room_runtime": {},
            "sun_runtime": {},
            "cover_runtime": {},
            # The ownership ledger and last decision trace intentionally live
            # beside legacy cover pause state.  They survive a Home Assistant
            # restart and let diagnostics explain both why a cover was moved
            # and whether that move is still owned by Smart Shading.
            "command_ledger": {},
            "decision_traces": {},
            "queued_commands": [],
            "card_notification_ids": [],
            "day_key": None,
            "runtime_schema": 5,
        }

    async def async_load(self) -> None:
        try:
            loaded = await self._store.async_load()
        except HomeAssistantError as err:
            # Runtime data is reconstructable. A transient or corrupt runtime
            # file must not prevent the customer's whole config entry from
            # loading after a Home Assistant restart.
            _LOGGER.warning(
                "Could not load Smart Shading runtime state; continuing with "
                "safe defaults: %s",
                err,
            )
            loaded = None
        if isinstance(loaded, dict):
            self.data.update(loaded)
            schema = int(self.data.get("runtime_schema", 1))
            changed = False
            if schema < 2:
                # Earlier betas counted routine "already correct" and cooldown
                # checks as blocked commands. Reset only that misleading statistic
                # while preserving pauses, Sun Presence and user overrides.
                for runtime in self.data.get("room_runtime", {}).values():
                    if isinstance(runtime, dict):
                        runtime["suppressed_commands"] = 0
                changed = True
            if schema < 3:
                self.data["overrides"] = migrate_slat_overrides(
                    self.data.get("overrides", {})
                )
                changed = True
            if schema < 4:
                overrides = self.data.get("overrides")
                if not isinstance(overrides, dict):
                    overrides = {}
                    self.data["overrides"] = overrides
                room_overrides = overrides.get("room")
                if not isinstance(room_overrides, dict):
                    room_overrides = {}
                    overrides["room"] = room_overrides
                room_runtime = self.data.get("room_runtime")
                if not isinstance(room_runtime, dict):
                    room_runtime = {}
                    self.data["room_runtime"] = room_runtime
                for room_id, runtime in room_runtime.items():
                    if not isinstance(runtime, dict) or "pause_hours" not in runtime:
                        continue
                    try:
                        duration = float(runtime["pause_hours"])
                    except (TypeError, ValueError):
                        duration = 2.0
                    duration = max(
                        PAUSE_DURATION_MIN_HOURS,
                        min(PAUSE_DURATION_MAX_HOURS, duration),
                    )
                    current = room_overrides.get(str(room_id))
                    if not isinstance(current, dict):
                        current = {}
                        room_overrides[str(room_id)] = current
                    current.setdefault("pause_duration_hours", duration)
                    runtime.pop("pause_hours", None)
                changed = True
            if schema < 5:
                for key in ("command_ledger", "decision_traces"):
                    if not isinstance(self.data.get(key), dict):
                        self.data[key] = {}
                queued = self.data.get("queued_commands", [])
                if isinstance(queued, dict):
                    queued = list(queued.values())
                if not isinstance(queued, list):
                    queued = []
                self.data["queued_commands"] = queued
                # Heat used to be persisted as a boolean.  Preserve its
                # customer-visible behaviour while moving to the explicit
                # lifecycle used by the decision trace.
                for runtime in self.data.get("room_runtime", {}).values():
                    if not isinstance(runtime, dict):
                        continue
                    runtime.setdefault(
                        "heat_phase",
                        "active" if runtime.get("heat_active") else "inactive",
                    )
                changed = True
            if changed:
                self.data["runtime_schema"] = 5
                await self.async_save()

    async def async_save(self) -> None:
        await self._store.async_save(self.data)

    def get_override(self, scope: str, object_id: str, key: str, default: Any) -> Any:
        return (
            self.data.get("overrides", {})
            .get(scope, {})
            .get(object_id, {})
            .get(key, default)
        )

    async def async_set_override(
        self, scope: str, object_id: str, key: str, value: Any
    ) -> None:
        self.data.setdefault("overrides", {}).setdefault(scope, {}).setdefault(
            object_id, {}
        )[key] = value
        await self.async_save()

    async def async_set_many(
        self, scope: str, object_id: str, values: dict[str, Any]
    ) -> None:
        self.data.setdefault("overrides", {}).setdefault(scope, {}).setdefault(
            object_id, {}
        ).update(values)
        await self.async_save()

    async def async_clear_overrides(self) -> None:
        """Remove overrides after the options wizard folded them into config."""
        if self.data.get("overrides"):
            self.data["overrides"] = {}
            await self.async_save()

    def room_runtime(self, room_id: str) -> dict[str, Any]:
        return deepcopy(self.data.setdefault("room_runtime", {}).setdefault(room_id, {}))

    async def async_save_room_runtime(self, room_id: str, values: dict[str, Any]) -> None:
        current = self.data.setdefault("room_runtime", {}).get(room_id)
        new_value = deepcopy(values)
        if current == new_value:
            return
        self.data["room_runtime"][room_id] = new_value
        await self.async_save()

    def sun_runtime(self, sector_id: str) -> dict[str, Any]:
        return deepcopy(self.data.setdefault("sun_runtime", {}).setdefault(sector_id, {}))

    async def async_save_sun_runtime(self, sector_id: str, values: dict[str, Any]) -> None:
        current = self.data.setdefault("sun_runtime", {}).get(sector_id)
        new_value = deepcopy(values)
        if current == new_value:
            return
        self.data["sun_runtime"][sector_id] = new_value
        await self.async_save()


    def cover_runtime(self, cover_id: str) -> dict[str, Any]:
        return deepcopy(self.data.setdefault("cover_runtime", {}).setdefault(cover_id, {}))

    async def async_save_cover_runtime(self, cover_id: str, values: dict[str, Any]) -> None:
        current = self.data.setdefault("cover_runtime", {}).get(cover_id)
        new_value = deepcopy(values)
        if current == new_value:
            return
        self.data["cover_runtime"][cover_id] = new_value
        await self.async_save()

    async def async_delete_cover_runtime(self, cover_id: str) -> None:
        if cover_id in self.data.setdefault("cover_runtime", {}):
            self.data["cover_runtime"].pop(cover_id, None)
            await self.async_save()

    def command_ledger(self, cover_id: str) -> dict[str, Any]:
        return deepcopy(self.data.setdefault("command_ledger", {}).setdefault(cover_id, {}))

    async def async_save_command_ledger(
        self, cover_id: str, values: dict[str, Any]
    ) -> None:
        current = self.data.setdefault("command_ledger", {}).get(cover_id)
        new_value = deepcopy(values)
        if current == new_value:
            return
        self.data["command_ledger"][cover_id] = new_value
        await self.async_save()

    async def async_delete_command_ledger(self, cover_id: str) -> None:
        if cover_id in self.data.setdefault("command_ledger", {}):
            self.data["command_ledger"].pop(cover_id, None)
            await self.async_save()

    def decision_trace(self, room_id: str) -> dict[str, Any]:
        return deepcopy(self.data.setdefault("decision_traces", {}).setdefault(room_id, {}))

    async def async_save_decision_trace(
        self, room_id: str, values: dict[str, Any]
    ) -> None:
        current = self.data.setdefault("decision_traces", {}).get(room_id)
        new_value = deepcopy(values)
        if current == new_value:
            return
        self.data["decision_traces"][room_id] = new_value
        await self.async_save()

    def queued_commands(self) -> list[dict[str, Any]]:
        values = self.data.setdefault("queued_commands", [])
        return deepcopy(values if isinstance(values, list) else [])

    async def async_save_queued_commands(self, values: list[dict[str, Any]]) -> None:
        new_value = deepcopy(values)
        if self.data.get("queued_commands", []) == new_value:
            return
        self.data["queued_commands"] = new_value
        await self.async_save()

    def card_notification_ids(self) -> list[str]:
        return list(self.data.get("card_notification_ids", []))

    async def async_set_card_notification_ids(self, values: list[str]) -> None:
        new_value = list(values)
        if self.data.get("card_notification_ids", []) == new_value:
            return
        self.data["card_notification_ids"] = new_value
        await self.async_save()

    def day_key(self) -> str | None:
        value = self.data.get("day_key")
        return str(value) if value else None

    async def async_set_day_key(self, value: str) -> None:
        if self.data.get("day_key") == value:
            return
        self.data["day_key"] = value
        await self.async_save()
