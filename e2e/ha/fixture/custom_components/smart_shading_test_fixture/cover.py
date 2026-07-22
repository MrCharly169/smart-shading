"""Deterministic controllable cover platform for E2E tests."""
from __future__ import annotations

from typing import Any

from homeassistant.components.cover import CoverEntity, CoverEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .store import get_store


async def async_setup_platform(
    hass: HomeAssistant,
    _config: dict[str, Any],
    async_add_entities: AddEntitiesCallback,
    _discovery_info: dict[str, Any] | None = None,
) -> None:
    async_add_entities(
        [
            FixtureCover(hass, "Easy Venetian", "easy_venetian", supports_position=True, supports_tilt=True),
            FixtureCover(
                hass,
                "Easy Roller Shutter",
                "easy_roller_shutter",
                supports_position=True,
                supports_tilt=False,
            ),
            FixtureCover(hass, "Advanced Screen", "advanced_screen", supports_position=True, supports_tilt=False),
            FixtureCover(hass, "Advanced Curtain", "advanced_curtain", supports_position=True, supports_tilt=False),
            FixtureCover(hass, "Advanced Vertical Blind", "advanced_vertical", supports_position=True, supports_tilt=True),
            FixtureCover(hass, "Advanced Awning", "advanced_awning", supports_position=True, supports_tilt=False),
            FixtureCover(hass, "Binary Cover", "binary_cover", supports_position=False, supports_tilt=False),
        ]
    )


class FixtureCover(CoverEntity):
    """A position/tilt cover that records every command."""

    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        object_id: str,
        *,
        supports_position: bool,
        supports_tilt: bool,
    ) -> None:
        self._store = get_store(hass)
        self._attr_name = name
        self._attr_unique_id = f"smart_shading_fixture_{object_id}"
        self._supports_tilt = supports_tilt
        self._supports_position = supports_position
        self._attr_supported_features = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
        )
        if supports_position:
            self._attr_supported_features |= CoverEntityFeature.SET_POSITION
        if supports_tilt:
            self._attr_supported_features |= (
                CoverEntityFeature.OPEN_TILT
                | CoverEntityFeature.CLOSE_TILT
                | CoverEntityFeature.SET_TILT_POSITION
            )
        self._position = 100
        self._tilt = 100
        self._available = True

    @property
    def available(self) -> bool:
        return self._available

    @property
    def current_cover_position(self) -> int | None:
        return self._position if self._supports_position else None

    @property
    def current_cover_tilt_position(self) -> int | None:
        return self._tilt if self._supports_tilt else None

    @property
    def is_closed(self) -> bool:
        return self._position == 0

    async def async_added_to_hass(self) -> None:
        self._store.register(self)

    def set_fixture_state(
        self, state: Any, attributes: dict[str, Any], available: bool
    ) -> None:
        self._available = available
        if "current_position" in attributes:
            self._position = int(attributes["current_position"])
        elif state == "closed":
            self._position = 0
        elif state == "open":
            self._position = 100
        if "current_tilt_position" in attributes:
            self._tilt = int(attributes["current_tilt_position"])

    async def async_open_cover(self, **_kwargs: Any) -> None:
        self._position = 100
        self._store.record("open_cover", {"entity_id": self.entity_id})
        self.async_write_ha_state()

    async def async_close_cover(self, **_kwargs: Any) -> None:
        self._position = 0
        self._store.record("close_cover", {"entity_id": self.entity_id})
        self.async_write_ha_state()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        self._position = int(kwargs["position"])
        self._store.record(
            "set_cover_position",
            {"entity_id": self.entity_id, "position": self._position},
        )
        self.async_write_ha_state()

    async def async_open_cover_tilt(self, **_kwargs: Any) -> None:
        self._tilt = 100
        self._store.record("open_cover_tilt", {"entity_id": self.entity_id})
        self.async_write_ha_state()

    async def async_close_cover_tilt(self, **_kwargs: Any) -> None:
        self._tilt = 0
        self._store.record("close_cover_tilt", {"entity_id": self.entity_id})
        self.async_write_ha_state()

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        self._tilt = int(kwargs["tilt_position"])
        self._store.record(
            "set_cover_tilt_position",
            {"entity_id": self.entity_id, "tilt_position": self._tilt},
        )
        self.async_write_ha_state()
