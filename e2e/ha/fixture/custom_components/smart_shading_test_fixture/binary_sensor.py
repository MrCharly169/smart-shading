"""Deterministic binary sensors for E2E tests."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .store import FixtureStore, get_store


async def async_setup_platform(
    hass: HomeAssistant,
    _config: dict[str, Any],
    async_add_entities: AddEntitiesCallback,
    _discovery_info: dict[str, Any] | None = None,
) -> None:
    store = get_store(hass)
    async_add_entities(
        [
            FixtureBinarySensor(
                store, "Safety Alarm", "safety_alarm", BinarySensorDeviceClass.SAFETY
            ),
            FixtureBinarySensor(
                store,
                "Window Contact",
                "window_contact",
                BinarySensorDeviceClass.WINDOW,
            ),
            FixtureBinarySensor(
                store,
                "External Sun Presence",
                "external_sun_presence",
                BinarySensorDeviceClass.LIGHT,
            ),
            FixtureBinarySensor(store, "Occupancy", "occupancy", BinarySensorDeviceClass.OCCUPANCY),
            FixtureBinarySensor(store, "Weather Permission", "weather_permission", BinarySensorDeviceClass.RUNNING),
            FixtureBinarySensor(store, "Glare", "glare", BinarySensorDeviceClass.LIGHT),
            FixtureBinarySensor(store, "Wind Alarm", "wind_alarm", BinarySensorDeviceClass.SAFETY),
            FixtureBinarySensor(store, "Frost Alarm", "frost_alarm", BinarySensorDeviceClass.COLD),
        ]
    )


class FixtureBinarySensor(BinarySensorEntity):
    _attr_should_poll = False

    def __init__(
        self,
        store: FixtureStore,
        name: str,
        object_id: str,
        device_class: BinarySensorDeviceClass,
    ) -> None:
        self._store = store
        self._attr_name = name
        self._attr_unique_id = f"smart_shading_fixture_{object_id}"
        self._attr_device_class = device_class
        self._on = False
        self._available = True

    @property
    def is_on(self) -> bool:
        return self._on

    @property
    def available(self) -> bool:
        return self._available

    async def async_added_to_hass(self) -> None:
        self._store.register(self)

    def set_fixture_state(
        self, state: Any, _attributes: dict[str, Any], available: bool
    ) -> None:
        self._available = available
        self._on = state in {True, 1, "1", "on", "true", "True"}
