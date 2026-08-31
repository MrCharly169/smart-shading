#!/usr/bin/env python3
"""Drive Smart Shading through a real Home Assistant HTTP API."""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


LIVE_WIZARD_COVERAGE: dict[str, set[str]] = {}
LIVE_WIZARD_TRANSITIONS: set[str] = set()
OPTIONS_SURFACE_PATHS: dict[tuple[str, str], tuple[str, ...]] = {}
INITIAL_ADVANCED_WIZARD_COVERAGE: dict[str, set[str]] = {}
CAPTURE_INITIAL_ADVANCED_WIZARD = False
ADVANCED_FEATURE_KEYS = (
    "schedule",
    "temperature",
    "night",
    "safety",
    "conditions",
    "glare_protection",
    "test_tools",
    "expert_execution",
)
RETIRED_LEGACY_OPTIONAL_BUTTON_SUFFIXES = (
    "_reset_sun_detection",
    "_evaluate_now",
    "_export_room_diagnostic_log",
    "_reset_finished_today_state",
    "_evaluate_all_rooms_now",
    "_export_diagnostic_log",
)
NON_SETTING_SCHEMA_FIELDS = {
    "next_step_id",
    "name",
    "short",
    "room_details",
    "profile_behavior",
    "target_positions",
    "slat_curve",
    "schedule_settings",
    "temperature_settings",
    "execution_settings",
    "sector_identity",
    "sector_maintenance",
    "group_identity",
    "group_maintenance",
    "cover_identity",
    "cover_automation",
    "cover_maintenance",
    "protected_zone_identity",
    "protected_zone_geometry",
    "protected_zone_target",
    "protected_zone_window",
    "protected_zone_object",
    "protected_zone_activation",
    "protected_zone_conditions",
    "protected_zone_maintenance",
}


@dataclass
class ApiError(RuntimeError):
    method: str
    path: str
    status: int
    body: str

    def __str__(self) -> str:
        return f"{self.method} {self.path} failed with HTTP {self.status}: {self.body}"


def is_retired_legacy_optional_entity(entity_id: str) -> bool:
    """Identify unsolicited legacy buttons replaced by explicit feature opt-in."""
    return entity_id.startswith("button.smart_shading_") and entity_id.endswith(
        RETIRED_LEGACY_OPTIONAL_BUTTON_SUFFIXES
    )


class HomeAssistantApi:
    def __init__(self, base_url: str, token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
        *,
        form: bool = False,
        authenticated: bool = True,
    ) -> Any:
        headers: dict[str, str] = {}
        payload = None
        if data is not None:
            if form:
                payload = urlencode(data).encode()
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            else:
                payload = json.dumps(data).encode()
                headers["Content-Type"] = "application/json"
        if authenticated and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(
            f"{self.base_url}{path}", data=payload, headers=headers, method=method
        )
        try:
            with urlopen(request, timeout=20) as response:
                body = response.read().decode()
                return json.loads(body) if body else None
        except HTTPError as exc:
            body = exc.read().decode(errors="replace")
            raise ApiError(method, path, exc.code, body) from exc

    def get(self, path: str, *, authenticated: bool = True) -> Any:
        return self.request("GET", path, authenticated=authenticated)

    def post(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        *,
        authenticated: bool = True,
    ) -> Any:
        return self.request("POST", path, data or {}, authenticated=authenticated)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)

    def call_service(self, domain: str, service: str, data: dict[str, Any]) -> Any:
        return self.post(f"/api/services/{domain}/{service}", data)


def wait_for_home_assistant(api: HomeAssistantApi, timeout: int = 180) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if api.token:
                api.get("/api/config")
            else:
                api.get("/api/onboarding", authenticated=False)
            return
        except (URLError, ApiError, TimeoutError, ConnectionError) as exc:
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"Home Assistant did not become ready: {last_error}")


def onboard(api: HomeAssistantApi) -> str:
    """Create a disposable owner and exchange its auth code for a token."""
    client_id = f"{api.base_url}/"
    user = api.post(
        "/api/onboarding/users",
        {
            "client_id": client_id,
            "name": "Smart Shading E2E",
            "username": "e2e-owner",
            "password": "e2e-only-disposable-password",
            "language": "en",
        },
        authenticated=False,
    )
    token_response = api.request(
        "POST",
        "/auth/token",
        {
            "grant_type": "authorization_code",
            "code": user["auth_code"],
            "client_id": client_id,
        },
        form=True,
        authenticated=False,
    )
    api.token = str(token_response["access_token"])
    onboarding = api.get("/api/onboarding", authenticated=False)
    done = {
        str(item.get("step"))
        for item in onboarding
        if isinstance(item, dict) and item.get("done")
    }
    available = {
        str(item.get("step")) for item in onboarding if isinstance(item, dict)
    }
    if "core_config" in available and "core_config" not in done:
        api.post(
            "/api/onboarding/core_config",
            {
                "latitude": 49.6116,
                "longitude": 6.1319,
                "elevation": 300,
                "unit_system": "metric",
                "location_name": "Smart Shading E2E",
                "time_zone": "UTC",
                "currency": "EUR",
            },
        )
    if "integration" in available and "integration" not in done:
        api.post(
            "/api/onboarding/integration",
            {
                "client_id": client_id,
                "redirect_uri": (
                    f"{api.base_url}/onboarding.html?auth_callback=1"
                ),
            },
        )
    if "analytics" in available and "analytics" not in done:
        api.post("/api/onboarding/analytics", {})
    remaining = [
        item
        for item in api.get("/api/onboarding", authenticated=False)
        if isinstance(item, dict) and not item.get("done")
    ]
    if remaining:
        raise AssertionError(
            f"Home Assistant onboarding remains incomplete: {remaining}"
        )
    return api.token


