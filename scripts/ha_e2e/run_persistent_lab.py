#!/usr/bin/env python3
"""Verify a protected, dedicated persistent Home Assistant test instance."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any
from urllib.request import Request, urlopen


def request(base_url: str, token: str, method: str, path: str, data=None) -> Any:
    payload = json.dumps(data).encode() if data is not None else None
    req = Request(
        f"{base_url.rstrip('/')}{path}",
        data=payload,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urlopen(req, timeout=30) as response:
        body = response.read().decode()
        return json.loads(body) if body else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("before-restart", "after-restart"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    base_url = os.environ["HA_PERSISTENT_URL"]
    token = os.environ["HA_PERSISTENT_TOKEN"]
    expected_name = os.environ["HA_PERSISTENT_INSTANCE_NAME"]
    expected_version = os.environ.get("HA_PERSISTENT_EXPECTED_VERSION", "")
    hacs_update_entity = os.environ.get("HA_PERSISTENT_HACS_UPDATE_ENTITY", "")
    if os.environ.get("HA_PERSISTENT_SCOPE") != "dedicated-test-only":
        raise SystemExit("HA_PERSISTENT_SCOPE must be dedicated-test-only")

    deadline = time.monotonic() + 180
    while True:
        try:
            config = request(base_url, token, "GET", "/api/config")
            break
        except Exception:
            if time.monotonic() >= deadline:
                raise
            time.sleep(2)
    if config.get("location_name") != expected_name:
        raise SystemExit(
            f"Refusing unexpected HA instance {config.get('location_name')!r}; "
            f"expected {expected_name!r}"
        )

    entries = [
        entry
        for entry in request(base_url, token, "GET", "/api/config/config_entries/entry")
        if entry.get("domain") == "smart_shading"
    ]
    if not entries:
        raise SystemExit("Persistent lab has no Smart Shading config entry")
    for entry in entries:
        result = request(
            base_url,
            token,
            "POST",
            f"/api/config/config_entries/entry/{entry['entry_id']}/reload",
            {},
        )
        if result.get("require_restart"):
            raise SystemExit(f"Entry {entry['entry_id']} could not reload")

    states = request(base_url, token, "GET", "/api/states")
    entities = sorted(
        item["entity_id"]
        for item in states
        if item.get("attributes", {}).get("smart_shading_entry_id")
    )
    hacs_version = None
    if expected_version or hacs_update_entity:
        if not expected_version or not hacs_update_entity:
            raise SystemExit(
                "Both HA_PERSISTENT_EXPECTED_VERSION and "
                "HA_PERSISTENT_HACS_UPDATE_ENTITY are required for HACS validation"
            )
        hacs_state = request(
            base_url,
            token,
            "GET",
            f"/api/states/{hacs_update_entity}",
        )
        hacs_version = str(
            hacs_state.get("attributes", {}).get("installed_version") or ""
        )
        if hacs_version != expected_version:
            raise SystemExit(
                f"HACS reports Smart Shading {hacs_version!r}; "
                f"expected {expected_version!r}"
            )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "phase": args.phase,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "instance_name": expected_name,
                "home_assistant_version": config.get("version"),
                "hacs_installed_version": hacs_version,
                "entries": [
                    {key: entry.get(key) for key in ("entry_id", "title", "state")}
                    for entry in entries
                ],
                "entity_ids": entities,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
