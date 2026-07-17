#!/usr/bin/env python3
"""Validate a manually selected Smart Shading release channel."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    from scripts.release_changelog import extract_release_notes
except ModuleNotFoundError:  # Direct execution adds scripts/, not the repository root.
    from release_changelog import extract_release_notes

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "custom_components" / "smart_shading" / "manifest.json"
CHANGELOG = ROOT / "CHANGELOG.md"
BETA_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+-beta\.[0-9]+$")
STABLE_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def validate_release(
    channel: str,
    branch: str,
    confirm_version: str,
    *,
    root: Path = ROOT,
) -> str:
    """Validate branch, SemVer channel, confirmation, and changelog."""
    manifest = root / "custom_components" / "smart_shading" / "manifest.json"
    changelog_path = root / "CHANGELOG.md"
    version = str(json.loads(manifest.read_text(encoding="utf-8"))["version"]).strip()
    normalized_branch = branch.removeprefix("refs/heads/")

    expected_branch = "develop" if channel == "beta" else "main"
    if normalized_branch != expected_branch:
        raise RuntimeError(
            f"{channel} releases must run from {expected_branch}, not {normalized_branch}"
        )

    pattern = BETA_VERSION if channel == "beta" else STABLE_VERSION
    if not pattern.fullmatch(version):
        expected = "X.Y.Z-beta.N" if channel == "beta" else "X.Y.Z"
        raise RuntimeError(
            f"manifest version {version!r} is invalid for {channel}; expected {expected}"
        )

    if confirm_version.strip() != version:
        raise RuntimeError(
            f"confirmation {confirm_version!r} does not match manifest version {version!r}"
        )

    changelog = changelog_path.read_text(encoding="utf-8")
    try:
        extract_release_notes(changelog, version)
    except RuntimeError as exc:
        raise RuntimeError(f"CHANGELOG.md release section is invalid: {exc}") from exc

    return version


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", choices=("beta", "stable"), required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--confirm-version", required=True)
    args = parser.parse_args()
    try:
        version = validate_release(
            args.channel,
            args.branch,
            args.confirm_version,
        )
    except Exception as exc:
        print(f"release channel validation failed: {exc}", file=sys.stderr)
        return 1
    print(f"Validated {args.channel} release v{version} from {args.branch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
