#!/usr/bin/env python3
"""Build or validate an installable Smart Shading release archive."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "smart_shading"
CANONICAL_RESOURCE = "/smart_shading/shading.js"
LEGACY_RESOURCE = COMPONENT / "frontend" / "smart-shading-card.js"
REQUIRED = (
    COMPONENT / "manifest.json",
    COMPONENT / "__init__.py",
    COMPONENT / "config_flow.py",
    COMPONENT / "frontend" / "shading.js",
    LEGACY_RESOURCE,
    ROOT / "hacs.json",
    ROOT / "README.md",
    ROOT / "CHANGELOG.md",
)


def validate(expected_tag: str | None = None) -> str:
    """Validate package structure and return the manifest version."""
    missing = [str(path.relative_to(ROOT)) for path in REQUIRED if not path.is_file()]
    if missing:
        raise RuntimeError("Missing required files: " + ", ".join(missing))

    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("domain") != "smart_shading":
        raise RuntimeError("manifest domain must be smart_shading")
    version = str(manifest.get("version", "")).strip()
    if not version:
        raise RuntimeError("manifest version is missing")

    if expected_tag:
        tag_version = expected_tag.removeprefix("v")
        if tag_version != version:
            raise RuntimeError(
                f"release tag {expected_tag} does not match manifest version {version}"
            )

    legacy = LEGACY_RESOURCE.read_text(encoding="utf-8")
    if 'import "./shading.js"' not in legacy:
        raise RuntimeError("legacy card resource must import the canonical shading.js")

    for document in (ROOT / "README.md",):
        text = document.read_text(encoding="utf-8")
        if CANONICAL_RESOURCE not in text:
            raise RuntimeError(
                f"{document.name} must document the canonical resource "
                f"{CANONICAL_RESOURCE}"
            )
        if "/smart_shading/shading.js?v=" in text:
            raise RuntimeError(
                f"{document.name} must not add a version query to the resource URL"
            )

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if "## Unreleased" not in changelog:
        raise RuntimeError("CHANGELOG.md must contain an Unreleased section")
    if f"## {version}" not in changelog:
        raise RuntimeError(
            f"CHANGELOG.md must contain a release section for manifest version {version}"
        )
    return version


def build(output: Path, expected_tag: str | None = None) -> None:
    version = validate(expected_tag)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(COMPONENT.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.write(path, path.relative_to(ROOT))
        for path in (
            ROOT / "README.md",
            ROOT / "CHANGELOG.md",
            ROOT / "LICENSE",
            ROOT / "hacs.json",
        ):
            archive.write(path, path.relative_to(ROOT))
    print(f"Built {output} for Smart Shading {version}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true", help="validate without creating an archive"
    )
    parser.add_argument(
        "--tag",
        help="optional release tag; must match manifest version (leading v allowed)",
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "dist" / "smart_shading.zip"
    )
    args = parser.parse_args()
    try:
        if args.check:
            version = validate(args.tag)
            print(f"Smart Shading {version}: package structure is valid")
        else:
            build(args.output, args.tag)
    except Exception as exc:
        print(f"release validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
