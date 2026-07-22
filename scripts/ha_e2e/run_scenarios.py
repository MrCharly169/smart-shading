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
        except (URLError, ApiError, TimeoutError) as exc:
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
    return str(result["flow_id"])


def submit_flow(
    api: HomeAssistantApi, flow_id: str, step_id: str, data: dict[str, Any]
) -> dict[str, Any]:
    result = api.post(f"/api/config/config_entries/flow/{flow_id}", data)
    if result.get("errors"):
        raise AssertionError(f"Config-flow step {step_id} failed: {result}")
    return result


def create_easy_entry(api: HomeAssistantApi, scenario: dict[str, Any]) -> str:
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
            "advanced_mode": False,
            "diagnostic_level": "full",
            "evaluation_interval_minutes": 1,
        },
    )
    expect_step(result, "compact_room")
    result = submit_flow(
        api,
        flow_id,
        "compact_room",
        {
            "name": setup["room_name"],
        },
    )
    expect_step(result, "compact_schedule")
    result = submit_flow(
        api,
        flow_id,
        "compact_schedule",
        {
            "schedule_profile": "year_round",
            "default_pause_mode": "next_sunrise",
        },
    )
    expect_step(result, "compact_sector")
    result = submit_flow(
        api,
        flow_id,
        "compact_sector",
        {
            "direction": "south",
            "name": "South",
            "short": "S",
            "sun_source": "external",
        },
    )
    expect_step(result, "compact_sector_external")
    result = submit_flow(
        api,
        flow_id,
        "compact_sector_external",
        {
            "sun_presence_entity": setup["sun_confirmation_entity"],
        },
    )
    expect_step(result, "compact_layer")
    result = submit_flow(
        api,
        flow_id,
        "compact_layer",
        {
            "name": "Roller shutters",
            "profile": "roller_shutter",
            "cover_entities": [setup["cover_entity"]],
        },
    )
    expect_step(result, "compact_cover_details")
    result = submit_flow(
        api,
        flow_id,
        "compact_cover_details",
        {
            "name": "Easy Roller Shutter",
            "short": "C1",
            "window_safe_state": "on",
            "window_policy": "block_closing",
        },
    )
    expect_step(result, "after_room")
    result = submit_flow(api, flow_id, "after_room", {"next_step_id": "finish"})
    if result.get("type") != "create_entry":
        raise AssertionError(f"Config flow did not create an entry: {result}")
    entry_id = result.get("result", {}).get("entry_id")
    if not entry_id:
        entries = smart_shading_entries(api)
        matching = [item for item in entries if item.get("title") == setup["house_name"]]
        if len(matching) != 1:
            raise AssertionError(f"Cannot identify created config entry: {result}")
        entry_id = matching[0]["entry_id"]
    return str(entry_id)


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
    """Exercise the complete Advanced branch without sharing Easy entities."""
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
            "advanced_mode": True,
            "diagnostic_level": "full",
            "evaluation_interval_minutes": 1,
        },
    )
    expect_step(result, "compact_room")
    result = submit_flow(
        api,
        flow_id,
        "compact_room",
        {
            "name": setup["room_name"],
            "indoor_temperature": setup["indoor_temperature_entity"],
            "outdoor_temperature": setup["outdoor_temperature_entity"],
            "safety_blockers": [setup["safety_entity"]],
        },
    )
    expect_step(result, "compact_outdoor_temperature")
    result = submit_flow(
        api,
        flow_id,
        "compact_outdoor_temperature",
        {"outdoor_minimum": 12},
    )
    expect_step(result, "compact_schedule")
    result = submit_flow(
        api,
        flow_id,
        "compact_schedule",
        {
            "schedule_profile": "year_round",
            "default_pause_mode": "manual",
            "heat_during_pause": True,
        },
    )
    expect_step(result, "compact_sector")
    result = submit_flow(
        api,
        flow_id,
        "compact_sector",
        {
            "direction": "custom",
            "name": "Advanced South",
            "short": "AS",
            "sun_source": "lux",
        },
    )
    expect_step(result, "compact_sector_geometry")
    result = submit_flow(
        api,
        flow_id,
        "compact_sector_geometry",
        {"azimuth_start": 120, "azimuth_end": 240, "elevation_min": 10},
    )
    expect_step(result, "compact_sector_lux")
    result = submit_flow(
        api,
        flow_id,
        "compact_sector_lux",
        {"lux_sensor": setup["lux_entity"], "sun_preset": "custom"},
    )
    expect_step(result, "compact_sun_custom")
    result = submit_flow(
        api,
        flow_id,
        "compact_sun_custom",
        {
            "sun_on_lux": 100,
            "sun_off_lux": 50,
            "sun_on_delay": 0,
            "sun_off_delay": 0,
        },
    )
    expect_step(result, "compact_layer")
    result = submit_flow(
        api,
        flow_id,
        "compact_layer",
        {
            "name": "Advanced Venetian",
            "profile": "venetian",
            "cover_entities": [setup["cover_entity"]],
        },
    )
    expect_step(result, "compact_tilt_profile")
    result = submit_flow(
        api,
        flow_id,
        "compact_tilt_profile",
        {"tilt_preset": "balanced"},
    )
    expect_step(result, "compact_cover_details")
    result = submit_flow(
        api,
        flow_id,
        "compact_cover_details",
        {
            "name": "Advanced Venetian",
            "short": "A1",
            "window": setup["window_entity"],
            "window_safe_state": "off",
            "window_policy": "block_closing",
        },
    )
    expect_step(result, "after_room")
    result = submit_flow(api, flow_id, "after_room", {"next_step_id": "finish"})
    return _created_entry_id(api, result, setup["house_name"])


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
    unexpected = [
        item["entity_id"]
        for item in matching
        if item.get("attributes", {}).get("smart_shading_advanced_mode")
        is not advanced
    ]
    if unexpected:
        raise AssertionError(
            f"Easy/Advanced variant leaked for {entry_id}: {unexpected}"
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
    room_state = evaluate_entry(api, easy_entry_id)
    sectors = room_state.get("attributes", {}).get("sector_statuses", [])
    if not sectors or sectors[0].get("source_valid") is not False:
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
        scenario["advanced_setup"]["lux_entity"],
        {"state": 0, "available": False},
    )
    room_state = evaluate_entry(api, advanced_entry_id)
    sectors = room_state.get("attributes", {}).get("sector_statuses", [])
    if not sectors or sectors[0].get("source_valid") is not False:
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
    advanced_entry_id = create_advanced_entry(api, scenario)
    wait_for_entry_loaded(api, advanced_entry_id)
    wait_for_smart_shading_entities(api, advanced_entry_id)
    assert_entry_variant(api, advanced_entry_id, True)
    calls = trigger_and_assert_cover_call(api, scenario, entry_id)
    matrix_evidence = run_interaction_matrix(
        api, scenario, entry_id, advanced_entry_id
    )
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
