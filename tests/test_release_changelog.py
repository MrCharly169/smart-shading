from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts import release_changelog


class ReleaseChangelogTests(unittest.TestCase):
    def _root(self, changelog: str, version: str = "4.6.0-beta.2") -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        component = root / "custom_components" / "smart_shading"
        component.mkdir(parents=True)
        (component / "manifest.json").write_text(
            json.dumps({"domain": "smart_shading", "version": version}) + "\n",
            encoding="utf-8",
        )
        (root / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
        return root

    def test_beta_preparation_moves_unreleased_and_updates_manifest(self):
        root = self._root(
            "# Changelog\n\n"
            "## Unreleased\n\n"
            "### Fixed\n\n- Manual pause synchronization.\n\n"
            "## 4.6.0-beta.2 - 2026-07-16\n\n- Earlier change.\n"
        )

        prepared = release_changelog.prepare_release(
            "beta",
            "develop",
            "develop",
            "4.6.0-beta.3",
            "2026-07-17",
            root=root,
        )

        manifest = json.loads(
            (root / "custom_components/smart_shading/manifest.json").read_text(
                encoding="utf-8"
            )
        )
        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertEqual(manifest["version"], "4.6.0-beta.3")
        self.assertEqual(prepared.source_branch, "develop")
        self.assertEqual(prepared.target_branch, "develop")
        self.assertIn(
            "## Unreleased\n\n\n## 4.6.0-beta.3 - 2026-07-17\n",
            changelog,
        )
        self.assertEqual(
            release_changelog.extract_release_notes(changelog, "4.6.0-beta.3"),
            "### Fixed\n\n- Manual pause synchronization.",
        )

    def test_stable_preparation_promotes_develop_and_aggregates_betas(self):
        root = self._root(
            "# Changelog\n\n"
            "## Unreleased\n\n"
            "## 4.6.0-beta.4 - 2026-07-17\n\n"
            "### Fixed\n\n- Latest beta fix.\n\n"
            "## 4.6.0-beta.3 - 2026-07-16\n\n"
            "### Added\n\n- Earlier beta feature.\n\n"
            "## 4.5.0 - 2026-07-01\n\n- Previous stable release.\n\n"
            "## 4.5.1-beta.1 - 2026-06-30\n\n- Older beta.\n",
            version="4.6.0-beta.4",
        )

        prepared = release_changelog.prepare_release(
            "stable",
            "develop",
            "main",
            "4.6.0",
            "2026-07-18",
            root=root,
        )

        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
        notes = release_changelog.extract_release_notes(changelog, "4.6.0")
        self.assertEqual(prepared.source_branch, "develop")
        self.assertEqual(prepared.target_branch, "main")
        self.assertIn("### Included beta release history", notes)
        self.assertLess(notes.index("#### 4.6.0-beta.4"), notes.index("#### 4.6.0-beta.3"))
        self.assertIn("##### Fixed", notes)
        self.assertIn("##### Added", notes)
        self.assertNotIn("Older beta", notes)
        self.assertIn("## 4.6.0-beta.4 - 2026-07-17", changelog)

    def test_beta_rejects_empty_unreleased_without_writing_files(self):
        root = self._root(
            "# Changelog\n\n## Unreleased\n\n"
            "## 4.6.0-beta.2 - 2026-07-16\n\n- Earlier.\n"
        )
        manifest_path = root / "custom_components/smart_shading/manifest.json"
        changelog_path = root / "CHANGELOG.md"
        original_manifest = manifest_path.read_text(encoding="utf-8")
        original_changelog = changelog_path.read_text(encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "Unreleased.*empty"):
            release_changelog.prepare_release(
                "beta",
                "develop",
                "develop",
                "4.6.0-beta.3",
                "2026-07-17",
                root=root,
            )

        self.assertEqual(manifest_path.read_text(encoding="utf-8"), original_manifest)
        self.assertEqual(changelog_path.read_text(encoding="utf-8"), original_changelog)

    def test_channel_rejects_wrong_source_target_and_version(self):
        root = self._root("# Changelog\n\n## Unreleased\n\n- Change.\n")
        cases = (
            ("beta", "main", "develop", "4.6.0-beta.3", "must use develop"),
            ("beta", "develop", "main", "4.6.0-beta.3", "must target develop"),
            ("stable", "develop", "develop", "4.6.0", "must target main"),
            ("stable", "develop", "main", "4.6.0-beta.3", "invalid for stable"),
            ("beta", "develop", "develop", "v4.6.0-beta.3", "invalid for beta"),
        )
        for channel, source, target, version, error in cases:
            with self.subTest(channel=channel, source=source, target=target, version=version):
                with self.assertRaisesRegex(RuntimeError, error):
                    release_changelog.prepare_release(
                        channel,
                        source,
                        target,
                        version,
                        "2026-07-17",
                        root=root,
                    )

    def test_invalid_date_and_duplicate_version_are_rejected(self):
        root = self._root(
            "# Changelog\n\n## Unreleased\n\n- Change.\n\n"
            "## 4.6.0-beta.3 - 2026-07-16\n\n- Existing.\n"
        )
        with self.assertRaisesRegex(RuntimeError, "invalid; expected YYYY-MM-DD"):
            release_changelog.prepare_release(
                "beta",
                "develop",
                "develop",
                "4.6.0-beta.4",
                "2026-02-30",
                root=root,
            )
        with self.assertRaisesRegex(RuntimeError, "already contains"):
            release_changelog.prepare_release(
                "beta",
                "develop",
                "develop",
                "4.6.0-beta.3",
                "2026-07-17",
                root=root,
            )

    def test_release_notes_require_one_nonempty_matching_section(self):
        with self.assertRaisesRegex(RuntimeError, "exactly one release section"):
            release_changelog.extract_release_notes(
                "# Changelog\n\n## Unreleased\n", "4.6.0"
            )
        with self.assertRaisesRegex(RuntimeError, "exactly one release section"):
            release_changelog.extract_release_notes(
                "# Changelog\n\n## 4.6.0\n\n- First.\n\n"
                "## 4.6.0 - 2026-07-17\n\n- Second.\n",
                "4.6.0",
            )
        with self.assertRaisesRegex(RuntimeError, "is empty"):
            release_changelog.extract_release_notes(
                "# Changelog\n\n## 4.6.0 - 2026-07-17\n", "4.6.0"
            )
        with self.assertRaisesRegex(RuntimeError, "exactly one release section"):
            release_changelog.extract_release_notes(
                "# Changelog\n\n## 4.6.0 - 2026-02-30\n\n- Invalid date.\n",
                "4.6.0",
            )


if __name__ == "__main__":
    unittest.main()
