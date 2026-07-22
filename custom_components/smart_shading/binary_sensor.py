from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.entity import EntityCategory

from .entity import SmartShadingEntity, localized


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    engine = entry.runtime_data
    entities = []
    for room in engine.config.get("rooms", []):
        for sector in room.get("sectors", []):
            if sector.get("lux_sensor"):
                entities.append(
                    SectorSunPresenceBinarySensor(
                        engine, room["id"], sector["id"]
                    )
                )
    async_add_entities(entities)


class SectorSunPresenceBinarySensor(SmartShadingEntity, BinarySensorEntity):
    _attr_name = "Sun presence"
    _attr_icon = "mdi:white-balance-sunny"

    def __init__(self, engine, room_id: str, sector_id: str) -> None:
        super().__init__(engine, room_id=room_id, sector_id=sector_id)
        sector = engine.sector_config(sector_id)
        suffix = localized(engine, "sun detected", "Sonne erkannt")
        self._attr_name = f"{sector.get('name', '')} · {suffix}"
        self._attr_unique_id = (
            f"{self.entry.entry_id}_{sector_id}_sun_presence"
        )

    @property
    def runtime(self):
        return self.engine.sun_runtime[self.sector_id]

    @property
    def is_on(self):
        return self.runtime.is_on

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        sector = self.engine.sector_config(self.sector_id)
        settings = self.engine._sun_settings(self.sector_id)
        lux_state = self.engine.hass.states.get(sector.get("lux_sensor", "")) if sector.get("lux_sensor") else None
        attrs.update(
            {
                "sector_name": sector["name"],
                "lux_sensor": sector.get("lux_sensor"),
                "lux_raw_state": lux_state.state if lux_state else None,
                "lux_unit": lux_state.attributes.get("unit_of_measurement") if lux_state else None,
                "current_lux": self.runtime.current_lux,
                "source_valid": self.runtime.source_valid,
                "sun_preset": self.engine.sector_value(self.sector_id, "sun_preset", "medium"),
                "sun_on_lux": settings["sun_on_lux"],
                "sun_off_lux": settings["sun_off_lux"],
                "effective_sun_on_lux": max(settings["sun_on_lux"], settings["sun_off_lux"]),
                "effective_sun_off_lux": min(settings["sun_on_lux"], settings["sun_off_lux"]),
                "sun_on_delay_minutes": settings["sun_on_delay"],
                "sun_off_delay_minutes": settings["sun_off_delay"],
                "pending_target": self.runtime.pending_target,
                "pending_since": self.runtime.pending_since,
                "pending_until": self.runtime.pending_until,
                "last_transition": self.runtime.last_transition,
                "reason": self.runtime.reason,
            }
        )
        return attrs
