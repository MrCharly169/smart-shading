#!/usr/bin/env python3
"""Verify the public release contract HACS uses and build its install payload."""
from __future__ import annotations

import argparse
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen
import zipfile


API_ROOT = "https://api.github.com"
DOMAIN = "smart_shading"
TAG_PATTERN = re.compile(r"^v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)$")


class HacsReleaseError(RuntimeError):
    """Raised when a published release cannot be consumed by HACS."""


def request_bytes(url: str, token: str = "") -> bytes:
    """Read a public GitHub API or archive URL."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "smart-shading-hacs-qualification",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request(url, headers=headers), timeout=60) as response:
        return response.read()


def request_json(url: str, token: str = "") -> Any:
    """Read JSON from GitHub."""
    return json.loads(request_bytes(url, token).decode("utf-8"))


def version_from_tag(tag: str) -> str:
    """Return the manifest version represented by a release tag."""
    match = TAG_PATTERN.fullmatch(tag)
    if match is None:
        raise HacsReleaseError(f"Unsupported release tag {tag!r}")
    return match.group(1)


def expected_release_channel(tag: str) -> str:
    """Return the HACS release channel selected by the tag."""
    return "prerelease" if "-" in version_from_tag(tag) else "stable"


def select_hacs_release(releases: list[dict[str, Any]], channel: str) -> dict[str, Any]:
    """Mirror HACS release selection for stable or prerelease users."""
    for release in releases:
        if release.get("draft"):
            continue
        if channel == "stable" and release.get("prerelease"):
            continue
        return release
    raise HacsReleaseError(f"GitHub returned no published {channel} release")


def validate_release_metadata(
    repository: str,
    tag: str,
    repository_data: dict[str, Any],
    releases: list[dict[str, Any]],
    exact_release: dict[str, Any],
) -> dict[str, Any]:
    """Validate public visibility and HACS' selected release."""
    if repository_data.get("private"):
        raise HacsReleaseError(f"{repository} is private and cannot be read by HACS")
    if repository_data.get("archived"):
        raise HacsReleaseError(f"{repository} is archived")

    channel = expected_release_channel(tag)
    selected = select_hacs_release(releases, channel)
    if selected.get("tag_name") != tag:
        raise HacsReleaseError(
            f"HACS selects {selected.get('tag_name')!r} for {channel}; expected {tag!r}"
        )
    if exact_release.get("tag_name") != tag or exact_release.get("draft"):
        raise HacsReleaseError(f"Release {tag} is missing or still a draft")
    expected_prerelease = channel == "prerelease"
    if bool(exact_release.get("prerelease")) != expected_prerelease:
        raise HacsReleaseError(
            f"Release {tag} prerelease flag does not match channel {channel}"
        )
    zipball_url = str(exact_release.get("zipball_url") or "")
    if not zipball_url:
        raise HacsReleaseError(f"Release {tag} has no source archive")

    return {
        "repository": repository,
        "tag": tag,
        "channel": channel,
        "published_at": exact_release.get("published_at"),
        "source_archive_url": zipball_url,
        "release_assets": sorted(
            str(asset.get("name"))
            for asset in exact_release.get("assets", [])
            if asset.get("name")
        ),
    }


