#!/usr/bin/env python3
"""Prepare and extract changelog-driven Smart Shading releases."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
CALVER_BASE = r"20[0-9]{2}\.(?:[1-9]|1[0-2])\.[0-9]+"
BETA_VERSION = re.compile(rf"^{CALVER_BASE}b[0-9]+$")
STABLE_VERSION = re.compile(rf"^{CALVER_BASE}$")
LEGACY_BETA_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+-beta\.[0-9]+$")
LEGACY_STABLE_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
SECTION_HEADING = re.compile(
    r"(?m)^##[ \t]+(?P<title>[^\r\n]+?)[ \t]*\r?\n"
)
DATED_VERSION = re.compile(
    rf"^(?P<version>(?:{CALVER_BASE}(?:b[0-9]+)?|"
    r"[0-9]+\.[0-9]+\.[0-9]+(?:-beta\.[0-9]+)?))"
    r"(?:[ \t]+-[ \t]+(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2}))?$"
)


@dataclass(frozen=True)
class ChangelogSection:
    """A second-level changelog section."""

    title: str
    start: int
    body_start: int
    end: int
    body: str


@dataclass(frozen=True)
class ReleasePreparation:
    """Metadata produced while preparing a release."""

    channel: str
    version: str
    source_branch: str
    target_branch: str
    release_date: str
    notes: str


def target_branch(channel: str) -> str:
    """Return the only branch allowed for a release channel."""
    if channel == "beta":
        return "develop"
    if channel == "stable":
        return "main"
    raise RuntimeError(f"unsupported release channel {channel!r}")


def source_branch(channel: str) -> str:
    """Return the tested source branch used to prepare a release."""
    if channel in {"beta", "stable"}:
        return "develop"
    raise RuntimeError(f"unsupported release channel {channel!r}")


def validate_version(channel: str, version: str) -> str:
    """Validate and return a normalized release version."""
    normalized = version
    if channel not in {"beta", "stable"}:
        raise RuntimeError(f"unsupported release channel {channel!r}")
    pattern = BETA_VERSION if channel == "beta" else STABLE_VERSION
    expected = "YYYY.M.PATCHbN" if channel == "beta" else "YYYY.M.PATCH"
    if not pattern.fullmatch(normalized):
        raise RuntimeError(
            f"version {version!r} is invalid for {channel}; expected {expected}"
        )
    return normalized


def validate_date(value: str) -> str:
    """Validate and return a canonical ISO release date."""
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise RuntimeError(
            f"release date {value!r} is invalid; expected YYYY-MM-DD"
        ) from exc
    if parsed.isoformat() != value:
        raise RuntimeError(f"release date {value!r} is not canonical YYYY-MM-DD")
    return value


def changelog_sections(text: str) -> list[ChangelogSection]:
    """Parse second-level changelog sections in document order."""
    matches = list(SECTION_HEADING.finditer(text))
    sections: list[ChangelogSection] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append(
            ChangelogSection(
                title=match.group("title").strip(),
                start=match.start(),
                body_start=match.end(),
                end=end,
                body=text[match.end() : end].strip(),
            )
        )
    return sections


def _version_from_title(title: str) -> str | None:
    match = DATED_VERSION.fullmatch(title)
    if not match:
        return None
    release_date = match.group("date")
    if release_date:
        try:
            if date.fromisoformat(release_date).isoformat() != release_date:
                return None
        except ValueError:
            return None
    return match.group("version")


def _find_unreleased(sections: list[ChangelogSection]) -> ChangelogSection:
    matches = [section for section in sections if section.title == "Unreleased"]
    if len(matches) != 1:
        raise RuntimeError("CHANGELOG.md must contain exactly one '## Unreleased' section")
    return matches[0]


def _existing_versions(sections: list[ChangelogSection]) -> set[str]:
    return {
        version
        for section in sections
        if (version := _version_from_title(section.title)) is not None
    }


def _nest_markdown_under_beta(text: str) -> str:
    """Nest headings embedded below an aggregated beta release heading."""

    def replace_heading(match: re.Match[str]) -> str:
        hashes = match.group("hashes")
        title = match.group("title")
        depth = len(hashes) + 2
        if depth <= 6:
            return f"{'#' * depth} {title}"
        return f"**{title}**"

    return re.sub(
        r"(?m)^(?P<hashes>#{3,6})[ \t]+(?P<title>[^\r\n]+)$",
        replace_heading,
        text,
    )


def _beta_history_since_stable(
    sections: list[ChangelogSection], unreleased: ChangelogSection
) -> list[tuple[str, str]]:
    """Return beta sections newer than the latest stable section."""
    history: list[tuple[str, str]] = []
    for section in sections:
        if section.start <= unreleased.start:
            continue
        version = _version_from_title(section.title)
        if version is None:
            continue
        if STABLE_VERSION.fullmatch(version) or LEGACY_STABLE_VERSION.fullmatch(
            version
        ):
            break
        if (
            BETA_VERSION.fullmatch(version)
            or LEGACY_BETA_VERSION.fullmatch(version)
        ) and section.body:
            history.append((version, section.body))
    return history


def _release_notes(
    channel: str,
    unreleased_body: str,
    beta_history: list[tuple[str, str]],
) -> str:
    parts: list[str] = []
    if unreleased_body.strip():
        parts.append(unreleased_body.strip())

    if channel == "stable" and beta_history:
        beta_parts = ["### Included beta release history"]
        for version, body in beta_history:
            beta_parts.extend(
                [f"#### {version}", _nest_markdown_under_beta(body.strip())]
            )
        parts.append("\n\n".join(beta_parts))

    notes = "\n\n".join(parts).strip()
    if not notes:
        if channel == "beta":
            raise RuntimeError("CHANGELOG.md 'Unreleased' section is empty")
        raise RuntimeError(
            "stable release has neither Unreleased changes nor beta history"
        )
    return notes


def prepare_release(
    channel: str,
    source: str,
    target: str,
    version: str,
    release_date: str,
    *,
    root: Path = ROOT,
) -> ReleasePreparation:
    """Update manifest and changelog for a reviewable release pull request."""
    normalized_version = validate_version(channel, version)
    normalized_date = validate_date(release_date)
    expected_source = source_branch(channel)
    expected_branch = target_branch(channel)
    normalized_source = source.removeprefix("refs/heads/")
    normalized_target = target.removeprefix("refs/heads/")
    if normalized_source != expected_source:
        raise RuntimeError(
            f"{channel} preparation must use {expected_source} as its source, "
            f"not {normalized_source}"
        )
    if normalized_target != expected_branch:
        raise RuntimeError(
            f"{channel} preparation must target {expected_branch}, not {normalized_target}"
        )

    manifest_path = root / "custom_components" / "smart_shading" / "manifest.json"
    changelog_path = root / "CHANGELOG.md"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    changelog = changelog_path.read_text(encoding="utf-8")
    sections = changelog_sections(changelog)
    unreleased = _find_unreleased(sections)

    if normalized_version in _existing_versions(sections):
        raise RuntimeError(
            f"CHANGELOG.md already contains release version {normalized_version}"
        )

    beta_history = _beta_history_since_stable(sections, unreleased)
    notes = _release_notes(channel, unreleased.body, beta_history)

    manifest["version"] = normalized_version
    updated_manifest = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"

    prefix = changelog[: unreleased.start].rstrip()
    suffix = changelog[unreleased.end :].strip()
    updated_changelog = (
        f"{prefix}\n\n"
        "## Unreleased\n\n\n"
        f"## {normalized_version} - {normalized_date}\n\n"
        f"{notes.rstrip()}\n"
    )
    if suffix:
        updated_changelog += f"\n\n{suffix}\n"

    manifest_path.write_text(updated_manifest, encoding="utf-8")
    changelog_path.write_text(updated_changelog, encoding="utf-8")
    return ReleasePreparation(
        channel=channel,
        version=normalized_version,
        source_branch=expected_source,
        target_branch=expected_branch,
        release_date=normalized_date,
        notes=notes,
    )


def extract_release_notes(text: str, version: str) -> str:
    """Extract the exact changelog body for a published version."""
    normalized_version = version.strip().removeprefix("v")
    matches = [
        section
        for section in changelog_sections(text)
        if _version_from_title(section.title) == normalized_version
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"CHANGELOG.md must contain exactly one release section for {normalized_version}"
        )
    notes = matches[0].body.strip()
    if not notes:
        raise RuntimeError(f"CHANGELOG.md release section {normalized_version} is empty")
    return notes


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--channel", choices=("beta", "stable"), required=True)
    prepare.add_argument("--source-branch", required=True)
    prepare.add_argument("--target-branch", required=True)
    prepare.add_argument("--version", required=True)
    prepare.add_argument("--date", required=True)
    prepare.add_argument("--root", type=Path, default=ROOT)

    notes = subparsers.add_parser("notes")
    notes.add_argument("--version", required=True)
    notes.add_argument("--output", type=Path, required=True)
    notes.add_argument("--root", type=Path, default=ROOT)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "prepare":
            prepared = prepare_release(
                args.channel,
                args.source_branch,
                args.target_branch,
                args.version,
                args.date,
                root=args.root,
            )
            print(
                f"Prepared {prepared.channel} release v{prepared.version} "
                f"from {prepared.source_branch} for {prepared.target_branch}"
            )
        else:
            changelog = (args.root / "CHANGELOG.md").read_text(encoding="utf-8")
            release_notes = extract_release_notes(changelog, args.version)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(release_notes.rstrip() + "\n", encoding="utf-8")
            print(f"Wrote release notes for {args.version} to {args.output}")
    except Exception as exc:
        print(f"release changelog operation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
