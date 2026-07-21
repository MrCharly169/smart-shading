from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN


def localized(engine, english: str, german: str) -> str:
    language = getattr(engine.hass.config, "language", "en") or "en"
    return german if language.lower().startswith("de") else english


class SmartShadingEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        engine,
        *,
        room_id: str | None = None,
        sector_id: str | None = None,
        layer_id: str | None = None,
    ) -> None:
        self.engine = engine
        self.entry = engine.entry
        self.room_id = room_id
        self.sector_id = sector_id
        self.layer_id = layer_id
        self._remove_listener = None

    @property
    def device_info(self) -> DeviceInfo:
        if self.room_id:
            room = self.engine.rooms[self.room_id]
            return DeviceInfo(
                identifiers={(DOMAIN, f"{self.entry.entry_id}_{self.room_id}")},
                name=f"Smart Shading · {room.name}",
                manufacturer="Smart Shading",
                model="Adaptive room controller",
                via_device=(DOMAIN, self.entry.entry_id),
            )
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=f"Smart Shading · {self.entry.title}",
            manufacturer="Smart Shading",
            model="House controller",
            configuration_url="/config/integrations/integration/smart_shading",
        )

    @property
    def extra_state_attributes(self):
        attributes = {
            "smart_shading_entry_id": self.entry.entry_id,
            "smart_shading_diagnostic_level": self.engine.diagnostic_level,
            "smart_shading_layout": (
                "detailed" if self.engine.advanced_mode else "compact"
            ),
        }
        if self.room_id:
            attributes["smart_shading_room_id"] = self.room_id
        if self.sector_id:
            attributes["smart_shading_sector_id"] = self.sector_id
        if self.layer_id:
            attributes["smart_shading_layer_id"] = self.layer_id
        return attributes

    async def async_added_to_hass(self) -> None:
        self._remove_listener = self.engine.async_add_listener(
            self.async_write_ha_state
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener:
            self._remove_listener()
