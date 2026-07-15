from __future__ import annotations

from copy import deepcopy
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_VERSION


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
            "card_notification_ids": [],
            "day_key": None,
            "runtime_schema": 2,
        }

    async def async_load(self) -> None:
        loaded = await self._store.async_load()
        if isinstance(loaded, dict):
            self.data.update(loaded)
            schema = int(self.data.get("runtime_schema", 1))
            if schema < 2:
                # Earlier betas counted routine "already correct" and cooldown
                # checks as blocked commands. Reset only that misleading statistic
                # while preserving pauses, Sun Presence and user overrides.
                for runtime in self.data.get("room_runtime", {}).values():
                    if isinstance(runtime, dict):
                        runtime["suppressed_commands"] = 0
                self.data["runtime_schema"] = 2
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
