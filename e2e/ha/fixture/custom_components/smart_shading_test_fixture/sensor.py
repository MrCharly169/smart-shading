"""Deterministic numeric sensors and call recorder for E2E tests."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import LIGHT_LUX, UnitOfTemperature
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
            FixtureNumberSensor(
                store,
                "Easy Lux",
                "easy_lux",
                0,
                SensorDeviceClass.ILLUMINANCE,
                LIGHT_LUX,
            ),
            FixtureNumberSensor(
                store,
                "Advanced Lux",
                "advanced_lux",
                0,
                SensorDeviceClass.ILLUMINANCE,
                LIGHT_LUX,
            ),
            FixtureNumberSensor(
                store,
                "Irradiance",
                "irradiance",
                0,
                None,
                "W/m²",
            ),
            FixtureNumberSensor(
                store,
                "Cloud Cover",
                "cloud_cover",
                0,
                None,
                "%",
            ),
            FixtureNumberSensor(
                store,
                "Indoor Temperature",
                "indoor_temperature",
                22,
                SensorDeviceClass.TEMPERATURE,
                UnitOfTemperature.CELSIUS,
            ),
            FixtureNumberSensor(
                store,
                "Outdoor Temperature",
                "outdoor_temperature",
                20,
                SensorDeviceClass.TEMPERATURE,
                UnitOfTemperature.CELSIUS,
            ),
            FixtureCallRecorder(store),
        ]
    )


class FixtureNumberSensor(SensorEntity):
    _attr_should_poll = False

    def __init__(
        self,
        store: FixtureStore,
        name: str,
        object_id: str,
        value: float,
        device_class: SensorDeviceClass | None,
        unit: str,
    ) -> None:
        self._store = store
        self._attr_name = name
        self._attr_unique_id = f"smart_shading_fixture_{object_id}"
        self._attr_native_value = value
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._available = True

    @property
    def available(self) -> bool:
        return self._available

    async def async_added_to_hass(self) -> None:
        self._store.register(self)

    def set_fixture_state(
        self, state: Any, _attributes: dict[str, Any], available: bool
    ) -> None:
        self._available = available
        if state is not None:
            self._attr_native_value = state


class FixtureCallRecorder(SensorEntity):
    _attr_name = "Fixture Service Calls"
    _attr_unique_id = "smart_shading_fixture_service_calls"
    _attr_native_unit_of_measurement = "calls"
    _attr_icon = "mdi:format-list-bulleted"
    _attr_should_poll = False

    def __init__(self, store: FixtureStore) -> None:
        self._store = store

    @property
    def native_value(self) -> int:
        return len(self._store.calls)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"calls": list(self._store.calls)}

    async def async_added_to_hass(self) -> None:
        self._store.register(self)
        self._store.recorder = self

    def set_fixture_state(
        self, _state: Any, _attributes: dict[str, Any], _available: bool
    ) -> None:
        return
