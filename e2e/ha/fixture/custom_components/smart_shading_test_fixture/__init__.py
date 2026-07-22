"""Controllable entities used only by the Smart Shading E2E laboratory."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .store import DOMAIN, get_store


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Register fixture control services."""
    store = get_store(hass)

    async def async_set_state(call: ServiceCall) -> None:
        entity_id = str(call.data["entity_id"])
        entity = store.entities.get(entity_id)
        state = call.data.get("state")
        attributes = dict(call.data.get("attributes") or {})
        available = bool(call.data.get("available", True))
        if entity is not None:
            entity.set_fixture_state(state, attributes, available)
            entity.async_write_ha_state()
            return

        # sun.sun is fixture-owned in the E2E lab so solar geometry remains
        # deterministic. Smart Shading still consumes a normal Home Assistant
        # state object, exactly as it does with the real Sun integration.
        if available:
            hass.states.async_set(entity_id, str(state), attributes)
        else:
            hass.states.async_set(entity_id, "unavailable", attributes)

    async def async_reset_calls(_call: ServiceCall) -> None:
        store.reset_calls()

    async def async_set_entry_enabled(call: ServiceCall) -> None:
        entry_id = str(call.data["entry_id"])
        enabled = bool(call.data["enabled"])
        disabled_by = None if enabled else ConfigEntryDisabler.USER
        if not await hass.config_entries.async_set_disabled_by(
            entry_id, disabled_by
        ):
            raise HomeAssistantError(
                f"Config entry {entry_id} could not be "
                f"{'enabled' if enabled else 'disabled'}"
            )

    async def async_registry_snapshot(_call: ServiceCall) -> dict[str, Any]:
        """Return Smart Shading's live HA registry ownership for E2E audit."""
        device_registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)
        return {
            "devices": [
                {
                    "id": device.id,
                    "config_entries": sorted(device.config_entries),
                    "identifiers": sorted(device.identifiers),
                }
                for device in device_registry.devices.values()
                if any(
                    domain == "smart_shading"
                    for domain, _identifier in device.identifiers
                )
            ],
            "entities": [
                {
                    "entity_id": entity.entity_id,
                    "config_entry_id": entity.config_entry_id,
                }
                for entity in entity_registry.entities.values()
                if entity.platform == "smart_shading"
            ],
        }

    hass.services.async_register(DOMAIN, "set_state", async_set_state)
    hass.services.async_register(DOMAIN, "reset_calls", async_reset_calls)
    hass.services.async_register(
        DOMAIN, "set_entry_enabled", async_set_entry_enabled
    )
    hass.services.async_register(
        DOMAIN,
        "registry_snapshot",
        async_registry_snapshot,
        supports_response=SupportsResponse.ONLY,
    )
    return True
