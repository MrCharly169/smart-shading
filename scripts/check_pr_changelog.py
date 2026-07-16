#!/usr/bin/env python3
"""Require user-visible production changes to update the changelog."""
from __future__ import annotations

import subprocess
import sys

PRODUCTION_PREFIXES = (
    "custom_components/smart_shading/",
    "scripts/",
    ".github/workflows/",
)
EXEMPT_PATHS = {
    "custom_components/smart_shading/manifest.json",
}


def changed_files(base_ref: str) -> set[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_pr_changelog.py BASE_REF", file=sys.stderr)
        return 2

    changed = changed_files(sys.argv[1])
    production_changed = any(
        path.startswith(PRODUCTION_PREFIXES) and path not in EXEMPT_PATHS
        for path in changed
    )
    if production_changed and "CHANGELOG.md" not in changed:
        print(
            "Production or release behavior changed without a CHANGELOG.md update.",
            file=sys.stderr,
        )
        return 1

    print("PR changelog policy is satisfied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
