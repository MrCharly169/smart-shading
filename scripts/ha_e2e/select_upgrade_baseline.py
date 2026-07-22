#!/usr/bin/env python3
"""Select the stable release baseline for Home Assistant upgrade testing."""
from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path
import re
import subprocess
import sys


STABLE_TAG = re.compile(r"^v(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")
ROOT = Path(__file__).parents[2]


def newest_stable_tag(tags: Iterable[str]) -> str:
    """Return the highest normal-release tag, excluding all prereleases."""
    candidates: list[tuple[tuple[int, int, int], str]] = []
    for tag in tags:
        match = STABLE_TAG.fullmatch(tag.strip())
        if match is None:
            continue
        candidates.append(
            (
                tuple(int(match.group(part)) for part in ("major", "minor", "patch")),
                tag.strip(),
            )
        )
    if not candidates:
        raise RuntimeError("No stable Smart Shading release tag exists")
    return max(candidates)[1]


def select_upgrade_baseline(requested_ref: str, tags: Iterable[str]) -> str:
    """Honor an explicit baseline, otherwise select the newest stable tag."""
    normalized = requested_ref.strip()
    return normalized or newest_stable_tag(tags)


def repository_tags(repository: Path) -> list[str]:
    """List local release tags from the full checkout used by the CI workflow."""
    result = subprocess.run(
        ["git", "tag", "--list", "v*"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requested-ref", default="")
    parser.add_argument("--repository", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        print(select_upgrade_baseline(args.requested_ref, repository_tags(args.repository)))
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"upgrade baseline selection failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
