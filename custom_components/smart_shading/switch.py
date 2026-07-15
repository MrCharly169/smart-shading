from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import EntityCategory

from .entity import SmartShadingEntity, localized


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    engine = entry.runtime_data
    entities = []
    for room_id in engine.rooms:
        entities.append(RoomEnableSwitch(engine, room_id))
    for room in engine.config.get("rooms", []):
        for sector in room.get("sectors", []):
            entities.append(
                SectorEnableSwitch(engine, room["id"], sector["id"])
            )
    async_add_entities(entities)


class RoomEnableSwitch(SmartShadingEntity, SwitchEntity):
    _attr_name = "Manual master override"
    _attr_icon = "mdi:hand-back-right"

    def __init__(self, engine, room_id: str) -> None:
        super().__init__(engine, room_id=room_id)
        self._attr_name = localized(engine, "Manual master override", "Manueller Master-Override")
        self._attr_unique_id = f"{self.entry.entry_id}_{room_id}_enable"

    @property
    def is_on(self):
        # ON = manual master active = automation disabled
        return not self.engine.rooms[self.room_id].enabled

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        attrs["smart_shading_control_key"] = "manual_master"
        return attrs

    async def async_turn_on(self, **kwargs):
        await self.engine.async_set_room_enabled(self.room_id, False)

    async def async_turn_off(self, **kwargs):
        await self.engine.async_set_room_enabled(self.room_id, True)


class SectorEnableSwitch(SmartShadingEntity, SwitchEntity):
    _attr_name = "Sector enabled"
    _attr_icon = "mdi:sun-compass"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, engine, room_id: str, sector_id: str) -> None:
        super().__init__(engine, room_id=room_id, sector_id=sector_id)
        sector = engine.sector_config(sector_id)
        self._attr_name = f"{sector.get('name', '')} · {localized(engine, 'Sector enabled', 'Sonnensektor aktiviert')}"
        self._attr_unique_id = f"{self.entry.entry_id}_{sector_id}_enable"

    @property
    def is_on(self):
        return bool(self.engine.sector_value(self.sector_id, "enabled", True))

    async def async_turn_on(self, **kwargs):
        await self.engine.async_set_sector_value(
            self.sector_id, "enabled", True, custom=False
        )

    async def async_turn_off(self, **kwargs):
        await self.engine.async_set_sector_value(
            self.sector_id, "enabled", False, custom=False
        )
