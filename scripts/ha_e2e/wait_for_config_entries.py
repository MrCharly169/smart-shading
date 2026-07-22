#!/usr/bin/env python3
"""Wait until Home Assistant has persisted upgrade-baseline config entries."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time


def stored_smart_shading_entry_ids(path: Path) -> set[str]:
    """Return persisted Smart Shading config-entry IDs."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = (payload.get("data") or {}).get("entries") or []
    return {
        str(item["entry_id"])
        for item in entries
        if item.get("domain") == "smart_shading" and item.get("entry_id")
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--storage", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--wait-seconds", type=float, default=60)
    args = parser.parse_args()
    state = json.loads(args.state.read_text(encoding="utf-8"))
    expected = {str(state["entry_id"]), str(state["advanced_entry_id"])}
    deadline = time.monotonic() + args.wait_seconds
    persisted: set[str] = set()
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            persisted = stored_smart_shading_entry_ids(args.storage)
            if expected <= persisted:
                return 0
        except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
            last_error = exc
        time.sleep(1)
    raise SystemExit(
        "Upgrade baseline was not persisted before package replacement: "
        f"expected={sorted(expected)}, persisted={sorted(persisted)}, "
        f"last_error={last_error}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
