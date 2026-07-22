from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts.ha_e2e.check_hacs_release import (
    HacsReleaseError,
    inspect_source_archive,
    select_hacs_release,
    validate_release_metadata,
)


def source_archive(version: str = "4.6.2") -> bytes:
    payload = BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        root = "MrCharly169-smart-shading-release"
        archive.writestr(
            f"{root}/custom_components/smart_shading/manifest.json",
            json.dumps({"domain": "smart_shading", "version": version}),
        )
        archive.writestr(
            f"{root}/custom_components/smart_shading/__init__.py", ""
        )
        archive.writestr(
            f"{root}/custom_components/smart_shading/config_flow.py", ""
        )
        archive.writestr(
            f"{root}/custom_components/smart_shading/frontend/shading.js", ""
        )
        archive.writestr(
            f"{root}/hacs.json",
            json.dumps(
                {
                    "content_in_root": False,
                    "hide_default_branch": True,
                    "homeassistant": "2026.6.0",
                }
            ),
        )
        archive.writestr(f"{root}/README.md", "Smart Shading")
    return payload.getvalue()


class HacsReleaseTests(unittest.TestCase):
    def test_stable_selection_skips_drafts_and_prereleases(self):
        releases = [
            {"tag_name": "v4.6.3", "draft": True, "prerelease": False},
            {"tag_name": "v4.6.3-beta.0", "draft": False, "prerelease": True},
            {"tag_name": "v4.6.2", "draft": False, "prerelease": False},
        ]
        self.assertEqual(select_hacs_release(releases, "stable")["tag_name"], "v4.6.2")
        self.assertEqual(
            select_hacs_release(releases, "prerelease")["tag_name"],
            "v4.6.3-beta.0",
        )

    def test_metadata_requires_the_requested_tag_to_be_hacs_latest(self):
        release = {
            "tag_name": "v4.6.2",
            "draft": False,
            "prerelease": False,
            "zipball_url": "https://api.github.test/archive.zip",
            "assets": [{"name": "smart_shading-v4.6.2.zip"}],
        }
        result = validate_release_metadata(
            "owner/repository",
            "v4.6.2",
            {"private": False, "archived": False},
            [release],
            release,
        )
        self.assertEqual(result["channel"], "stable")
        self.assertEqual(result["release_assets"], ["smart_shading-v4.6.2.zip"])

        with self.assertRaises(HacsReleaseError):
            validate_release_metadata(
                "owner/repository",
                "v4.6.1",
                {"private": False, "archived": False},
                [release],
                {**release, "tag_name": "v4.6.1"},
            )

    def test_source_archive_builds_the_exact_home_assistant_install_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            install_archive = Path(temp_dir) / "smart_shading-v4.6.2.zip"
            result = inspect_source_archive(
                source_archive(), "v4.6.2", install_archive
            )
            with zipfile.ZipFile(install_archive) as archive:
                names = set(archive.namelist())

        self.assertEqual(result["manifest_version"], "4.6.2")
        self.assertEqual(result["homeassistant_minimum"], "2026.6.0")
        self.assertIn("custom_components/smart_shading/manifest.json", names)
        self.assertIn("hacs.json", names)

    def test_source_archive_rejects_a_tag_manifest_mismatch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(HacsReleaseError):
                inspect_source_archive(
                    source_archive("4.6.1"),
                    "v4.6.2",
                    Path(temp_dir) / "install.zip",
                )


if __name__ == "__main__":
    unittest.main()
