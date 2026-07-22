#!/usr/bin/env python3
"""Write concise HA E2E results to a GitHub job summary."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_dir", type=Path)
    args = parser.parse_args()
    rows = []
    for path in sorted(args.artifact_dir.glob("result-*.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        rows.append(
            (
                result["phase"],
                "✅ passed" if result["success"] else "❌ failed",
                result["duration_seconds"],
                result.get("error") or "",
            )
        )
    lines = [
        "## Smart Shading Home Assistant E2E",
        "",
        "| Phase | Result | Duration | Details |",
        "| --- | --- | ---: | --- |",
    ]
    if rows:
        for phase, status, duration, error in rows:
            safe_error = str(error).replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {phase} | {status} | {duration}s | {safe_error} |")
    else:
        lines.append("| laboratory | ❌ no result | — | Runner stopped before producing a result |")
    lines.extend(
        [
            "",
            "The workflow artifact contains Home Assistant logs, container metadata, generated configuration, scenario data, snapshots, recorded cover calls, JSON results, and JUnit XML.",
        ]
    )
    summary = "\n".join(lines) + "\n"
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with Path(target).open("a", encoding="utf-8") as handle:
            handle.write(summary)
    else:
        print(summary, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
