#!/usr/bin/env python3
"""Drive Smart Shading through a real Home Assistant HTTP API."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


LIVE_WIZARD_COVERAGE: dict[str, set[str]] = {}
OPTIONS_SURFACE_PATHS: dict[tuple[str, str], tuple[str, ...]] = {}


@dataclass
class ApiError(RuntimeError):
    method: str
    path: str
    status: int
    body: str

    def __str__(self) -> str:
        return f"{self.method} {self.path} failed with HTTP {self.status}: {self.body}"


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
    try:
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
    except ApiError as exc:
        # Newer Home Assistant releases can mark this step done directly from
        # configuration.yaml. Only that already-completed response is benign.
        if exc.status not in {400, 403}:
            raise
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
    LIVE_WIZARD_COVERAGE.setdefault(step_id, set()).update(
        _schema_fields(result.get("data_schema", []))
    )


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


def create_easy_entry(api: HomeAssistantApi, scenario: dict[str, Any]) -> str:
    """Create an Easy entry through the current schema-15 guided flow."""
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
    expect_step(result, "global_settings")
    result = submit_flow(
        api,
        flow_id,
        "global_settings",
        {"sun_entity": "sun.sun"},
    )
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


def create_advanced_entry(api: HomeAssistantApi, scenario: dict[str, Any]) -> str:
    """Exercise the complete current Advanced branch and optional features."""
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
    expect_step(result, "global_settings")
    result = submit_flow(
        api,
        flow_id,
        "global_settings",
        {"sun_entity": "sun.sun"},
    )
    expect_step(result, "room_setup")
    result = submit_flow(
        api,
        flow_id,
        "room_setup",
        {
            "room_details": {
                "name": setup["room_name"],
                "indoor_temperature": setup["indoor_temperature_entity"],
                "outdoor_temperature": setup["outdoor_temperature_entity"],
            }
        },
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
            "target_positions": {
                "open_position": 100,
                "open_tilt": 0,
                "heat_tilt": 100,
            },
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
    expect_step(result, "manage_cover_special")
    result = submit_flow(
        api, flow_id, "manage_cover_special", {"enforce_max_open_position": True}
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
                "active_months": [str(value) for value in range(1, 13)],
                "active_weekdays": [str(value) for value in range(7)],
                "start_time": "06:00:00",
                "end_time": "22:00:00",
                "outside_schedule_behavior": "open",
                "heat_outside_schedule": True,
            },
            "temperature_settings": temperature_settings,
        },
    )
    expect_step(result, "manage_night")
    result = submit_flow(
        api,
        flow_id,
        "manage_night",
        {"night_enabled": True},
    )
    expect_step(result, "manage_night")
    result = submit_flow(
        api,
        flow_id,
        "manage_night",
        {
            "night_enabled": True,
            "night_source": "sun",
            "night_entity": "input_boolean.fixture_night_mode",
            "night_morning_transition_minutes": 0,
            "night_evening_transition_minutes": 0,
        },
    )
    expect_step(result, "manage_night")
    result = submit_flow(
        api,
        flow_id,
        "manage_night",
        {
            "night_enabled": True,
            "night_source": "sun",
            "night_start_offset_minutes": 0,
            "night_end_offset_minutes": 0,
            "night_morning_transition_minutes": 0,
            "night_evening_transition_minutes": 0,
        },
    )
    expect_step(result, "initial_night_targets")
    result = submit_flow(
        api,
        flow_id,
        "initial_night_targets",
        {"night_position": 0, "night_tilt": 100},
    )
    expect_step(result, "manage_pause")
    result = submit_flow(
        api,
        flow_id,
        "manage_pause",
        {
            "default_pause_mode": "next_night_end",
            "pause_sun_offset_minutes": -60,
            "pause_duration_hours": 2,
            "external_movement_detection": True,
            "heat_during_pause": True,
        },
    )
    expect_step(result, "manage_conditions")
    condition_sources = {
        "safety_blockers": [setup["safety_entity"]],
        "irradiance_sensor": "sensor.irradiance",
        "cloud_cover_sensor": "sensor.cloud_cover",
        "weather_permission": "binary_sensor.weather_permission",
        "glare_sensor": "binary_sensor.glare",
        "occupancy_sensor": "binary_sensor.occupancy",
        "heat_requires_sun": True,
    }
    result = submit_flow(api, flow_id, "manage_conditions", condition_sources)
    expect_step(result, "manage_conditions")
    result = submit_flow(
        api,
        flow_id,
        "manage_conditions",
        {
            **condition_sources,
            "irradiance_minimum": 150,
            "cloud_cover_maximum": 85,
            "weather_logic": "all",
            "comfort_requires_occupancy": False,
            "safety_behavior": "move_safe",
            "heat_ignores_weather": True,
        },
    )
    expect_step(result, "initial_safety_targets")
    result = submit_flow(
        api,
        flow_id,
        "initial_safety_targets",
        {"safety_position": 100, "safety_tilt": 0},
    )
    expect_step(result, "init")
    result = submit_flow(api, flow_id, "init", {"next_step_id": "finish"})
    expect_step(result, "finish")
    result = submit_flow(api, flow_id, "finish", {"confirm_start": True})
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
    save_options_from_group_hub(api, flow_id, result)
    wait_for_entry_loaded(api, entry_id)
    explore_options_surfaces(api, entry_id)


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

    temperature = {
        "heat_temperature": 27,
        "evening_release_time": "18:00:00",
        "sunset_offset_minutes": 0,
        "comfort_temperature": 23.5,
        "solar_temperature": 25.5,
    }
    for profile in ("year_round", "summer", "custom"):
        flow_id, _ = replay_options_path(
            api, advanced_entry_id, "manage_automation"
        )
        try:
            result = submit_options_flow(
                api,
                flow_id,
                "manage_automation",
                {
                    "schedule_settings": {
                        "schedule_enabled": True,
                        "schedule_profile": profile,
                        "day_window": "all_day",
                        "active_months": ["1"],
                        "active_weekdays": ["0"],
                        "start_time": "06:00:00",
                        "end_time": "22:00:00",
                        "outside_schedule_behavior": "open",
                        "heat_outside_schedule": True,
                    },
                    "temperature_settings": temperature,
                },
            )
            expect_step(result, "manage_automation")
            schedule_settings: dict[str, Any] = {
                "schedule_enabled": True,
                "schedule_profile": profile,
                "day_window": "all_day",
            }
            if profile == "custom":
                schedule_settings.update(
                    {"active_months": ["1"], "active_weekdays": ["0"]}
                )
            if profile != "year_round":
                schedule_settings.update(
                    {
                        "outside_schedule_behavior": "open",
                        "heat_outside_schedule": True,
                    }
                )
            result = submit_options_flow(
                api,
                flow_id,
                "manage_automation",
                {
                    "schedule_settings": schedule_settings,
                    "temperature_settings": temperature,
                },
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

    flow_id, _ = replay_options_path(
        api, advanced_entry_id, "manage_automation"
    )
    try:
        result = submit_options_flow(
            api,
            flow_id,
            "manage_automation",
            {
                "schedule_settings": {
                    "schedule_enabled": True,
                    "schedule_profile": "custom",
                    "day_window": "fixed_time",
                    "active_months": ["1"],
                    "active_weekdays": ["0"],
                    "start_time": "06:00:00",
                    "end_time": "22:00:00",
                    "outside_schedule_behavior": "hold",
                    "heat_outside_schedule": True,
                },
                "temperature_settings": temperature,
            },
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
        flow_id, _ = replay_options_path(api, advanced_entry_id, "manage_night")
        try:
            result = submit_options_flow(
                api,
                flow_id,
                "manage_night",
                {
                    "night_enabled": True,
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
                        "night_enabled": True,
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

    condition_sources = {
        "safety_blockers": ["binary_sensor.safety_alarm"],
        "irradiance_sensor": "sensor.irradiance",
        "irradiance_minimum": 150,
        "cloud_cover_sensor": "sensor.cloud_cover",
        "cloud_cover_maximum": 85,
        "weather_permission": "binary_sensor.weather_permission",
        "glare_sensor": "binary_sensor.glare",
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
        flow_id, _ = replay_options_path(
            api, advanced_entry_id, "manage_conditions"
        )
        try:
            result = submit_options_flow(
                api,
                flow_id,
                "manage_conditions",
                {
                    **condition_sources,
                    "safety_behavior": behavior,
                    "weather_logic": weather_logic,
                },
            )
            expect_step(result, "room_hub")
            evidence["safety_behaviors"].append(behavior)
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
    """Fail the real HA job when a mandatory flow surface was not observed."""
    contract_path = (
        Path(__file__).parents[2]
        / "e2e"
        / "ha"
        / "scenarios"
        / "wizard_coverage.json"
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    required = set(contract["live_required"])
    observed = set(LIVE_WIZARD_COVERAGE)
    missing = sorted(required - observed)
    report = {
        "required": sorted(required),
        "observed": {
            step: sorted(fields)
            for step, fields in sorted(LIVE_WIZARD_COVERAGE.items())
        },
        "missing": missing,
    }
    (output_dir / "wizard-coverage-live.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    if missing:
        raise AssertionError(
            f"Mandatory wizard surfaces were not exercised in real HA: {missing}"
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
    """Prove that the integration releases and recreates its HA platforms."""
    result = api.post(
        f"/api/config/config_entries/entry/{entry_id}/unload", {}
    )
    if result.get("require_restart"):
        raise AssertionError(f"Config entry could not unload cleanly: {result}")
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
        raise AssertionError(f"Config entry {entry_id} stayed loaded after unload")
    reload_entry(api, entry_id)


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
    room_state = wait_for_state(
        api,
        entry_room_state(api, easy_entry_id)["entity_id"],
        lambda item: any(
            sector.get("confirmation_source") == "binary"
            and sector.get("confirmation_state") is None
            and sector.get("status") == "source_unavailable"
            and sector.get("effective_active") is False
            for sector in item.get("attributes", {}).get("sector_statuses", [])
        ),
    )
    sectors = room_state.get("attributes", {}).get("sector_statuses", [])
    if (
        not sectors
        or sectors[0].get("confirmation_state") is not None
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

    # An unavailable selected lux sensor also blocks instead of using geometry.
    api.call_service("smart_shading_test_fixture", "reset_calls", {})
    set_fixture_state(
        api,
        scenario["setup"]["sun_confirmation_entity"],
        {"state": "off", "available": True},
    )
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
    if expected_entity_ids and entity_ids != expected_entity_ids:
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
    (output_dir / "lifecycle-final.json").write_text(
        json.dumps(
            {
                "removed_entry_id": advanced_entry_id,
                "reinstalled_entry_id": reinstalled_entry_id,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
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
            run_bootstrap(api, scenario, args.state_file, args.output_dir)
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