def wait_for_state(
    api: HomeAssistantApi,
    entity_id: str,
    predicate,
    timeout: int = 60,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        try:
            last = api.get(f"/api/states/{entity_id}")
            if predicate(last):
                return last
        except ApiError as exc:
            if exc.status != 404:
                raise
        time.sleep(1)
    raise AssertionError(f"Timed out waiting for {entity_id}; last state: {last}")


def set_fixture_state(
    api: HomeAssistantApi, entity_id: str, specification: dict[str, Any]
) -> None:
    api.call_service(
        "smart_shading_test_fixture",
        "set_state",
        {
            "entity_id": entity_id,
            "state": specification.get("state"),
            "attributes": specification.get("attributes", {}),
            "available": specification.get("available", True),
        },
    )


def apply_initial_state(api: HomeAssistantApi, scenario: dict[str, Any]) -> None:
    for entity_id, specification in scenario["initial"].items():
        set_fixture_state(api, entity_id, specification)


def expect_step(result: dict[str, Any], step_id: str) -> str:
    actual = result.get("step_id")
    if actual != step_id:
        raise AssertionError(
            f"Expected config-flow step {step_id!r}, got {actual!r}: {result}"
        )
    record_flow_surface(result)
    return str(result["flow_id"])


def _schema_fields(value: Any) -> set[str]:
    """Collect field names from HA's serialized flat or sectioned schema."""
    fields: set[str] = set()
    if isinstance(value, list):
        for item in value:
            fields.update(_schema_fields(item))
    elif isinstance(value, dict):
        name = value.get("name")
        if isinstance(name, str):
            fields.add(name)
        for nested in value.values():
            fields.update(_schema_fields(nested))
    return fields


def record_flow_surface(result: dict[str, Any]) -> None:
    step_id = result.get("step_id")
    if not isinstance(step_id, str):
        return
    fields = _schema_fields(result.get("data_schema", []))
    LIVE_WIZARD_COVERAGE.setdefault(step_id, set()).update(fields)
    if CAPTURE_INITIAL_ADVANCED_WIZARD:
        owner = _initial_wizard_setting_owner(step_id, fields)
        INITIAL_ADVANCED_WIZARD_COVERAGE.setdefault(owner, set()).update(
            fields
        )


def _initial_wizard_setting_owner(
    step_id: str, fields: set[str]
) -> str:
    """Return the customer-facing owner of one dynamic wizard form."""
    if step_id == "manage_automation":
        sections = {
            section
            for section in (
                "schedule_settings",
                "temperature_settings",
                "execution_settings",
            )
            if section in fields
        }
        if len(sections) != 1:
            raise AssertionError(
                "Advanced automation page must contain exactly one feature, "
                f"got {sorted(sections)} with fields {sorted(fields)}"
            )
        return {
            "schedule_settings": "manage_schedule",
            "temperature_settings": "manage_temperature",
            "execution_settings": "manage_execution",
        }[next(iter(sections))]
    if step_id == "manage_conditions":
        has_safety = bool(
            fields & {"safety_blockers", "safety_behavior"}
        )
        has_weather = bool(
            fields
            & {
                "irradiance_sensor",
                "irradiance_minimum",
                "cloud_cover_sensor",
                "cloud_cover_maximum",
                "weather_permission",
                "occupancy_sensor",
                "weather_logic",
                "comfort_requires_occupancy",
                "heat_ignores_weather",
                "heat_requires_sun",
            }
        )
        if has_safety == has_weather:
            raise AssertionError(
                "Protection page must contain exactly one feature, "
                f"got safety={has_safety}, weather={has_weather} with "
                f"fields {sorted(fields)}"
            )
        return "manage_safety" if has_safety else "manage_weather_conditions"
    return step_id


def duplicate_wizard_setting_owners(
    coverage: dict[str, set[str]],
) -> dict[str, list[str]]:
    """Return settings that are owned by more than one wizard page."""
    owners: dict[str, set[str]] = {}
    for page, fields in coverage.items():
        for field in fields:
            if field in NON_SETTING_SCHEMA_FIELDS:
                continue
            owners.setdefault(field, set()).add(page)
    return {
        field: sorted(pages)
        for field, pages in sorted(owners.items())
        if len(pages) > 1
    }


def _menu_options(result: dict[str, Any]) -> list[str]:
    raw = result.get("menu_options") or []
    if isinstance(raw, dict):
        return [str(item) for item in raw]
    return [str(item) for item in raw]


def submit_flow(
    api: HomeAssistantApi, flow_id: str, step_id: str, data: dict[str, Any]
) -> dict[str, Any]:
    result = api.post(f"/api/config/config_entries/flow/{flow_id}", data)
    if result.get("errors"):
        raise AssertionError(f"Config-flow step {step_id} failed: {result}")
    return result


def continue_past_legacy_global_settings(
    api: HomeAssistantApi, flow_id: str, result: dict[str, Any]
) -> dict[str, Any]:
    """Submit the retired Sun form when bootstrapping an older release."""
    if result.get("step_id") != "global_settings":
        return result
    return submit_flow(
        api,
        flow_id,
        "global_settings",
        {"sun_entity": "sun.sun"},
    )


def continue_past_initial_structure_hub(
    api: HomeAssistantApi, flow_id: str, result: dict[str, Any]
) -> dict[str, Any]:
    """Complete the structure checkpoint when the installed version has it."""
    if result.get("step_id") != "initial_structure_hub":
        return result
    expect_step(result, "initial_structure_hub")
    return submit_flow(
        api,
        flow_id,
        "initial_structure_hub",
        {"next_step_id": "complete_initial_structure"},
    )


def supported_form_data(
    result: dict[str, Any], data: dict[str, Any]
) -> dict[str, Any]:
    """Limit a submission to fields exposed by the installed flow version."""
    supported = {
        str(field.get("name"))
        for field in result.get("data_schema", [])
        if isinstance(field, dict) and field.get("name")
    }
    if not supported:
        return data
    return {key: value for key, value in data.items() if key in supported}


def continue_past_retired_night_setup(
    api: HomeAssistantApi, flow_id: str, result: dict[str, Any]
) -> dict[str, Any]:
    """Complete per-layer Night and pause forms retired after v2026.7.1."""
    while result.get("step_id") == "initial_night_targets":
        expect_step(result, "initial_night_targets")
        result = submit_flow(
            api,
            flow_id,
            "initial_night_targets",
            supported_form_data(
                result,
                {"night_position": 0, "night_tilt": 100},
            ),
        )
    if result.get("step_id") == "manage_pause":
        expect_step(result, "manage_pause")
        result = submit_flow(
            api,
            flow_id,
            "manage_pause",
            supported_form_data(
                result,
                {
                    "default_pause_mode": "next_sunrise",
                    "pause_sun_offset_minutes": -60,
                    "pause_duration_hours": 2,
                    "external_movement_detection": True,
                    "heat_during_pause": True,
                },
            ),
        )
    return result


def start_options_flow(
    api: HomeAssistantApi, entry_id: str
) -> tuple[str, dict[str, Any]]:
    """Open the real Home Assistant options flow for one config entry."""
    result = api.post(
        "/api/config/config_entries/options/flow", {"handler": entry_id}
    )
    flow_id = str(result.get("flow_id") or "")
    if not flow_id:
        raise AssertionError(f"Options flow did not start: {result}")
    return flow_id, result


def submit_options_flow(
    api: HomeAssistantApi, flow_id: str, step_id: str, data: dict[str, Any]
) -> dict[str, Any]:
    result = api.post(
        f"/api/config/config_entries/options/flow/{flow_id}", data
    )
    if result.get("errors"):
        raise AssertionError(f"Options-flow step {step_id} failed: {result}")
    return result


def create_easy_entry(
    api: HomeAssistantApi,
    scenario: dict[str, Any],
    *,
    include_dashboard_badges: bool = True,
) -> str:
    """Create an Easy entry through the current guided flow."""
    setup = scenario["setup"]
    result = api.post(
        "/api/config/config_entries/flow",
        {"handler": "smart_shading", "show_advanced_options": True},
    )
    flow_id = expect_step(result, "user")
    result = submit_flow(
        api,
        flow_id,
        "user",
        {
            "house_name": setup["house_name"],
            "setup_type": "simple",
        },
    )
    result = continue_past_legacy_global_settings(api, flow_id, result)
    expect_step(result, "room_setup")
    result = submit_flow(
        api,
        flow_id,
        "room_setup",
        {
            "room_details": {"name": setup["room_name"]},
        },
    )
    expect_step(result, "add_sector_flat")
    result = submit_flow(
        api,
        flow_id,
        "add_sector_flat",
        {
            "direction": "south",
            "name": "South",
            "short": "S",
            "sun_source": "external",
        },
    )
    expect_step(result, "configure_sector_source")
    result = submit_flow(
        api,
        flow_id,
        "configure_sector_source",
        {
            "sun_presence_entity": setup["sun_confirmation_entity"],
        },
    )
    expect_step(result, "add_sector_group")
    result = submit_flow(
        api,
        flow_id,
        "add_sector_group",
        {
            "name": "Roller shutters",
            "profile": "roller_shutter",
        },
    )
    expect_step(result, "add_sector_covers")
    result = submit_flow(
        api,
        flow_id,
        "add_sector_covers",
        {"cover_entities": [setup["cover_entity"]]},
    )
    expect_step(result, "compact_cover_details")
    result = submit_flow(
        api,
        flow_id,
        "compact_cover_details",
        {
            "name": "Easy Roller Shutter",
            "short": "C1",
        },
    )
    if include_dashboard_badges:
        expect_step(result, "choose_advanced_features")
        result = submit_flow(
            api,
            flow_id,
            "choose_advanced_features",
            supported_form_data(result, {"dashboard_badges": True}),
        )
        expect_step(result, "manage_dashboard_badges")
        result = submit_flow(
            api,
            flow_id,
            "manage_dashboard_badges",
            {},
        )
    expect_step(result, "init")
    result = submit_flow(api, flow_id, "init", {"next_step_id": "finish"})
    expect_step(result, "finish")
    result = submit_flow(api, flow_id, "finish", {"confirm_start": True})
    return _created_entry_id(api, result, setup["house_name"])


def _created_entry_id(
    api: HomeAssistantApi, result: dict[str, Any], title: str
) -> str:
    if result.get("type") != "create_entry":
        raise AssertionError(f"Config flow did not create an entry: {result}")
    entry_id = result.get("result", {}).get("entry_id")
    if entry_id:
        return str(entry_id)
    matching = [
        item for item in smart_shading_entries(api) if item.get("title") == title
    ]
    if len(matching) != 1:
        raise AssertionError(f"Cannot identify created config entry: {result}")
    return str(matching[0]["entry_id"])


def advanced_execution_settings_payload() -> dict[str, Any]:
    """Return the complete required Advanced automation section.

    Home Assistant validates the outer section schema before the integration
    can flatten it.  Keep every real-HA exercise on the same explicit
    execution defaults as a newly created Advanced room.
    """
    return {
        "command_stagger_seconds": 0.0,
        "stagger_scope": "room",
        "safety_bypasses_stagger": True,
        "target_verification_enabled": False,
        "verification_retries": 1,
        "movement_seconds": 45.0,
        "settling_seconds": 5.0,
        "source_stale_seconds": 0.0,
    }


def advanced_execution_settings_section(
    *, legacy_compatible: bool = False
) -> dict[str, dict[str, Any]]:
    """Return the required candidate section, absent from the old baseline."""
    if legacy_compatible:
        return {}
    return {"execution_settings": advanced_execution_settings_payload()}


def baseline_uses_legacy_wizard(version: str) -> bool:
    """Return whether an upgrade baseline predates the CalVer wizard."""
    normalized = str(version or "").strip().removeprefix("v")
    return not normalized.startswith("20")


def baseline_supports_dashboard_badges(version: str) -> bool:
    """Return whether a release already has the optional badge wizard step."""
    normalized = str(version or "").strip().removeprefix("v")
    match = re.fullmatch(
        r"(?P<year>20[0-9]{2})\.(?P<month>[0-9]{1,2})\."
        r"(?P<patch>[0-9]+)(?:b(?P<beta>[0-9]+))?",
        normalized,
    )
    if match is None:
        return False
    release_base = tuple(
        int(match.group(name)) for name in ("year", "month", "patch")
    )
    badge_base = (2026, 8, 0)
    if release_base != badge_base:
        return release_base > badge_base
    beta = match.group("beta")
    return beta is None or int(beta) >= 2


def create_advanced_entry(
    api: HomeAssistantApi,
    scenario: dict[str, Any],
    *,
    legacy_compatible: bool = False,
    include_test_tools: bool = True,
    include_dashboard_badges: bool = True,
) -> str:
    """Exercise Advanced setup, optionally avoiding broken legacy optionals."""
    global CAPTURE_INITIAL_ADVANCED_WIZARD
    INITIAL_ADVANCED_WIZARD_COVERAGE.clear()
    CAPTURE_INITIAL_ADVANCED_WIZARD = not legacy_compatible
    setup = scenario["advanced_setup"]
    result = api.post(
        "/api/config/config_entries/flow",
        {"handler": "smart_shading", "show_advanced_options": True},
    )
    flow_id = expect_step(result, "user")
    result = submit_flow(
        api,
        flow_id,
        "user",
        {
            "house_name": setup["house_name"],
            "setup_type": "complete",
        },
    )
    result = continue_past_legacy_global_settings(api, flow_id, result)
    expect_step(result, "room_setup")
    room_details = {
        "name": setup["room_name"],
        "outdoor_temperature": setup["outdoor_temperature_entity"],
    }
    if legacy_compatible:
        room_details["indoor_temperature"] = setup[
            "indoor_temperature_entity"
        ]
    result = submit_flow(
        api,
        flow_id,
        "room_setup",
        {"room_details": room_details},
    )
    expect_step(result, "configure_outdoor_temperature")
    result = submit_flow(
        api,
        flow_id,
        "configure_outdoor_temperature",
        {"outdoor_minimum": 12},
    )
    expect_step(result, "add_sector_flat")
    result = submit_flow(
        api,
        flow_id,
        "add_sector_flat",
        {
            "direction": "custom",
            "name": "Advanced South",
            "short": "AS",
            "sun_source": "lux",
        },
    )
    expect_step(result, "manage_sector_geometry")
    result = submit_flow(
        api,
        flow_id,
        "manage_sector_geometry",
        {"azimuth_start": 120, "azimuth_end": 240, "elevation_min": 10},
    )
    expect_step(result, "configure_sector_source")
    result = submit_flow(
        api,
        flow_id,
        "configure_sector_source",
        {"lux_sensor": setup["lux_entity"], "sun_preset": "custom"},
    )
    expect_step(result, "configure_lux_profile")
    result = submit_flow(
        api,
        flow_id,
        "configure_lux_profile",
        {
            "sun_on_lux": 100,
            "sun_off_lux": 50,
            "sun_on_delay": 0,
            "sun_off_delay": 0,
        },
    )
    expect_step(result, "add_sector_group")
    result = submit_flow(
        api,
        flow_id,
        "add_sector_group",
        {
            "name": "Advanced Venetian",
            "profile": "venetian",
        },
    )
    expect_step(result, "manage_layer_profile")
    initial_targets = {
        "open_position": 100,
        "open_tilt": 0,
    }
    if legacy_compatible:
        initial_targets["heat_tilt"] = 100
    result = submit_flow(
        api,
        flow_id,
        "manage_layer_profile",
        {
            "profile_behavior": {
                "position_tolerance": 5,
                "tilt_preset": "balanced",
                "tilt_tolerance": 5,
            },
            "target_positions": initial_targets,
        },
    )
    expect_step(result, "add_sector_covers")
    result = submit_flow(
        api,
        flow_id,
        "add_sector_covers",
        {"cover_entities": [setup["cover_entity"]]},
    )
    expect_step(result, "compact_cover_details")
    result = submit_flow(
        api,
        flow_id,
        "compact_cover_details",
        {
            "name": "Advanced Venetian",
            "short": "A1",
            "lock": "input_boolean.fixture_manual_override",
            "window": setup["window_entity"],
            "window_safe_state": "off",
            "window_policy": "block_closing",
            "window_returns_to_automation": True,
            "invert_position": False,
            "invert_tilt": False,
        },
    )
    if legacy_compatible:
        expect_step(result, "manage_cover_special")
        result = submit_flow(
            api,
            flow_id,
            "manage_cover_special",
            {"enforce_max_open_position": True},
        )
        expect_step(result, "manage_cover_special")
        result = submit_flow(
            api,
            flow_id,
            "manage_cover_special",
            {"enforce_max_open_position": True, "max_open_position": 90},
        )
        expect_step(result, "manage_automation")
        temperature_settings = {
            "heat_temperature": 27,
            "evening_release_time": "18:00:00",
            "sunset_offset_minutes": 0,
            "normal_shading_temperature": 23.5,
            "reopen_temperature": 22,
        }
        result = submit_flow(
            api,
            flow_id,
            "manage_automation",
            {
                "schedule_settings": {"schedule_enabled": True},
                "temperature_settings": temperature_settings,
            },
        )
        expect_step(result, "manage_automation")
        result = submit_flow(
            api,
            flow_id,
            "manage_automation",
            {
                "schedule_settings": {
                    "schedule_enabled": True,
                    "schedule_profile": "custom",
                    "day_window": "fixed_time",
                },
                "temperature_settings": temperature_settings,
            },
        )
        expect_step(result, "manage_automation")
        result = submit_flow(
            api,
            flow_id,
            "manage_automation",
            {
                "schedule_settings": {
                    "schedule_enabled": True,
                    "schedule_profile": "custom",
                    "day_window": "fixed_time",
                    "active_months": [
                        str(value) for value in range(1, 13)
                    ],
                    "active_weekdays": [str(value) for value in range(7)],
                    "start_time": "06:00:00",
                    "end_time": "22:00:00",
                    "outside_schedule_behavior": "open",
                },
                "temperature_settings": temperature_settings,
            },
        )
        expect_step(result, "manage_night")
        result = submit_flow(
            api, flow_id, "manage_night", {"night_enabled": False}
        )
        expect_step(result, "manage_pause")
        result = submit_flow(
            api,
            flow_id,
            "manage_pause",
            {
                "default_pause_mode": "next_sunrise",
                "pause_sun_offset_minutes": -60,
                "pause_duration_hours": 2,
                "external_movement_detection": True,
                "heat_during_pause": True,
            },
        )
        expect_step(result, "manage_conditions")
        result = submit_flow(
            api,
            flow_id,
            "manage_conditions",
            {"heat_requires_sun": True},
        )
        expect_step(result, "init")
        result = submit_flow(
            api, flow_id, "init", {"next_step_id": "finish"}
        )
        expect_step(result, "finish")
        result = submit_flow(
            api, flow_id, "finish", {"confirm_start": True}
        )
        CAPTURE_INITIAL_ADVANCED_WIZARD = False
        return _created_entry_id(api, result, setup["house_name"])
    result = continue_past_initial_structure_hub(api, flow_id, result)
    expect_step(result, "choose_advanced_features")
    advanced_features = {
        "schedule": True,
        "temperature": True,
        "night": not legacy_compatible,
        "safety": not legacy_compatible,
        "conditions": True,
        "maximum_opening": True,
        "dashboard_badges": include_dashboard_badges,
        "test_tools": not legacy_compatible and include_test_tools,
        "expert_execution": not legacy_compatible,
    }
    result = submit_flow(
        api,
        flow_id,
        "choose_advanced_features",
        supported_form_data(result, advanced_features),
    )
    expect_step(result, "manage_automation")
    result = submit_flow(
        api,
        flow_id,
        "manage_automation",
        {
            "schedule_settings": {
                "schedule_profile": "custom",
                "day_window": "fixed_time",
                "active_months": [str(value) for value in range(1, 13)],
                "active_weekdays": [str(value) for value in range(7)],
                "start_time": "06:00:00",
                "end_time": "22:00:00",
                "outside_schedule_behavior": "open",
            },
        },
    )
    expect_step(result, "manage_automation")
    result = submit_flow(
        api,
        flow_id,
        "manage_automation",
        {
            "temperature_settings": {
                "indoor_temperature": setup["indoor_temperature_entity"],
                "heat_temperature": 27,
                "evening_release_time": "18:00:00",
                "sunset_offset_minutes": 0,
                "normal_shading_temperature": 23.5,
                "reopen_temperature": 22,
            }
        },
    )
    expect_step(result, "manage_night")
    night_source = {
        "night_source": "sun",
        "night_morning_transition_minutes": 0,
        "night_evening_transition_minutes": 0,
    }
    result = submit_flow(
        api,
        flow_id,
        "manage_night",
        supported_form_data(result, night_source),
    )
    expect_step(result, "manage_night")
    night_offsets = {
        "night_source": "sun",
        "night_start_offset_minutes": 0,
        "night_end_offset_minutes": 0,
        "night_morning_transition_minutes": 0,
        "night_evening_transition_minutes": 0,
    }
    result = submit_flow(
        api,
        flow_id,
        "manage_night",
        supported_form_data(result, night_offsets),
    )
    result = continue_past_retired_night_setup(api, flow_id, result)
    expect_step(result, "manage_conditions")
    safety_conditions = {
        "safety_blockers": [setup["safety_entity"]],
        "safety_behavior": "move_safe",
        "safety_position": 100,
        "safety_tilt": 0,
    }
    result = submit_flow(
        api,
        flow_id,
        "manage_conditions",
        supported_form_data(result, safety_conditions),
    )
    expect_step(result, "manage_conditions")
    condition_sources = {
        "irradiance_sensor": "sensor.irradiance",
        "cloud_cover_sensor": "sensor.cloud_cover",
        "weather_permission": "binary_sensor.weather_permission",
        "occupancy_sensor": "binary_sensor.occupancy",
        "heat_requires_sun": True,
        "irradiance_minimum": 150,
        "cloud_cover_maximum": 85,
        "weather_logic": "all",
        "comfort_requires_occupancy": False,
        "heat_ignores_weather": True,
    }
    result = submit_flow(
        api,
        flow_id,
        "manage_conditions",
        supported_form_data(result, condition_sources),
    )
    if result.get("step_id") == "initial_maximum_opening":
        expect_step(result, "initial_maximum_opening")
        maximum_opening = {
            "enforce_max_open_position": True,
            "max_open_position": 90,
        }
        result = submit_flow(
            api,
            flow_id,
            "initial_maximum_opening",
            supported_form_data(result, maximum_opening),
        )
    if include_dashboard_badges:
        expect_step(result, "manage_dashboard_badges")
        result = submit_flow(
            api,
            flow_id,
            "manage_dashboard_badges",
            {},
        )
    expect_step(result, "manage_automation")
    result = submit_flow(
        api,
        flow_id,
        "manage_automation",
        {"execution_settings": advanced_execution_settings_payload()},
    )
    expect_step(result, "init")
    result = submit_flow(api, flow_id, "init", {"next_step_id": "finish"})
    expect_step(result, "finish")
    result = submit_flow(api, flow_id, "finish", {"confirm_start": True})
    CAPTURE_INITIAL_ADVANCED_WIZARD = False
    return _created_entry_id(api, result, setup["house_name"])


def add_easy_room_through_options(
    api: HomeAssistantApi, scenario: dict[str, Any], entry_id: str
) -> None:
    """Create a second room through the real options flow and save it."""
    room = scenario["options_room"]
    flow_id, result = start_options_flow(api, entry_id)
    expect_step(result, "init")
    result = submit_options_flow(
        api, flow_id, "init", {"next_step_id": "add_room"}
    )
    expect_step(result, "add_room")
    result = submit_options_flow(
        api,
        flow_id,
        "add_room",
        {"room_details": {"name": room["room_name"]}},
    )
    expect_step(result, "add_sector_flat")
    result = submit_options_flow(
        api,
        flow_id,
        "add_sector_flat",
        {
            "name": "North",
            "short": "N",
            "direction": "north",
            "sun_source": "geometry",
        },
    )
    expect_step(result, "add_sector_group")
    result = submit_options_flow(
        api,
        flow_id,
        "add_sector_group",
        {"name": "Binary covers", "profile": "binary_cover"},
    )
    expect_step(result, "add_sector_covers")
    result = submit_options_flow(
        api,
        flow_id,
        "add_sector_covers",
        {"cover_entities": [room["cover_entity"]]},
    )
    expect_step(result, "compact_cover_details")
    result = submit_options_flow(
        api,
        flow_id,
        "compact_cover_details",
        {"name": "Binary Test Cover", "short": "C2"},
    )
    expect_step(result, "choose_advanced_features")
    result = submit_options_flow(
        api,
        flow_id,
        "choose_advanced_features",
        supported_form_data(result, {"dashboard_badges": True}),
    )
    expect_step(result, "manage_dashboard_badges")
    result = submit_options_flow(
        api,
        flow_id,
        "manage_dashboard_badges",
        {},
    )
    expect_step(result, "room_hub")
    result = submit_options_flow(
        api, flow_id, "room_hub", {"next_step_id": "back_to_overview"}
    )
    expect_step(result, "init")
    result = submit_options_flow(
        api, flow_id, "init", {"next_step_id": "finish"}
    )
    if result.get("type") != "create_entry":
        raise AssertionError(f"Options flow did not save the added room: {result}")
    wait_for_entry_loaded(api, entry_id)


def explore_options_surfaces(
    api: HomeAssistantApi, entry_id: str, *, maximum_depth: int = 7
) -> None:
    """Walk every reachable options menu against real HA without saving forms."""
    queue: list[tuple[str, ...]] = [tuple()]
    expanded: set[tuple[str, tuple[str, ...]]] = set()
    while queue:
        path = queue.pop(0)
        flow_id, result = start_options_flow(api, entry_id)
        try:
            for choice in path:
                result = submit_options_flow(
                    api,
                    flow_id,
                    str(result.get("step_id") or "menu"),
                    {"next_step_id": choice},
                )
            record_flow_surface(result)
            step_id = str(result.get("step_id") or "")
            if step_id:
                OPTIONS_SURFACE_PATHS[(entry_id, step_id)] = path
            options = _menu_options(result)
            signature = (str(result.get("step_id") or ""), tuple(options))
            if (
                result.get("type") == "menu"
                and len(path) < maximum_depth
                and signature not in expanded
            ):
                expanded.add(signature)
                for option in options:
                    if option == "finish" or option.startswith("back_"):
                        continue
                    queue.append((*path, option))
        finally:
            try:
                api.delete(
                    f"/api/config/config_entries/options/flow/{flow_id}"
                )
            except ApiError as exc:
                if exc.status not in {404, 405}:
                    raise


def replay_options_path(
    api: HomeAssistantApi, entry_id: str, target_step: str
) -> tuple[str, dict[str, Any]]:
    path = OPTIONS_SURFACE_PATHS.get((entry_id, target_step))
    if path is None:
        raise AssertionError(f"No discovered options path for {target_step}")
    flow_id, result = start_options_flow(api, entry_id)
    for choice in path:
        result = submit_options_flow(
            api,
            flow_id,
            str(result.get("step_id") or "menu"),
            {"next_step_id": choice},
        )
    expect_step(result, target_step)
    return flow_id, result


def advanced_feature_payload(
    configuration: dict[str, Any],
    *,
    add: tuple[str, ...] = (),
    remove: tuple[str, ...] = (),
    visible_fields: set[str] | None = None,
) -> dict[str, bool]:
    """Return the complete feature selector state for one existing room."""
    selected = set(configuration.get("advanced_features") or ())
    selected.update(add)
    selected.difference_update(remove)
    return {
        key: key in selected
        for key in ADVANCED_FEATURE_KEYS
        if visible_fields is None or key in visible_fields
    }


def replay_advanced_feature(
    api: HomeAssistantApi,
    entry_id: str,
    action: str,
    expected_step: str,
) -> tuple[str, dict[str, Any]]:
    """Open one focused feature from the Advanced Features menu."""
    flow_id, result = replay_options_path(
        api, entry_id, "advanced_features_hub"
    )
    result = submit_options_flow(
        api,
        flow_id,
        "advanced_features_hub",
        {"next_step_id": action},
    )
    expect_step(result, expected_step)
    return flow_id, result


def _profile_form_payload(profile: str) -> dict[str, Any]:
    targets = {
        "venetian": {
            "open_position": 100, "open_tilt": 0, "heat_tilt": 100,
            "night_position": 0, "night_tilt": 100,
            "safety_position": 100, "safety_tilt": 0,
        },
        "vertical_blind": {
            "open_position": 100, "open_tilt": 0, "comfort_tilt": 35,
            "heat_tilt": 100, "night_position": 0, "night_tilt": 100,
        },
        "roller_shutter": {
            "open_position": 100, "comfort_position": 65,
            "solar_position": 25, "heat_position": 0,
            "night_position": 0, "safety_position": 100,
        },
        "exterior_screen": {
            "open_position": 100, "comfort_position": 60,
            "solar_position": 15, "heat_position": 0,
            "night_position": 0, "safety_position": 100,
        },
        "curtain": {
            "open_position": 100, "comfort_position": 60,
            "solar_position": 30, "heat_position": 30,
            "night_position": 0,
        },
        "awning": {
            "open_position": 0, "comfort_position": 60,
            "solar_position": 100, "heat_position": 100,
            "night_position": 0, "safety_position": 0,
        },
    }[profile]
    behavior: dict[str, Any] = {"position_tolerance": 5}
    if profile in {"venetian", "vertical_blind"}:
        behavior.update(
            {"tilt_preset": "balanced", "tilt_tolerance": 5}
        )
    return {"profile_behavior": behavior, "target_positions": targets}


def save_options_from_group_hub(
    api: HomeAssistantApi, flow_id: str, result: dict[str, Any]
) -> None:
    for step_id, choice, expected in (
        ("group_hub", "back_to_sector", "sector_hub"),
        ("sector_hub", "back_to_structure", "structure_hub"),
        ("structure_hub", "back_to_room", "room_hub"),
        ("room_hub", "back_to_overview", "init"),
    ):
        expect_step(result, step_id)
        result = submit_options_flow(
            api, flow_id, step_id, {"next_step_id": choice}
        )
        expect_step(result, expected)
    result = submit_options_flow(
        api, flow_id, "init", {"next_step_id": "finish"}
    )
    if result.get("type") != "create_entry":
        raise AssertionError(f"Options flow did not save group changes: {result}")


def save_options_from_room_hub(
    api: HomeAssistantApi, flow_id: str, result: dict[str, Any]
) -> None:
    """Persist an edited room through the same review exit used by customers."""
    expect_step(result, "room_hub")
    result = submit_options_flow(
        api, flow_id, "room_hub", {"next_step_id": "back_to_overview"}
    )
    expect_step(result, "init")
    result = submit_options_flow(
        api, flow_id, "init", {"next_step_id": "finish"}
    )
    if result.get("type") != "create_entry":
        raise AssertionError(f"Options flow did not save room changes: {result}")


def assert_existing_room_night_transition(
    api: HomeAssistantApi,
    scenario: dict[str, Any],
    entry_id: str,
) -> None:
    """Disable and re-enable Night through the room feature selection."""
    configuration = entry_room_state(api, entry_id).get(
        "attributes", {}
    ).get("configuration", {})
    flow_id, feature_form = replay_options_path(
        api, entry_id, "choose_advanced_features"
    )
    result = submit_options_flow(
        api,
        flow_id,
        "choose_advanced_features",
        advanced_feature_payload(
            configuration,
            remove=("night",),
            visible_fields=_schema_fields(
                feature_form.get("data_schema", [])
            ),
        ),
    )
    expect_step(result, "advanced_features_hub")
    result = submit_options_flow(
        api,
        flow_id,
        "advanced_features_hub",
        {"next_step_id": "back_to_room"},
    )
    save_options_from_room_hub(api, flow_id, result)
    reload_entry(api, entry_id)
    configuration = entry_room_state(api, entry_id).get("attributes", {}).get(
        "configuration", {}
    )
    if configuration.get("night_enabled") is not False:
        raise AssertionError(
            f"Night disable was not persisted for an existing room: {configuration}"
        )
    LIVE_WIZARD_TRANSITIONS.add(
        "existing_room.night_enabled.on_to_off.save_reload"
    )

    explore_options_surfaces(api, entry_id)
    configuration = entry_room_state(api, entry_id).get(
        "attributes", {}
    ).get("configuration", {})
    flow_id, feature_form = replay_options_path(
        api, entry_id, "choose_advanced_features"
    )
    result = submit_options_flow(
        api,
        flow_id,
        "choose_advanced_features",
        advanced_feature_payload(
            configuration,
            add=("night",),
            visible_fields=_schema_fields(
                feature_form.get("data_schema", [])
            ),
        ),
    )
    expect_step(result, "manage_night")
    night_values = {
        "night_source": "sun",
        "night_start_offset_minutes": 0,
        "night_end_offset_minutes": 0,
        "night_morning_transition_minutes": 0,
        "night_evening_transition_minutes": 0,
    }
    result = submit_options_flow(
        api, flow_id, "manage_night", night_values
    )
    if result.get("step_id") == "manage_night":
        result = submit_options_flow(
            api, flow_id, "manage_night", night_values
        )
    save_options_from_room_hub(api, flow_id, result)
    reload_entry(api, entry_id)

    room_state = entry_room_state(api, entry_id)
    configuration = room_state.get("attributes", {}).get("configuration", {})
    if not configuration.get("night_enabled"):
        raise AssertionError(
            f"Night enable was not persisted for an existing room: {configuration}"
        )
    if configuration.get("night_source") != "sun":
        raise AssertionError(
            f"Night source was not persisted for an existing room: {configuration}"
        )

    below_horizon = dict(scenario["initial"]["sun.sun"])
    below_horizon["state"] = "below_horizon"
    set_fixture_state(api, "sun.sun", below_horizon)
    room_state = evaluate_entry(api, entry_id)
    if room_state.get("state") != "night" or not room_state.get(
        "attributes", {}
    ).get("night_active"):
        raise AssertionError(
            f"Persisted Night configuration did not run after reload: {room_state}"
        )
    set_fixture_state(api, "sun.sun", scenario["initial"]["sun.sun"])
    LIVE_WIZARD_TRANSITIONS.add(
        "existing_room.night_enabled.off_to_on.configure.save_reload.runtime"
    )


def assert_existing_room_schedule_transition(
    api: HomeAssistantApi, entry_id: str
) -> None:
    """Persist both states of the dedicated Schedule feature."""
    configuration = entry_room_state(api, entry_id).get(
        "attributes", {}
    ).get("configuration", {})
    flow_id, feature_form = replay_options_path(
        api, entry_id, "choose_advanced_features"
    )
    result = submit_options_flow(
        api,
        flow_id,
        "choose_advanced_features",
        advanced_feature_payload(
            configuration,
            remove=("schedule",),
            visible_fields=_schema_fields(
                feature_form.get("data_schema", [])
            ),
        ),
    )
    expect_step(result, "advanced_features_hub")
    result = submit_options_flow(
        api,
        flow_id,
        "advanced_features_hub",
        {"next_step_id": "back_to_room"},
    )
    save_options_from_room_hub(api, flow_id, result)
    reload_entry(api, entry_id)
    configuration = entry_room_state(api, entry_id).get("attributes", {}).get(
        "configuration", {}
    )
    if configuration.get("schedule_enabled") is not False:
        raise AssertionError(
            "Schedule disable was not persisted for an existing room: "
            f"{configuration}"
        )

    explore_options_surfaces(api, entry_id)
    configuration = entry_room_state(api, entry_id).get(
        "attributes", {}
    ).get("configuration", {})
    flow_id, feature_form = replay_options_path(
        api, entry_id, "choose_advanced_features"
    )
    result = submit_options_flow(
        api,
        flow_id,
        "choose_advanced_features",
        advanced_feature_payload(
            configuration,
            add=("schedule",),
            visible_fields=_schema_fields(
                feature_form.get("data_schema", [])
            ),
        ),
    )
    expect_step(result, "manage_automation")
    schedule_values = {
        "schedule_profile": "custom",
        "day_window": "fixed_time",
        "active_months": [str(value) for value in range(1, 13)],
        "active_weekdays": [str(value) for value in range(7)],
        "start_time": "06:00:00",
        "end_time": "22:00:00",
        "outside_schedule_behavior": "open",
    }
    result = submit_options_flow(
        api,
        flow_id,
        "manage_automation",
        {"schedule_settings": schedule_values},
    )
    if result.get("step_id") == "manage_automation":
        result = submit_options_flow(
            api,
            flow_id,
            "manage_automation",
            {"schedule_settings": schedule_values},
        )
    save_options_from_room_hub(api, flow_id, result)
    reload_entry(api, entry_id)
    configuration = entry_room_state(api, entry_id).get("attributes", {}).get(
        "configuration", {}
    )
    if not configuration.get("schedule_enabled"):
        raise AssertionError(
            "Schedule enable was not persisted for an existing room: "
            f"{configuration}"
        )
    LIVE_WIZARD_TRANSITIONS.add(
        "existing_room.schedule_enabled.on_to_off_to_on.save_reload"
    )


def assert_existing_cover_limit_transition(
    api: HomeAssistantApi, entry_id: str
) -> None:
    """Persist both states of the optional maximum-opening cover limit."""

    def current_cover() -> dict[str, Any]:
        configuration = entry_room_state(api, entry_id).get(
            "attributes", {}
        ).get("configuration", {})
        covers = [
            cover
            for sector in configuration.get("sectors", [])
            for layer in sector.get("layers", [])
            for cover in layer.get("covers", [])
        ]
        if len(covers) != 1:
            raise AssertionError(
                f"Expected one cover during limit transition, got {covers}"
            )
        return covers[0]

    flow_id, _ = replay_options_path(
        api, entry_id, "manage_cover_special"
    )
    result = submit_options_flow(
        api,
        flow_id,
        "manage_cover_special",
        {"enforce_max_open_position": False},
    )
    expect_step(result, "maximum_opening_hub")
    result = submit_options_flow(
        api,
        flow_id,
        "maximum_opening_hub",
        {"next_step_id": "back_to_room"},
    )
    save_options_from_room_hub(api, flow_id, result)
    reload_entry(api, entry_id)
    if current_cover().get("enforce_max_open_position") is not False:
        raise AssertionError(
            f"Maximum-opening disable was not persisted: {current_cover()}"
        )

    explore_options_surfaces(api, entry_id)
    flow_id, _ = replay_options_path(
        api, entry_id, "manage_cover_special"
    )
    result = submit_options_flow(
        api,
        flow_id,
        "manage_cover_special",
        {"enforce_max_open_position": True, "max_open_position": 85},
    )
    expect_step(result, "maximum_opening_hub")
    result = submit_options_flow(
        api,
        flow_id,
        "maximum_opening_hub",
        {"next_step_id": "back_to_room"},
    )
    save_options_from_room_hub(api, flow_id, result)
    reload_entry(api, entry_id)
    cover = current_cover()
    if not cover.get("enforce_max_open_position") or float(
        cover.get("max_open_position", -1)
    ) != 85:
        raise AssertionError(
            f"Maximum-opening enable was not persisted: {cover}"
        )
    LIVE_WIZARD_TRANSITIONS.add(
        "existing_cover.enforce_max_open_position.on_to_off_to_on.save_reload"
    )


def add_advanced_group_through_options(
    api: HomeAssistantApi,
    entry_id: str,
    *,
    profile: str,
    cover_entity: str,
    name: str,
) -> None:
    """Add one physical profile through the real hierarchical options flow."""
    flow_id, _result = replay_options_path(api, entry_id, "add_layer_flat")
    result = submit_options_flow(
        api,
        flow_id,
        "add_layer_flat",
        {"name": name, "profile": profile},
    )
    expect_step(result, "manage_layer_profile")
    result = submit_options_flow(
        api,
        flow_id,
        "manage_layer_profile",
        _profile_form_payload(profile),
    )
    expect_step(result, "add_group_covers")
    result = submit_options_flow(
        api,
        flow_id,
        "add_group_covers",
        {"cover_entities": [cover_entity]},
    )
    expect_step(result, "compact_cover_details")
    cover_short = {
        "vertical_blind": "V1",
        "exterior_screen": "S1",
        "curtain": "T1",
    }.get(profile, "C1")
    result = submit_options_flow(
        api,
        flow_id,
        "compact_cover_details",
        {
            "name": name,
            "short": cover_short,
            "window_safe_state": "on",
            "window_policy": "block_closing",
            "window_returns_to_automation": True,
            "invert_position": False,
            **({"invert_tilt": False} if profile in {
                "venetian", "vertical_blind"
            } else {}),
        },
    )
    if result.get("step_id") == "new_optional_feature_available":
        LIVE_WIZARD_TRANSITIONS.add(
            "existing_room.new_cover_profile.optional_feature_discovery"
        )
        result = submit_options_flow(
            api,
            flow_id,
            "new_optional_feature_available",
            {"open_optional_features": False},
        )
    save_options_from_group_hub(api, flow_id, result)
    wait_for_entry_loaded(api, entry_id)
    explore_options_surfaces(api, entry_id)


def assert_calculated_glare_zone_flow(
    api: HomeAssistantApi, entry_id: str
) -> None:
    """Create and edit one exact-cover glare zone through real HA forms."""
    configuration = entry_room_state(api, entry_id).get(
        "attributes", {}
    ).get("configuration", {})
    flow_id, feature_form = replay_options_path(
        api, entry_id, "choose_advanced_features"
    )
    result = submit_options_flow(
        api,
        flow_id,
        "choose_advanced_features",
        advanced_feature_payload(
            configuration,
            add=("glare_protection",),
            visible_fields=_schema_fields(
                feature_form.get("data_schema", [])
            ),
        ),
    )
    if result.get("step_id") == "glare_protection_hub":
        sector_choice = next(
            option
            for option in _menu_options(result)
            if option != "back_to_room"
        )
        result = submit_options_flow(
            api,
            flow_id,
            "glare_protection_hub",
            {"next_step_id": sector_choice},
        )
        expect_step(result, "protected_zones_hub")
        add_choice = next(
            option
            for option in _menu_options(result)
            if option != "back_to_sector"
        )
        result = submit_options_flow(
            api,
            flow_id,
            "protected_zones_hub",
            {"next_step_id": add_choice},
        )
    expect_step(result, "add_protected_zone")
    fields = _schema_fields(result.get("data_schema", []))
    for required in (
        "cover_entity",
        "window_width_m",
        "window_height_m",
        "window_sill_height_m",
        "object_distance_m",
        "object_center_height_m",
        "object_height_m",
        "object_lateral_center_m",
        "object_width_m",
        "sun_confirmation_enabled",
        "minimum_sun_elevation_degrees",
        "condition_activation_delay_seconds",
        "condition_release_delay_seconds",
        "local_sun_sensor",
        "local_sun_preset",
        "local_sun_on_threshold",
        "local_sun_off_threshold",
        "weather_fallback_entity",
    ):
        if required not in fields:
            raise AssertionError(
                f"Glare form is missing {required}: {sorted(fields)}"
            )
    for removed in ("group_ids", "calculated", "target_position"):
        if removed in fields:
            raise AssertionError(
                f"Glare form still exposes obsolete {removed}: "
                f"{sorted(fields)}"
            )
    zone_payload = {
        "protected_zone_identity": {
            "name": "Dining table",
            "cover_entity": "cover.advanced_curtain",
            "curtain_movement": "symmetric",
        },
        "protected_zone_window": {
            "window_width_m": 2.4,
            "window_height_m": 2.1,
            "window_sill_height_m": 0.2,
        },
        "protected_zone_object": {
            "object_distance_m": 1.8,
            "object_center_height_m": 0.8,
            "object_height_m": 0.8,
            "object_lateral_center_m": 0.3,
            "object_width_m": 1.2,
        },
        "protected_zone_activation": {
            "sun_confirmation_enabled": False,
            "minimum_sun_elevation_degrees": 2.5,
            "condition_activation_delay_seconds": 60,
            "condition_release_delay_seconds": 300,
        },
        "protected_zone_sun_evidence": {
            "local_sun_sensor": "sensor.advanced_lux",
            "local_sun_preset": "sensitive",
            "local_sun_on_threshold": 5000,
            "local_sun_off_threshold": 3000,
        },
    }
    result = submit_options_flow(
        api, flow_id, "add_protected_zone", zone_payload
    )
    expect_step(result, "confirm_protected_zone")
    result = submit_options_flow(
        api,
        flow_id,
        "confirm_protected_zone",
        {"confirm_protected_zone": True},
    )
    if result.get("step_id") == "room_hub":
        save_options_from_room_hub(api, flow_id, result)
        reload_entry(api, entry_id)
        flow_id, result = replay_advanced_feature(
            api,
            entry_id,
            "glare_protection_hub",
            "glare_protection_hub",
        )
        sector_choice = next(
            option
            for option in _menu_options(result)
            if option != "back_to_room"
        )
        result = submit_options_flow(
            api,
            flow_id,
            "glare_protection_hub",
            {"next_step_id": sector_choice},
        )
    expect_step(result, "protected_zones_hub")
    zone_choice = next(
        option
        for option, label in result.get("menu_options", {}).items()
        if option != "back_to_sector"
        and not str(label).lstrip().startswith("+")
    )
    result = submit_options_flow(
        api,
        flow_id,
        "protected_zones_hub",
        {"next_step_id": zone_choice},
    )
    expect_step(result, "manage_protected_zone")
    edit_payload = deepcopy(zone_payload)
    edit_payload["protected_zone_identity"]["enabled"] = True
    edit_payload["protected_zone_maintenance"] = {
        "delete_protected_zone": False
    }
    result = submit_options_flow(
        api, flow_id, "manage_protected_zone", edit_payload
    )
    expect_step(result, "confirm_protected_zone")
    result = submit_options_flow(
        api,
        flow_id,
        "confirm_protected_zone",
        {"confirm_protected_zone": True},
    )
    expect_step(result, "protected_zones_hub")
    for step_id, choice, expected in (
        ("protected_zones_hub", "back_to_sector", "sector_hub"),
        ("sector_hub", "back_to_structure", "structure_hub"),
        ("structure_hub", "back_to_room", "room_hub"),
    ):
        result = submit_options_flow(
            api, flow_id, step_id, {"next_step_id": choice}
        )
        expect_step(result, expected)
    save_options_from_room_hub(api, flow_id, result)
    reload_entry(api, entry_id)

    configuration = entry_room_state(api, entry_id).get(
        "attributes", {}
    ).get("configuration", {})
    zones = configuration["sectors"][0].get("protected_zones", [])
    zone = next(
        item for item in zones if item.get("name") == "Dining table"
    )
    if zone.get("cover_entity") != "cover.advanced_curtain":
        raise AssertionError(f"Glare zone lost exact cover scope: {zone}")
    if zone.get("calculation_mode") != "curtain":
        raise AssertionError(f"Glare zone has wrong calculation mode: {zone}")
    if zone.get("condition_activation_delay_seconds") != 60.0:
        raise AssertionError(f"Glare activation delay was not persisted: {zone}")
    if zone.get("condition_release_delay_seconds") != 300.0:
        raise AssertionError(f"Glare release delay was not persisted: {zone}")
    if zone.get("local_sun_sensor") != "sensor.advanced_lux":
        raise AssertionError(f"Glare local sun sensors were not persisted: {zone}")
    if zone.get("local_sun_preset") != "sensitive":
        raise AssertionError(f"Glare local sun preset was not persisted: {zone}")
    if "group_ids" in zone or "calculated" in zone:
        raise AssertionError(f"Glare zone persisted obsolete switches: {zone}")
    LIVE_WIZARD_TRANSITIONS.add(
        "existing_room.glare_zone.single_cover.create_edit.save_reload"
    )


def add_advanced_sector_through_options(
    api: HomeAssistantApi, scenario: dict[str, Any], entry_id: str
) -> None:
    """Add a second sector so chooser and cross-sector paths are real."""
    flow_id, _result = replay_options_path(api, entry_id, "add_sector_flat")
    result = submit_options_flow(
        api,
        flow_id,
        "add_sector_flat",
        {
            "name": "West External",
            "short": "W",
            "direction": "west",
            "sun_source": "external",
        },
    )
    expect_step(result, "configure_sector_source")
    result = submit_options_flow(
        api,
        flow_id,
        "configure_sector_source",
        {
            "sun_presence_entity": scenario["setup"][
                "sun_confirmation_entity"
            ]
        },
    )
    expect_step(result, "add_sector_group")
    result = submit_options_flow(
        api,
        flow_id,
        "add_sector_group",
        {"name": "Awning", "profile": "awning"},
    )
    expect_step(result, "manage_layer_profile")
    result = submit_options_flow(
        api,
        flow_id,
        "manage_layer_profile",
        _profile_form_payload("awning"),
    )
    expect_step(result, "add_sector_covers")
    result = submit_options_flow(
        api,
        flow_id,
        "add_sector_covers",
        {"cover_entities": ["cover.advanced_awning"]},
    )
    expect_step(result, "compact_cover_details")
    result = submit_options_flow(
        api,
        flow_id,
        "compact_cover_details",
        {
            "name": "Advanced Awning",
            "short": "AW",
            "window_safe_state": "on",
            "window_policy": "block_closing",
            "window_returns_to_automation": True,
            "invert_position": False,
        },
    )
    expect_step(result, "sector_hub")
    result = submit_options_flow(
        api, flow_id, "sector_hub", {"next_step_id": "back_to_structure"}
    )
    expect_step(result, "structure_hub")
    result = submit_options_flow(
        api, flow_id, "structure_hub", {"next_step_id": "back_to_room"}
    )
    expect_step(result, "room_hub")
    result = submit_options_flow(
        api, flow_id, "room_hub", {"next_step_id": "back_to_overview"}
    )
    expect_step(result, "init")
    result = submit_options_flow(
        api, flow_id, "init", {"next_step_id": "finish"}
    )
    if result.get("type") != "create_entry":
        raise AssertionError(f"Options flow did not save sector changes: {result}")
    wait_for_entry_loaded(api, entry_id)


def _cancel_options_flow(api: HomeAssistantApi, flow_id: str) -> None:
    try:
        api.delete(f"/api/config/config_entries/options/flow/{flow_id}")
    except ApiError as exc:
        if exc.status not in {404, 405}:
            raise


def submit_options_expect_error(
    api: HomeAssistantApi,
    flow_id: str,
    step_id: str,
    data: dict[str, Any],
    expected_error: str,
    *,
    expected_schema_field: str | None = None,
) -> dict[str, Any]:
    """Require a customer-facing validation error from a real HA form."""
    try:
        result = api.post(
            f"/api/config/config_entries/options/flow/{flow_id}", data
        )
    except ApiError as exc:
        if (
            exc.status == 400
            and expected_schema_field is not None
            and expected_schema_field in exc.body
        ):
            return {
                "type": "schema_error",
                "errors": {expected_schema_field: exc.body},
            }
        raise
    expect_step(result, step_id)
    errors = set((result.get("errors") or {}).values())
    if expected_error not in errors:
        raise AssertionError(
            f"Expected {expected_error!r} at {step_id}, got {result}"
        )
    return result


def probe_invalid_wizard_inputs(
    api: HomeAssistantApi, easy_entry_id: str, advanced_entry_id: str
) -> dict[str, str]:
    """Prove that contradictory setup data is rejected by the real wizard."""
    evidence: dict[str, str] = {}

    flow_id, _ = replay_options_path(api, easy_entry_id, "add_sector_flat")
    try:
        submit_options_expect_error(
            api,
            flow_id,
            "add_sector_flat",
            {
                "name": "Invalid custom Easy sector",
                "short": "X",
                "direction": "custom",
                "sun_source": "geometry",
            },
            "option_not_available",
            expected_schema_field="direction",
        )
        evidence["easy_custom_geometry"] = "ha_schema_rejected"
    finally:
        _cancel_options_flow(api, flow_id)

    flow_id, _ = replay_options_path(
        api, advanced_entry_id, "add_sector_flat"
    )
    try:
        result = submit_options_flow(
            api,
            flow_id,
            "add_sector_flat",
            {
                "name": "Invalid Lux sector",
                "short": "LX",
                "direction": "south",
                "sun_source": "lux",
            },
        )
        expect_step(result, "configure_sector_source")
        result = submit_options_flow(
            api,
            flow_id,
            "configure_sector_source",
            {
                "lux_sensor": "sensor.advanced_lux",
                "sun_preset": "custom",
            },
        )
        expect_step(result, "configure_lux_profile")
        submit_options_expect_error(
            api,
            flow_id,
            "configure_lux_profile",
            {
                "sun_on_lux": 50,
                "sun_off_lux": 100,
                "sun_on_delay": 0,
                "sun_off_delay": 0,
            },
            "lux_hysteresis",
        )
        evidence["inverted_lux_hysteresis"] = "lux_hysteresis"
    finally:
        _cancel_options_flow(api, flow_id)

    flow_id, _ = replay_options_path(
        api, advanced_entry_id, "add_layer_flat"
    )
    try:
        result = submit_options_flow(
            api,
            flow_id,
            "add_layer_flat",
            {"name": "Invalid duplicate", "profile": "binary_cover"},
        )
        expect_step(result, "add_group_covers")
        submit_options_expect_error(
            api,
            flow_id,
            "add_group_covers",
            {"cover_entities": ["cover.easy_venetian"]},
            "cover_already_assigned",
        )
        evidence["duplicate_cover"] = "cover_already_assigned"
    finally:
        _cancel_options_flow(api, flow_id)

    return evidence


def probe_choice_matrix(
    api: HomeAssistantApi, easy_entry_id: str, advanced_entry_id: str
) -> dict[str, Any]:
    """Submit every major dropdown choice in a disposable real HA flow."""
    evidence: dict[str, Any] = {
        "setup_types": ["simple", "complete"],
        "easy_directions": [],
        "advanced_directions": [],
        "easy_sun_sources": [],
        "advanced_sun_sources": [],
        "easy_sun_presets": [],
        "advanced_sun_presets": [],
        "easy_profiles": [],
        "advanced_profiles": [],
        "tilt_presets": [],
        "diagnostic_levels": [],
        "schedule_profiles": [],
        "day_windows": [],
        "outside_schedule_behaviors": [],
        "pause_modes": [],
        "night_sources": [],
        "safety_behaviors": [],
        "weather_logic": [],
        "window_safe_states": [],
        "window_policies": [],
    }
    directions = [
        "north", "northeast", "east", "southeast", "south",
        "southwest", "west", "northwest",
    ]
    for entry_id, allowed, key in (
        (easy_entry_id, directions, "easy_directions"),
        (advanced_entry_id, [*directions, "custom"], "advanced_directions"),
    ):
        for direction in allowed:
            flow_id, _ = replay_options_path(api, entry_id, "add_sector_flat")
            try:
                result = submit_options_flow(
                    api,
                    flow_id,
                    "add_sector_flat",
                    {
                        "name": f"Probe {direction}",
                        "short": "P",
                        "direction": direction,
                        "sun_source": "geometry",
                    },
                )
                expected = (
                    "manage_sector_geometry"
                    if direction == "custom"
                    else "add_sector_group"
                )
                expect_step(result, expected)
                evidence[key].append(direction)
            finally:
                _cancel_options_flow(api, flow_id)

    for entry_id, key in (
        (easy_entry_id, "easy_sun_sources"),
        (advanced_entry_id, "advanced_sun_sources"),
    ):
        for source in ("geometry", "lux", "external"):
            flow_id, _ = replay_options_path(api, entry_id, "add_sector_flat")
            try:
                result = submit_options_flow(
                    api,
                    flow_id,
                    "add_sector_flat",
                    {
                        "name": f"Probe {source}",
                        "short": "P",
                        "direction": "south",
                        "sun_source": source,
                    },
                )
                expect_step(
                    result,
                    "add_sector_group"
                    if source == "geometry"
                    else "configure_sector_source",
                )
                evidence[key].append(source)
            finally:
                _cancel_options_flow(api, flow_id)

    for entry_id, presets, key in (
        (easy_entry_id, ("low", "medium", "high"), "easy_sun_presets"),
        (
            advanced_entry_id,
            ("low", "medium", "high", "custom"),
            "advanced_sun_presets",
        ),
    ):
        for preset in presets:
            flow_id, _ = replay_options_path(api, entry_id, "add_sector_flat")
            try:
                result = submit_options_flow(
                    api,
                    flow_id,
                    "add_sector_flat",
                    {
                        "name": f"Probe Lux {preset}",
                        "short": "L",
                        "direction": "south",
                        "sun_source": "lux",
                    },
                )
                expect_step(result, "configure_sector_source")
                result = submit_options_flow(
                    api,
                    flow_id,
                    "configure_sector_source",
                    {
                        "lux_sensor": "sensor.advanced_lux",
                        "sun_preset": preset,
                    },
                )
                expect_step(
                    result,
                    "configure_lux_profile"
                    if preset == "custom"
                    else "add_sector_group",
                )
                evidence[key].append(preset)
            finally:
                _cancel_options_flow(api, flow_id)

    profiles = (
        "venetian", "roller_shutter", "exterior_screen", "curtain",
        "vertical_blind", "awning", "binary_cover",
    )
    for entry_id, key, advanced in (
        (easy_entry_id, "easy_profiles", False),
        (advanced_entry_id, "advanced_profiles", True),
    ):
        for profile in profiles:
            flow_id, _ = replay_options_path(api, entry_id, "add_layer_flat")
            try:
                result = submit_options_flow(
                    api,
                    flow_id,
                    "add_layer_flat",
                    {"name": f"Probe {profile}", "profile": profile},
                )
                expect_step(
                    result,
                    "manage_layer_profile"
                    if advanced and profile != "binary_cover"
                    else "add_group_covers",
                )
                evidence[key].append(profile)
            finally:
                _cancel_options_flow(api, flow_id)

    for preset in ("glare", "balanced", "daylight", "custom"):
        flow_id, _ = replay_options_path(
            api, advanced_entry_id, "add_layer_flat"
        )
        try:
            result = submit_options_flow(
                api,
                flow_id,
                "add_layer_flat",
                {"name": f"Probe tilt {preset}", "profile": "venetian"},
            )
            expect_step(result, "manage_layer_profile")
            payload = _profile_form_payload("venetian")
            payload["profile_behavior"]["tilt_preset"] = preset
            result = submit_options_flow(
                api, flow_id, "manage_layer_profile", payload
            )
            if preset == "custom":
                expect_step(result, "manage_layer_profile")
                payload["slat_curve"] = {
                    "elevation_1": 10,
                    "tilt_1": 90,
                    "elevation_2": 20,
                    "tilt_2": 65,
                    "elevation_3": 40,
                    "tilt_3": 35,
                    "elevation_4": 60,
                    "tilt_4": 15,
                }
                result = submit_options_flow(
                    api, flow_id, "manage_layer_profile", payload
                )
            expect_step(result, "add_group_covers")
            evidence["tilt_presets"].append(preset)
        finally:
            _cancel_options_flow(api, flow_id)

    for level in ("off", "events", "full"):
        flow_id, _ = replay_options_path(
            api, advanced_entry_id, "diagnostics_settings"
        )
        try:
            result = submit_options_flow(
                api,
                flow_id,
                "diagnostics_settings",
                {"diagnostic_level": level},
            )
            expect_step(result, "init")
            evidence["diagnostic_levels"].append(level)
        finally:
            _cancel_options_flow(api, flow_id)

    for profile in ("year_round", "summer", "custom"):
        flow_id, _ = replay_advanced_feature(
            api,
            advanced_entry_id,
            "manage_schedule",
            "manage_automation",
        )
        try:
            initial_schedule = {
                "schedule_profile": profile,
                "day_window": "all_day",
                "active_months": ["1"],
                "active_weekdays": ["0"],
                "start_time": "06:00:00",
                "end_time": "22:00:00",
                "outside_schedule_behavior": "open",
            }
            result = submit_options_flow(
                api,
                flow_id,
                "manage_automation",
                {"schedule_settings": initial_schedule},
            )
            expect_step(result, "room_hub")
            evidence["schedule_profiles"].append(profile)
            if "all_day" not in evidence["day_windows"]:
                evidence["day_windows"].append("all_day")
            if profile != "year_round" and "open" not in evidence[
                "outside_schedule_behaviors"
            ]:
                evidence["outside_schedule_behaviors"].append("open")
        finally:
            _cancel_options_flow(api, flow_id)

    flow_id, _ = replay_advanced_feature(
        api,
        advanced_entry_id,
        "manage_schedule",
        "manage_automation",
    )
    try:
        fixed_schedule = {
            "schedule_profile": "custom",
            "day_window": "fixed_time",
            "active_months": ["1"],
            "active_weekdays": ["0"],
            "start_time": "06:00:00",
            "end_time": "22:00:00",
            "outside_schedule_behavior": "hold",
        }
        result = submit_options_flow(
            api,
            flow_id,
            "manage_automation",
            {"schedule_settings": fixed_schedule},
        )
        if result.get("step_id") == "manage_automation":
            result = submit_options_flow(
                api,
                flow_id,
                "manage_automation",
                {"schedule_settings": fixed_schedule},
            )
        expect_step(result, "room_hub")
        evidence["day_windows"].append("fixed_time")
        evidence["outside_schedule_behaviors"].append("hold")
    finally:
        _cancel_options_flow(api, flow_id)

    for mode in (
        "next_sunrise", "next_sunset", "next_night_end", "timed", "manual"
    ):
        flow_id, _ = replay_options_path(api, advanced_entry_id, "manage_pause")
        try:
            result = submit_options_flow(
                api,
                flow_id,
                "manage_pause",
                {
                    "default_pause_mode": mode,
                    "pause_sun_offset_minutes": -60,
                    "pause_duration_hours": 2,
                    "external_movement_detection": True,
                    "heat_during_pause": True,
                },
            )
            if result.get("errors"):
                raise AssertionError(result)
            evidence["pause_modes"].append(mode)
        finally:
            _cancel_options_flow(api, flow_id)

    for source in ("sun", "entity"):
        flow_id, _ = replay_advanced_feature(
            api, advanced_entry_id, "manage_night", "manage_night"
        )
        try:
            result = submit_options_flow(
                api,
                flow_id,
                "manage_night",
                {
                    "night_source": source,
                    "night_start_offset_minutes": 0,
                    "night_end_offset_minutes": 0,
                    "night_morning_transition_minutes": 0,
                    "night_evening_transition_minutes": 0,
                },
            )
            if source == "entity":
                expect_step(result, "manage_night")
                result = submit_options_flow(
                    api,
                    flow_id,
                    "manage_night",
                    {
                        "night_source": "entity",
                        "night_entity": "input_boolean.fixture_night_mode",
                        "night_morning_transition_minutes": 0,
                        "night_evening_transition_minutes": 0,
                    },
                )
            if result.get("errors"):
                raise AssertionError(result)
            evidence["night_sources"].append(source)
        finally:
            _cancel_options_flow(api, flow_id)

    weather_sources = {
        "irradiance_sensor": "sensor.irradiance",
        "irradiance_minimum": 150,
        "cloud_cover_sensor": "sensor.cloud_cover",
        "cloud_cover_maximum": 85,
        "weather_permission": "binary_sensor.weather_permission",
        "occupancy_sensor": "binary_sensor.occupancy",
        "weather_logic": "all",
        "comfort_requires_occupancy": False,
        "heat_ignores_weather": True,
        "heat_requires_sun": True,
    }
    for behavior, weather_logic in (
        ("move_safe", "all"),
        ("block", "any"),
    ):
        flow_id, _ = replay_advanced_feature(
            api,
            advanced_entry_id,
            "manage_safety",
            "manage_conditions",
        )
        try:
            result = submit_options_flow(
                api,
                flow_id,
                "manage_conditions",
                {
                    "safety_blockers": ["binary_sensor.safety_alarm"],
                    "safety_behavior": behavior,
                },
            )
            expect_step(result, "room_hub")
            evidence["safety_behaviors"].append(behavior)
        finally:
            _cancel_options_flow(api, flow_id)
        flow_id, _ = replay_advanced_feature(
            api,
            advanced_entry_id,
            "manage_weather_conditions",
            "manage_conditions",
        )
        try:
            result = submit_options_flow(
                api,
                flow_id,
                "manage_conditions",
                {**weather_sources, "weather_logic": weather_logic},
            )
            expect_step(result, "room_hub")
            evidence["weather_logic"].append(weather_logic)
        finally:
            _cancel_options_flow(api, flow_id)

    for safe_state in ("on", "off"):
        for policy in ("block_all", "block_closing", "ignore"):
            flow_id, _ = replay_options_path(
                api, advanced_entry_id, "add_layer_flat"
            )
            try:
                result = submit_options_flow(
                    api,
                    flow_id,
                    "add_layer_flat",
                    {
                        "name": f"Probe {safe_state} {policy}",
                        "profile": "roller_shutter",
                    },
                )
                expect_step(result, "manage_layer_profile")
                result = submit_options_flow(
                    api,
                    flow_id,
                    "manage_layer_profile",
                    _profile_form_payload("roller_shutter"),
                )
                expect_step(result, "add_group_covers")
                result = submit_options_flow(
                    api,
                    flow_id,
                    "add_group_covers",
                    {"cover_entities": ["cover.flow_probe_cover"]},
                )
                expect_step(result, "compact_cover_details")
                result = submit_options_flow(
                    api,
                    flow_id,
                    "compact_cover_details",
                    {
                        "name": "Flow Probe Cover",
                        "short": "FP",
                        "window": "binary_sensor.window_contact",
                        "window_safe_state": safe_state,
                        "window_policy": policy,
                        "window_returns_to_automation": (
                            safe_state == "on"
                        ),
                        "invert_position": policy == "ignore",
                    },
                )
                expect_step(result, "group_hub")
                if safe_state not in evidence["window_safe_states"]:
                    evidence["window_safe_states"].append(safe_state)
                if policy not in evidence["window_policies"]:
                    evidence["window_policies"].append(policy)
            finally:
                _cancel_options_flow(api, flow_id)
    assert_choice_contract(evidence)
    return evidence


def assert_choice_contract(evidence: dict[str, Any]) -> None:
    """Keep the executable matrix identical to its declared option contract."""
    contract_path = (
        Path(__file__).parents[2]
        / "e2e"
        / "ha"
        / "scenarios"
        / "wizard_coverage.json"
    )
    choices = json.loads(contract_path.read_text(encoding="utf-8"))[
        "choice_contract"
    ]
    direct = {
        "setup_type": "setup_types",
        "direction_easy": "easy_directions",
        "direction_advanced": "advanced_directions",
        "sun_preset_easy": "easy_sun_presets",
        "sun_preset_advanced": "advanced_sun_presets",
        "tilt_preset": "tilt_presets",
        "diagnostic_level": "diagnostic_levels",
        "schedule_profile": "schedule_profiles",
        "day_window": "day_windows",
        "outside_schedule_behavior": "outside_schedule_behaviors",
        "night_source": "night_sources",
        "safety_behavior": "safety_behaviors",
        "weather_logic": "weather_logic",
        "window_safe_state": "window_safe_states",
        "window_policy": "window_policies",
    }
    for contract_key, evidence_key in direct.items():
        if set(choices[contract_key]) != set(evidence[evidence_key]):
            raise AssertionError(
                f"Choice coverage mismatch for {contract_key}: "
                f"expected={choices[contract_key]}, observed={evidence[evidence_key]}"
            )
    for contract_key, evidence_keys in {
        "sun_source": ("easy_sun_sources", "advanced_sun_sources"),
        "profile": ("easy_profiles", "advanced_profiles"),
    }.items():
        expected = set(choices[contract_key])
        for evidence_key in evidence_keys:
            if expected != set(evidence[evidence_key]):
                raise AssertionError(
                    f"Choice coverage mismatch for {contract_key}/{evidence_key}: "
                    f"expected={sorted(expected)}, observed={evidence[evidence_key]}"
                )


def assert_live_wizard_coverage(output_dir: Path) -> None:
    """Fail when mandatory real-HA surfaces or state changes were not observed."""
    contract_path = (
        Path(__file__).parents[2]
        / "e2e"
        / "ha"
        / "scenarios"
        / "wizard_coverage.json"
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    required = set(contract["live_required"])
    required_transitions = set(contract["live_transitions"])
    observed = set(LIVE_WIZARD_COVERAGE)
    missing = sorted(required - observed)
    missing_transitions = sorted(
        required_transitions - LIVE_WIZARD_TRANSITIONS
    )
    duplicate_setting_owners = (
        duplicate_wizard_setting_owners(
            INITIAL_ADVANCED_WIZARD_COVERAGE
        )
        if contract.get("unique_setting_ownership", False)
        else {}
    )
    missing_initial_capture = (
        bool(contract.get("unique_setting_ownership", False))
        and not INITIAL_ADVANCED_WIZARD_COVERAGE
    )
    report = {
        "required": sorted(required),
        "observed": {
            step: sorted(fields)
            for step, fields in sorted(LIVE_WIZARD_COVERAGE.items())
        },
        "missing": missing,
        "required_transitions": sorted(required_transitions),
        "observed_transitions": sorted(LIVE_WIZARD_TRANSITIONS),
        "missing_transitions": missing_transitions,
        "initial_advanced_setting_owners": {
            page: sorted(fields)
            for page, fields in sorted(
                INITIAL_ADVANCED_WIZARD_COVERAGE.items()
            )
        },
        "duplicate_initial_setting_owners": duplicate_setting_owners,
        "missing_initial_setting_capture": missing_initial_capture,
    }
    (output_dir / "wizard-coverage-live.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    if (
        missing
        or missing_transitions
        or duplicate_setting_owners
        or missing_initial_capture
    ):
        raise AssertionError(
            "Mandatory wizard coverage was not exercised in real HA: "
            f"surfaces={missing}, transitions={missing_transitions}, "
            f"duplicate_settings={duplicate_setting_owners}, "
            f"missing_initial_capture={missing_initial_capture}"
        )


def smart_shading_entries(api: HomeAssistantApi) -> list[dict[str, Any]]:
    entries = api.get("/api/config/config_entries/entry")
    return [item for item in entries if item.get("domain") == "smart_shading"]


def wait_for_entry_loaded(
    api: HomeAssistantApi, entry_id: str, timeout: int = 60
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        for entry in smart_shading_entries(api):
            if str(entry.get("entry_id")) == entry_id:
                last = entry
                if entry.get("state") == "loaded":
                    return entry
        time.sleep(1)
    raise AssertionError(f"Config entry {entry_id} did not load; last state: {last}")


def wait_for_smart_shading_entities(
    api: HomeAssistantApi, entry_id: str, timeout: int = 60
) -> list[str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        states = api.get("/api/states")
        entity_ids = sorted(
            item["entity_id"]
            for item in states
            if str(
                item.get("attributes", {}).get("smart_shading_entry_id", "")
            )
            == entry_id
        )
        if entity_ids:
            return entity_ids
        time.sleep(1)
    raise AssertionError(f"Smart Shading entities did not load for entry {entry_id}")


def assert_entry_variant(api: HomeAssistantApi, entry_id: str, advanced: bool) -> None:
    states = api.get("/api/states")
    matching = [
        item
        for item in states
        if str(item.get("attributes", {}).get("smart_shading_entry_id", ""))
        == entry_id
    ]
    if not matching:
        raise AssertionError(f"No entities found for config entry {entry_id}")
    expected_layout = "detailed" if advanced else "compact"
    unexpected = [
        item["entity_id"]
        for item in matching
        if item.get("attributes", {}).get("smart_shading_layout")
        != expected_layout
    ]
    if unexpected:
        raise AssertionError(
            f"Expected {expected_layout!r} layout for {entry_id}; "
            f"mismatching entities: {unexpected}"
        )


def wait_for_entry_removed(
    api: HomeAssistantApi, entry_id: str, timeout: int = 60
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        entries = smart_shading_entries(api)
        states = api.get("/api/states")
        entry_exists = any(str(item.get("entry_id")) == entry_id for item in entries)
        entities_exist = any(
            str(item.get("attributes", {}).get("smart_shading_entry_id", ""))
            == entry_id
            for item in states
        )
        if not entry_exists and not entities_exist:
            return
        time.sleep(1)
    raise AssertionError(f"Config entry {entry_id} or its entities were not removed")


def trigger_and_assert_cover_call(
    api: HomeAssistantApi, scenario: dict[str, Any], entry_id: str
) -> list[dict[str, Any]]:
    api.call_service("smart_shading_test_fixture", "reset_calls", {})
    # Refresh deterministic sun geometry immediately before evaluation so the
    # real Sun integration cannot make the scenario depend on wall-clock time.
    set_fixture_state(api, "sun.sun", scenario["initial"]["sun.sun"])
    action = scenario["action"]
    set_fixture_state(
        api,
        action["entity_id"],
        {"state": action["state"], "available": True},
    )
    reload_result = api.post(
        f"/api/config/config_entries/entry/{entry_id}/reload", {}
    )
    if reload_result.get("require_restart"):
        raise AssertionError(f"Config entry could not reload cleanly: {reload_result}")
    minimum = int(scenario["expect"]["minimum_cover_calls"])
    state = wait_for_state(
        api,
        "sensor.fixture_service_calls",
        lambda item: int(float(item["state"])) >= minimum,
    )
    calls = list(state.get("attributes", {}).get("calls", []))
    services = {call.get("service") for call in calls}
    missing = set(scenario["expect"]["cover_services"]) - services
    if missing:
        raise AssertionError(f"Missing expected cover services {sorted(missing)}: {calls}")
    return calls


def assert_unique_entities(api: HomeAssistantApi) -> list[str]:
    states = api.get("/api/states")
    entity_ids = [
        item["entity_id"]
        for item in states
        if item.get("attributes", {}).get("smart_shading_entry_id")
    ]
    if not entity_ids:
        raise AssertionError("No Smart Shading entities were registered")
    if len(entity_ids) != len(set(entity_ids)):
        raise AssertionError(f"Duplicate Smart Shading entity IDs: {entity_ids}")
    return sorted(entity_ids)


def entry_states(api: HomeAssistantApi, entry_id: str) -> list[dict[str, Any]]:
    return [
        item
        for item in api.get("/api/states")
        if str(item.get("attributes", {}).get("smart_shading_entry_id", ""))
        == entry_id
    ]


def entry_entity_for_control(
    api: HomeAssistantApi, entry_id: str, control_key: str
) -> str:
    matching = [
        item["entity_id"]
        for item in entry_states(api, entry_id)
        if item.get("attributes", {}).get("smart_shading_control_key") == control_key
    ]
    if len(matching) != 1:
        raise AssertionError(
            f"Expected one {control_key} control for {entry_id}, got {matching}"
        )
    return matching[0]


def entry_room_state(api: HomeAssistantApi, entry_id: str) -> dict[str, Any]:
    matching = [
        item
        for item in entry_states(api, entry_id)
        if item["entity_id"].startswith("sensor.")
        and item.get("attributes", {}).get("smart_shading_room_id")
        and "sector_statuses" in item.get("attributes", {})
    ]
    if len(matching) != 1:
        raise AssertionError(
            f"Expected one room status sensor for {entry_id}, got "
            f"{[item['entity_id'] for item in matching]}"
        )
    return matching[0]


def evaluate_entry(api: HomeAssistantApi, entry_id: str) -> dict[str, Any]:
    before = entry_room_state(api, entry_id).get("attributes", {}).get(
        "last_evaluation"
    )
    entity_id = entry_entity_for_control(api, entry_id, "evaluate")
    api.call_service("button", "press", {"entity_id": entity_id})
    return wait_for_state(
        api,
        entry_room_state(api, entry_id)["entity_id"],
        lambda item: item.get("attributes", {}).get("last_evaluation") != before,
    )


def reload_entry(api: HomeAssistantApi, entry_id: str) -> None:
    """Reload one entry and reject lifecycle paths requiring a HA restart."""
    result = api.post(
        f"/api/config/config_entries/entry/{entry_id}/reload", {}
    )
    if result.get("require_restart"):
        raise AssertionError(f"Config entry could not reload cleanly: {result}")
    wait_for_entry_loaded(api, entry_id)


def unload_and_reload_entry(api: HomeAssistantApi, entry_id: str) -> None:
    """Prove that disabling releases and re-enabling recreates HA platforms."""
    api.call_service(
        "smart_shading_test_fixture",
        "set_entry_enabled",
        {"entry_id": entry_id, "enabled": False},
    )
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        matching = [
            item
            for item in smart_shading_entries(api)
            if str(item.get("entry_id")) == entry_id
        ]
        if matching and matching[0].get("state") != "loaded":
            break
        time.sleep(1)
    else:
        raise AssertionError(f"Config entry {entry_id} stayed loaded after disable")
    api.call_service(
        "smart_shading_test_fixture",
        "set_entry_enabled",
        {"entry_id": entry_id, "enabled": True},
    )
    wait_for_entry_loaded(api, entry_id)


def recorded_calls(api: HomeAssistantApi) -> list[dict[str, Any]]:
    state = api.get("/api/states/sensor.fixture_service_calls")
    return list(state.get("attributes", {}).get("calls", []))


def run_interaction_matrix(
    api: HomeAssistantApi,
    scenario: dict[str, Any],
    easy_entry_id: str,
    advanced_entry_id: str,
) -> dict[str, Any]:
    """Run priority, unavailable-source and manual-intervention checks in HA."""
    evidence: dict[str, Any] = {}

    # A selected external source is authoritative: unavailable means wait,
    # never a silent fallback to sun geometry.
    api.call_service("smart_shading_test_fixture", "reset_calls", {})
    set_fixture_state(
        api,
        scenario["setup"]["sun_confirmation_entity"],
        {"state": "on", "available": False},
    )
    wait_for_state(
        api,
        scenario["setup"]["sun_confirmation_entity"],
        lambda item: item.get("state") == "unavailable",
    )
    reload_entry(api, easy_entry_id)
    # The lab owns sun.sun through its fixture. Reapply the scenario geometry
    # after an entry reload so this assertion never inherits a prior wizard or
    # lifecycle transition.
    set_fixture_state(api, "sun.sun", scenario["initial"]["sun.sun"])
    room_state = wait_for_state(
        api,
        entry_room_state(api, easy_entry_id)["entity_id"],
        lambda item: item.get("attributes", {}).get(
            "easy_confirmation_state"
        ) == "unavailable" and any(
            sector.get("confirmation_source") == "binary"
            and sector.get("status") == "source_unavailable"
            and sector.get("effective_active") is False
            for sector in item.get("attributes", {}).get("sector_statuses", [])
        ),
    )
    sectors = room_state.get("attributes", {}).get("sector_statuses", [])
    if (
        not sectors
        or room_state.get("attributes", {}).get("easy_confirmation_state")
        != "unavailable"
        or sectors[0].get("confirmation_source") != "binary"
        or sectors[0].get("status") != "source_unavailable"
        or sectors[0].get("effective_active") is not False
    ):
        raise AssertionError(f"Unavailable external source was not reported: {sectors}")
    if recorded_calls(api):
        raise AssertionError("Unavailable external source issued a cover command")
    evidence["external_unavailable"] = sectors[0]

    # Safety must override normal logic in the independent Advanced entry.
    set_fixture_state(
        api,
        scenario["advanced_setup"]["cover_entity"],
        {"state": "closed", "available": True, "attributes": {"current_position": 0}},
    )
    set_fixture_state(
        api,
        scenario["advanced_setup"]["lux_entity"],
        {"state": 0, "available": True},
    )
    api.call_service("smart_shading_test_fixture", "reset_calls", {})
    set_fixture_state(
        api,
        scenario["advanced_setup"]["safety_entity"],
        {"state": "on", "available": True},
    )
    safety_state = wait_for_state(
        api,
        entry_room_state(api, advanced_entry_id)["entity_id"],
        lambda item: item.get("state") == "safety",
    )
    wait_for_state(
        api,
        "sensor.fixture_service_calls",
        lambda item: int(float(item["state"])) >= 1,
    )
    evidence["safety_override"] = {
        "mode": safety_state["state"],
        "calls": recorded_calls(api),
    }
    set_fixture_state(
        api,
        scenario["advanced_setup"]["safety_entity"],
        {"state": "off", "available": True},
    )

    # A false external source must remain visible through Easy mode's compact
    # public contract instead of falling back to sun geometry.
    # Reapply the fixture geometry before checking the compact Easy-mode
    # aggregate. The compact public contract intentionally omits per-sector
    # confirmation_state, so the aggregate exposes the customer-facing result.
    set_fixture_state(api, "sun.sun", scenario["initial"]["sun.sun"])
    set_fixture_state(
        api,
        scenario["setup"]["sun_confirmation_entity"],
        {"state": "off", "available": True},
    )
    room_state = wait_for_state(
        api,
        entry_room_state(api, easy_entry_id)["entity_id"],
        lambda item: item.get("attributes", {}).get(
            "easy_confirmation_state"
        ) == "blocked" and any(
            sector.get("confirmation_source") == "binary"
            and sector.get("status") == "sun_not_confirmed"
            and sector.get("effective_active") is False
            for sector in item.get("attributes", {}).get("sector_statuses", [])
        ),
    )
    sectors = room_state.get("attributes", {}).get("sector_statuses", [])
    if (
        not sectors
        or room_state.get("attributes", {}).get("easy_confirmation_state")
        != "blocked"
        or sectors[0].get("confirmation_source") != "binary"
        or sectors[0].get("status") != "sun_not_confirmed"
        or sectors[0].get("effective_active") is not False
    ):
        raise AssertionError(
            f"External source off was not reported in the Easy contract: {sectors}"
        )

    # An unavailable selected lux sensor also blocks instead of using geometry.
    api.call_service("smart_shading_test_fixture", "reset_calls", {})
    set_fixture_state(
        api,
        scenario["advanced_setup"]["lux_entity"],
        {"state": 0, "available": False},
    )
    wait_for_state(
        api,
        scenario["advanced_setup"]["lux_entity"],
        lambda item: item.get("state") == "unavailable",
    )
    room_state = evaluate_entry(api, advanced_entry_id)
    sectors = room_state.get("attributes", {}).get("sector_statuses", [])
    if (
        not sectors
        or sectors[0].get("confirmation_source") != "lux"
        or sectors[0].get("confirmation_state") is not None
        or sectors[0].get("effective_active") is not False
    ):
        raise AssertionError(f"Unavailable lux source was not reported: {sectors}")
    if recorded_calls(api):
        raise AssertionError("Unavailable lux source issued a cover command")
    evidence["lux_unavailable"] = sectors[0]

    # Restore inputs so restart checks begin from a known healthy state.
    set_fixture_state(
        api,
        scenario["setup"]["sun_confirmation_entity"],
        {"state": "on", "available": True},
    )
    set_fixture_state(
        api,
        scenario["advanced_setup"]["lux_entity"],
        {"state": 0, "available": True},
    )
    return evidence


def write_snapshot(
    output_dir: Path,
    phase: str,
    entries: list[dict[str, Any]],
    entity_ids: list[str],
    calls: list[dict[str, Any]],
    api_config: dict[str, Any],
    interaction_matrix: dict[str, Any] | None = None,
) -> None:
    sanitized_config = dict(api_config)
    for key in ("latitude", "longitude", "external_url", "internal_url"):
        if key in sanitized_config:
            sanitized_config[key] = "<redacted>"
    snapshot = {
        "phase": phase,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "home_assistant": sanitized_config,
        "config_entries": entries,
        "entity_ids": entity_ids,
        "recorded_cover_calls": calls,
        "interaction_matrix": interaction_matrix or {},
    }
    (output_dir / f"snapshot-{phase}.json").write_text(
        json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8"
    )


def write_result(
    output_dir: Path,
    phase: str,
    scenario_id: str,
    success: bool,
    duration: float,
    error: str | None,
) -> None:
    result_path = output_dir / f"result-{phase}.json"
    result_path.write_text(
        json.dumps(
            {
                "scenario": scenario_id,
                "phase": phase,
                "success": success,
                "duration_seconds": round(duration, 3),
                "error": error,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    suite = ET.Element(
        "testsuite",
        name="smart-shading-ha-e2e",
        tests="1",
        failures="0" if success else "1",
        time=f"{duration:.3f}",
    )
    case = ET.SubElement(
        suite,
        "testcase",
        classname="ha_e2e",
        name=f"{scenario_id}[{phase}]",
        time=f"{duration:.3f}",
    )
    if error:
        ET.SubElement(case, "failure", message=error).text = error
    ET.ElementTree(suite).write(
        output_dir / f"junit-{phase}.xml", encoding="utf-8", xml_declaration=True
    )


def run_bootstrap(
    api: HomeAssistantApi,
    scenario: dict[str, Any],
    state_file: Path,
    output_dir: Path,
) -> None:
    token = onboard(api)
    state_file.write_text(json.dumps({"token": token}), encoding="utf-8")
    os.chmod(state_file, 0o600)
    wait_for_state(api, scenario["setup"]["cover_entity"], lambda _item: True)
    apply_initial_state(api, scenario)
    entry_id = create_easy_entry(api, scenario)
    wait_for_entry_loaded(api, entry_id)
    wait_for_smart_shading_entities(api, entry_id)
    assert_entry_variant(api, entry_id, False)
    explore_options_surfaces(api, entry_id)
    advanced_entry_id = create_advanced_entry(api, scenario)
    wait_for_entry_loaded(api, advanced_entry_id)
    wait_for_smart_shading_entities(api, advanced_entry_id)
    assert_entry_variant(api, advanced_entry_id, True)
    explore_options_surfaces(api, advanced_entry_id)
    assert_existing_room_night_transition(api, scenario, advanced_entry_id)
    explore_options_surfaces(api, advanced_entry_id)
    assert_existing_room_schedule_transition(api, advanced_entry_id)
    explore_options_surfaces(api, advanced_entry_id)
    assert_existing_cover_limit_transition(api, advanced_entry_id)
    explore_options_surfaces(api, advanced_entry_id)
    for profile, cover_entity, name in (
        ("vertical_blind", "cover.advanced_vertical", "Vertical blind"),
        ("exterior_screen", "cover.advanced_screen", "Exterior screen"),
        ("curtain", "cover.advanced_curtain", "Curtain"),
    ):
        add_advanced_group_through_options(
            api,
            advanced_entry_id,
            profile=profile,
            cover_entity=cover_entity,
            name=name,
        )
    assert_calculated_glare_zone_flow(api, advanced_entry_id)
    add_advanced_sector_through_options(api, scenario, advanced_entry_id)
    explore_options_surfaces(api, advanced_entry_id)
    choice_evidence = probe_choice_matrix(api, entry_id, advanced_entry_id)
    invalid_evidence = probe_invalid_wizard_inputs(
        api, entry_id, advanced_entry_id
    )
    calls = trigger_and_assert_cover_call(api, scenario, entry_id)
    matrix_evidence = run_interaction_matrix(
        api, scenario, entry_id, advanced_entry_id
    )
    matrix_evidence["wizard_choices"] = choice_evidence
    matrix_evidence["wizard_rejections"] = invalid_evidence
    unload_and_reload_entry(api, advanced_entry_id)
    add_easy_room_through_options(api, scenario, entry_id)
    wait_for_smart_shading_entities(api, entry_id)
    assert_live_wizard_coverage(output_dir)
    entries = smart_shading_entries(api)
    expected_titles = {
        scenario["expect"]["entry_title"],
        scenario["advanced_setup"]["house_name"],
    }
    if {entry.get("title") for entry in entries} != expected_titles:
        raise AssertionError(f"Unexpected config entries after setup: {entries}")
    entity_ids = assert_unique_entities(api)
    state_file.write_text(
        json.dumps(
            {
                "token": token,
                "entry_id": entry_id,
                "advanced_entry_id": advanced_entry_id,
                "entity_ids": entity_ids,
            }
        ),
        encoding="utf-8",
    )
    os.chmod(state_file, 0o600)
    write_snapshot(
        output_dir,
        "bootstrap",
        entries,
        entity_ids,
        calls,
        api.get("/api/config"),
        matrix_evidence,
    )


def run_upgrade_bootstrap(
    api: HomeAssistantApi,
    scenario: dict[str, Any],
    state_file: Path,
    output_dir: Path,
    baseline_version: str,
) -> None:
    """Create representative state with the published pre-upgrade version."""
    token = onboard(api)
    state_file.write_text(json.dumps({"token": token}), encoding="utf-8")
    os.chmod(state_file, 0o600)
    wait_for_state(api, scenario["setup"]["cover_entity"], lambda _item: True)
    apply_initial_state(api, scenario)
    entry_id = create_easy_entry(
        api,
        scenario,
        include_dashboard_badges=baseline_supports_dashboard_badges(
            baseline_version
        ),
    )
    wait_for_entry_loaded(api, entry_id)
    wait_for_smart_shading_entities(api, entry_id)
    assert_entry_variant(api, entry_id, False)
    legacy_compatible = baseline_uses_legacy_wizard(baseline_version)
    advanced_entry_id = create_advanced_entry(
        api,
        scenario,
        legacy_compatible=legacy_compatible,
        include_test_tools=False,
        include_dashboard_badges=baseline_supports_dashboard_badges(
            baseline_version
        ),
    )
    wait_for_entry_loaded(api, advanced_entry_id)
    wait_for_smart_shading_entities(api, advanced_entry_id)
    assert_entry_variant(api, advanced_entry_id, True)
    entries = smart_shading_entries(api)
    entity_ids = assert_unique_entities(api)
    state_file.write_text(
        json.dumps(
            {
                "token": token,
                "entry_id": entry_id,
                "advanced_entry_id": advanced_entry_id,
                "entity_ids": entity_ids,
                "upgrade_baseline": True,
                "upgrade_baseline_version": baseline_version,
            }
        ),
        encoding="utf-8",
    )
    os.chmod(state_file, 0o600)
    write_snapshot(
        output_dir,
        "bootstrap",
        entries,
        entity_ids,
        [],
        api.get("/api/config"),
        {
            "upgrade_baseline": (
                "legacy-compatible" if legacy_compatible else "calver"
            ),
            "upgrade_baseline_version": baseline_version,
        },
    )


def run_restart(
    api: HomeAssistantApi,
    scenario: dict[str, Any],
    saved_state: dict[str, Any],
    output_dir: Path,
) -> None:
    entry_id = str(saved_state["entry_id"])
    advanced_entry_id = str(saved_state["advanced_entry_id"])
    entries = smart_shading_entries(api)
    matching = [item for item in entries if str(item.get("entry_id")) == entry_id]
    if len(matching) != 1:
        raise AssertionError(f"Config entry did not survive restart: {entries}")
    advanced_matching = [
        item for item in entries if str(item.get("entry_id")) == advanced_entry_id
    ]
    if len(advanced_matching) != 1:
        raise AssertionError(f"Advanced config entry did not survive restart: {entries}")
    wait_for_entry_loaded(api, entry_id)
    wait_for_entry_loaded(api, advanced_entry_id)
    wait_for_state(api, scenario["setup"]["cover_entity"], lambda _item: True)
    wait_for_smart_shading_entities(api, entry_id)
    apply_initial_state(api, scenario)
    calls = trigger_and_assert_cover_call(api, scenario, entry_id)
    entity_ids = assert_unique_entities(api)
    expected_entity_ids = list(saved_state.get("entity_ids", []))
    if saved_state.get("upgrade_baseline"):
        expected_retired_ids = {
            entity_id
            for entity_id in expected_entity_ids
            if is_retired_legacy_optional_entity(entity_id)
        }
        retained_expected_ids = set(expected_entity_ids) - expected_retired_ids
        missing_entity_ids = sorted(retained_expected_ids - set(entity_ids))
        if missing_entity_ids:
            raise AssertionError(
                "Smart Shading entity IDs disappeared during upgrade: "
                f"missing={missing_entity_ids}, after={entity_ids}"
            )
        legacy_buttons_still_visible = sorted(
            expected_retired_ids & set(entity_ids)
        )
        if legacy_buttons_still_visible:
            raise AssertionError(
                "Legacy test buttons remained visible without feature opt-in: "
                f"{legacy_buttons_still_visible}"
            )
    elif expected_entity_ids and entity_ids != expected_entity_ids:
        raise AssertionError(
            "Smart Shading entity IDs changed across restart: "
            f"before={expected_entity_ids}, after={entity_ids}"
        )
    assert_entry_variant(api, entry_id, False)
    assert_entry_variant(api, advanced_entry_id, True)
    removal = api.delete(
        f"/api/config/config_entries/entry/{advanced_entry_id}"
    )
    if isinstance(removal, dict) and removal.get("require_restart"):
        raise AssertionError(f"Advanced entry removal requires restart: {removal}")
    wait_for_entry_removed(api, advanced_entry_id)
    reinstalled_entry_id = create_advanced_entry(api, scenario)
    wait_for_entry_loaded(api, reinstalled_entry_id)
    wait_for_smart_shading_entities(api, reinstalled_entry_id)
    assert_entry_variant(api, reinstalled_entry_id, True)
    entity_ids = assert_unique_entities(api)
    entries = smart_shading_entries(api)
    lifecycle = {
        "removed_entry_id": advanced_entry_id,
        "reinstalled_entry_id": reinstalled_entry_id,
    }
    (output_dir / "lifecycle-final.json").write_text(
        json.dumps(lifecycle, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    registry_response = api.post(
        "/api/services/smart_shading_test_fixture/registry_snapshot?return_response",
        {},
    )
    registry_snapshot = dict(registry_response.get("service_response") or {})
    registry_entities = list(registry_snapshot.get("entities") or [])
    registry_devices = list(registry_snapshot.get("devices") or [])
    registry_result = {
        **lifecycle,
        "stale_entities": sorted(
            entity["entity_id"]
            for entity in registry_entities
            if entity.get("config_entry_id") == advanced_entry_id
        ),
        "stale_devices": sorted(
            device["id"]
            for device in registry_devices
            if advanced_entry_id in (device.get("config_entries") or [])
        ),
        "current_entities": sorted(
            entity["entity_id"]
            for entity in registry_entities
            if entity.get("config_entry_id") == reinstalled_entry_id
        ),
    }
    (output_dir / "registry-summary.json").write_text(
        json.dumps(registry_result, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    if registry_result["stale_entities"] or registry_result["stale_devices"]:
        raise AssertionError(
            f"Removed config entry remains in live HA registries: {registry_result}"
        )
    if not registry_result["current_entities"]:
        raise AssertionError(
            "Reinstalled config entry has no live HA entity registry entries"
        )
    write_snapshot(
        output_dir, "restart", entries, entity_ids, calls, api.get("/api/config")
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8123")
    parser.add_argument("--phase", choices=("bootstrap", "restart"), required=True)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--bootstrap-mode", choices=("full", "upgrade"), default="full"
    )
    parser.add_argument("--upgrade-baseline-version", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    saved_state: dict[str, Any] = {}
    if args.phase == "restart":
        saved_state = json.loads(args.state_file.read_text(encoding="utf-8"))
    api = HomeAssistantApi(args.base_url, saved_state.get("token"))
    wait_for_home_assistant(api)
    started = time.monotonic()
    error: str | None = None
    try:
        if args.phase == "bootstrap":
            if args.bootstrap_mode == "upgrade":
                run_upgrade_bootstrap(
                    api,
                    scenario,
                    args.state_file,
                    args.output_dir,
                    args.upgrade_baseline_version,
                )
            else:
                run_bootstrap(
                    api, scenario, args.state_file, args.output_dir
                )
        else:
            run_restart(api, scenario, saved_state, args.output_dir)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    duration = time.monotonic() - started
    write_result(
        args.output_dir,
        args.phase,
        str(scenario["id"]),
        error is None,
        duration,
        error,
    )
    if error:
        print(error)
        return 1
    print(f"PASS {scenario['id']} [{args.phase}] ({duration:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
