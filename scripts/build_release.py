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
REQUIRED = (
    COMPONENT / "manifest.json",
    COMPONENT / "__init__.py",
    COMPONENT / "config_flow.py",
    COMPONENT / "frontend" / "smart-shading-card.js",
    ROOT / "hacs.json",
    ROOT / "README.md",
)


def validate() -> str:
    missing = [str(path.relative_to(ROOT)) for path in REQUIRED if not path.is_file()]
    if missing:
        raise RuntimeError("Missing required files: " + ", ".join(missing))
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("domain") != "smart_shading":
        raise RuntimeError("manifest domain must be smart_shading")
    version = str(manifest.get("version", "")).strip()
    if not version:
        raise RuntimeError("manifest version is missing")
    card = (COMPONENT / "frontend" / "smart-shading-card.js").read_text(encoding="utf-8")
    if version not in card:
        raise RuntimeError("frontend card does not contain the manifest version")
    return version


def build(output: Path) -> None:
    version = validate()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(COMPONENT.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.write(path, path.relative_to(ROOT))
        for path in (ROOT / "README.md", ROOT / "README_DE.md", ROOT / "LICENSE", ROOT / "hacs.json"):
            archive.write(path, path.relative_to(ROOT))
    print(f"Built {output} for Smart Shading {version}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="validate without creating an archive")
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "smart_shading.zip")
    args = parser.parse_args()
    try:
        version = validate()
        if args.check:
            print(f"Smart Shading {version}: package structure is valid")
        else:
            build(args.output)
    except Exception as exc:
        print(f"release validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