def inspect_source_archive(
    archive_payload: bytes,
    tag: str,
    install_archive: Path,
) -> dict[str, Any]:
    """Validate HACS layout and create the exact integration package for HA."""
    expected_version = version_from_tag(tag)
    try:
        source = zipfile.ZipFile(BytesIO(archive_payload))
    except zipfile.BadZipFile as exc:
        raise HacsReleaseError(f"Release {tag} source archive is not a ZIP") from exc

    file_names = [name for name in source.namelist() if not name.endswith("/")]
    roots = {PurePosixPath(name).parts[0] for name in file_names}
    if len(roots) != 1:
        raise HacsReleaseError("Release source archive must have one root directory")
    root = next(iter(roots))
    root_prefix = f"{root}/"

    relative_files: dict[str, bytes] = {}
    for name in file_names:
        if not name.startswith(root_prefix):
            raise HacsReleaseError(f"Archive member {name!r} is outside the root")
        relative = name.removeprefix(root_prefix)
        path = PurePosixPath(relative)
        if not relative or ".." in path.parts or path.is_absolute():
            raise HacsReleaseError(f"Unsafe archive member {name!r}")
        relative_files[relative] = source.read(name)

    integration_names = {
        PurePosixPath(name).parts[1]
        for name in relative_files
        if len(PurePosixPath(name).parts) >= 3
        and PurePosixPath(name).parts[0] == "custom_components"
    }
    if integration_names != {DOMAIN}:
        raise HacsReleaseError(
            "HACS integration archive must contain only "
            f"custom_components/{DOMAIN}; found {sorted(integration_names)}"
        )

    manifest_path = f"custom_components/{DOMAIN}/manifest.json"
    hacs_path = "hacs.json"
    try:
        manifest = json.loads(relative_files[manifest_path].decode("utf-8"))
        hacs = json.loads(relative_files[hacs_path].decode("utf-8"))
    except KeyError as exc:
        raise HacsReleaseError(f"Release archive is missing {exc.args[0]}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HacsReleaseError("Release manifest or hacs.json is invalid") from exc

    if manifest.get("domain") != DOMAIN:
        raise HacsReleaseError(f"Integration manifest domain must be {DOMAIN}")
    if manifest.get("version") != expected_version:
        raise HacsReleaseError(
            f"Tag {tag} contains manifest version {manifest.get('version')!r}"
        )
    if hacs.get("content_in_root") is not False:
        raise HacsReleaseError("hacs.json must set content_in_root to false")
    if hacs.get("hide_default_branch") is not True:
        raise HacsReleaseError("hacs.json must set hide_default_branch to true")

    required_component_files = (
        f"custom_components/{DOMAIN}/__init__.py",
        f"custom_components/{DOMAIN}/config_flow.py",
        f"custom_components/{DOMAIN}/frontend/shading.js",
    )
    missing = [name for name in required_component_files if name not in relative_files]
    if missing:
        raise HacsReleaseError("Release archive is missing " + ", ".join(missing))

    install_archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        install_archive, "w", compression=zipfile.ZIP_DEFLATED
    ) as target:
        for name in sorted(relative_files):
            if name.startswith(f"custom_components/{DOMAIN}/") or name in {
                "CHANGELOG.md",
                "LICENSE",
                "README.md",
                "hacs.json",
            }:
                target.writestr(name, relative_files[name])

    install_digest = sha256(install_archive.read_bytes()).hexdigest()
    return {
        "manifest_version": manifest["version"],
        "homeassistant_minimum": hacs.get("homeassistant"),
        "source_sha256": sha256(archive_payload).hexdigest(),
        "install_archive": str(install_archive),
        "install_sha256": install_digest,
        "integration_file_count": sum(
            name.startswith(f"custom_components/{DOMAIN}/")
            for name in relative_files
        ),
    }


def qualify_release(
    repository: str,
    tag: str,
    token: str,
    output: Path,
    install_archive: Path,
) -> dict[str, Any]:
    """Query the same public release data HACS uses and validate its payload."""
    if repository.count("/") != 1:
        raise HacsReleaseError("Repository must use owner/name format")
    encoded_tag = quote(tag, safe="")
    repository_data = request_json(f"{API_ROOT}/repos/{repository}", token)
    releases = request_json(
        f"{API_ROOT}/repos/{repository}/releases?per_page=30", token
    )
    exact_release = request_json(
        f"{API_ROOT}/repos/{repository}/releases/tags/{encoded_tag}", token
    )
    metadata = validate_release_metadata(
        repository, tag, repository_data, releases, exact_release
    )
    archive = request_bytes(metadata["source_archive_url"], token)
    result = {
        **metadata,
        **inspect_source_archive(archive, tag, install_archive),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--install-archive", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = qualify_release(
            args.repository,
            args.tag,
            os.environ.get("GITHUB_TOKEN", ""),
            args.output,
            args.install_archive,
        )
    except Exception as exc:
        print(f"HACS release qualification failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"HACS selects {result['tag']} ({result['channel']}); "
        f"manifest {result['manifest_version']} and public archive are valid"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
