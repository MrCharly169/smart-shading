#!/usr/bin/env python3
"""Validate entity/device registry cleanup after the real HA lifecycle."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def storage_data(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload.get("data") or {})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--storage-dir", type=Path, required=True)
    parser.add_argument("--lifecycle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    lifecycle = json.loads(args.lifecycle.read_text(encoding="utf-8"))
    removed = str(lifecycle["removed_entry_id"])
    current = str(lifecycle["reinstalled_entry_id"])
    entities = storage_data(args.storage_dir / "core.entity_registry").get(
        "entities", []
    )
    devices = storage_data(args.storage_dir / "core.device_registry").get(
        "devices", []
    )
    stale_entities = [
        item.get("entity_id")
        for item in entities
        if item.get("config_entry_id") == removed
    ]
    stale_devices = [
        item.get("id")
        for item in devices
        if removed in (item.get("config_entries") or [])
    ]
    current_entities = [
        item.get("entity_id")
        for item in entities
        if item.get("config_entry_id") == current
    ]
    result = {
        "removed_entry_id": removed,
        "reinstalled_entry_id": current,
        "stale_entities": sorted(filter(None, stale_entities)),
        "stale_devices": sorted(filter(None, stale_devices)),
        "current_entities": sorted(filter(None, current_entities)),
    }
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )
    if stale_entities or stale_devices:
        raise SystemExit(
            f"Removed config entry remains in HA registries: {result}"
        )
    if not current_entities:
        raise SystemExit("Reinstalled config entry has no entity registry entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
