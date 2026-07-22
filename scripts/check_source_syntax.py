#!/usr/bin/env python3
"""Validate syntax for every source/config file shipped or used by CI."""
from __future__ import annotations

import json
from pathlib import Path
import py_compile
import subprocess
import sys
import tempfile


ROOT = Path(__file__).parents[1]
SOURCE_ROOTS = {".github", "custom_components", "e2e", "scripts", "tests"}


def repository_files() -> list[Path]:
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return sorted(
        ROOT / relative
        for relative in result.stdout.splitlines()
        if relative and relative.split("/", 1)[0] in SOURCE_ROOTS
    )


def run(command: list[str], files: list[Path]) -> None:
    if not files:
        return
    subprocess.run(
        [*command, *(str(path.relative_to(ROOT)) for path in files)],
        cwd=ROOT,
        check=True,
    )


def main() -> int:
    files = repository_files()
    python_files = [path for path in files if path.suffix == ".py"]
    javascript_files = [
        path for path in files if path.suffix in {".js", ".cjs", ".mjs"}
    ]
    json_files = [path for path in files if path.suffix == ".json"]
    shell_files = [path for path in files if path.suffix == ".sh"]
    yaml_files = [
        path for path in files if path.suffix in {".yaml", ".yml"}
    ]

    with tempfile.TemporaryDirectory(prefix="smart-shading-syntax-") as temp:
        bytecode_root = Path(temp)
        for path in python_files:
            relative = path.relative_to(ROOT)
            target = bytecode_root / relative.with_suffix(".pyc")
            target.parent.mkdir(parents=True, exist_ok=True)
            py_compile.compile(
                str(path), cfile=str(target), doraise=True
            )

    for path in json_files:
        with path.open(encoding="utf-8") as handle:
            json.load(handle)

    for path in javascript_files:
        run(["node", "--check"], [path])
    run(["bash", "-n"], shell_files)
    run(
        [
            "ruby",
            "-e",
            (
                'require "yaml"; ARGV.each { |path| '
                "YAML.parse_file(path) || raise(\"empty YAML: #{path}\") }"
            ),
        ],
        yaml_files,
    )

    counts = {
        "Python": len(python_files),
        "JavaScript": len(javascript_files),
        "JSON": len(json_files),
        "shell": len(shell_files),
        "YAML": len(yaml_files),
    }
    print(
        "Source syntax valid: "
        + ", ".join(f"{name}={count}" for name, count in counts.items())
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, py_compile.PyCompileError, subprocess.CalledProcessError) as exc:
        print(f"Source syntax validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
