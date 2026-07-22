"""Shared deterministic state for the Smart Shading E2E fixture."""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

DOMAIN = "smart_shading_test_fixture"


class FixtureStore:
    """Keep fixture entities and every cover command in one place."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.entities: dict[str, Any] = {}
        self.calls: list[dict[str, Any]] = []
        self.recorder: Any | None = None

    def register(self, entity: Any) -> None:
        self.entities[entity.entity_id] = entity

    def record(self, service: str, data: dict[str, Any]) -> None:
        self.calls.append(
            {
                "domain": "cover",
                "service": service,
                "data": dict(data),
            }
        )
        if self.recorder is not None:
            self.recorder.async_write_ha_state()

    def reset_calls(self) -> None:
        self.calls.clear()
        if self.recorder is not None:
            self.recorder.async_write_ha_state()


def get_store(hass: HomeAssistant) -> FixtureStore:
    """Return the fixture store, independent of platform setup order."""
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = FixtureStore(hass)
    return hass.data[DOMAIN]
