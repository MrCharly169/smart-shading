from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "validate_release_channel.py"
spec = importlib.util.spec_from_file_location("validate_release_channel", SCRIPT)
release_mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(release_mod)


class ReleaseChannelTests(unittest.TestCase):
    def _root(self, version: str) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        component = root / "custom_components" / "smart_shading"
        component.mkdir(parents=True)
        (component / "manifest.json").write_text(
            json.dumps({"version": version}),
            encoding="utf-8",
        )
        (root / "CHANGELOG.md").write_text(
            f"# Changelog\n\n## Unreleased\n\n## {version}\n\n- Release notes.\n",
            encoding="utf-8",
        )
        return root

    def test_beta_requires_develop_and_beta_calver(self):
        root = self._root("2026.8.0b1")
        self.assertEqual(
            release_mod.validate_release(
                "beta", "develop", "2026.8.0b1", root=root
            ),
            "2026.8.0b1",
        )
        with self.assertRaisesRegex(RuntimeError, "must run from develop"):
            release_mod.validate_release(
                "beta", "main", "2026.8.0b1", root=root
            )

    def test_stable_requires_main_and_stable_calver(self):
        root = self._root("2026.7.0")
        self.assertEqual(
            release_mod.validate_release(
                "stable", "main", "2026.7.0", root=root
            ),
            "2026.7.0",
        )
        with self.assertRaisesRegex(RuntimeError, "must run from main"):
            release_mod.validate_release(
                "stable", "develop", "2026.7.0", root=root
            )

    def test_channel_rejects_wrong_version_shape(self):
        beta_root = self._root("2026.8.0")
        with self.assertRaisesRegex(RuntimeError, "invalid for beta"):
            release_mod.validate_release(
                "beta", "develop", "2026.8.0", root=beta_root
            )
        stable_root = self._root("2026.8.0b1")
        with self.assertRaisesRegex(RuntimeError, "invalid for stable"):
            release_mod.validate_release(
                "stable", "main", "2026.8.0b1", root=stable_root
            )
        for invalid in ("2026.07.0", "2026.13.0", "5.0.0", "2026.8.0-beta.1"):
            with self.subTest(invalid=invalid):
                root = self._root(invalid)
                with self.assertRaisesRegex(RuntimeError, "invalid"):
                    release_mod.validate_release(
                        "stable", "main", invalid, root=root
                    )

    def test_confirmation_and_changelog_are_required(self):
        root = self._root("2026.8.0b1")
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            release_mod.validate_release(
                "beta", "develop", "2026.8.0b2", root=root
            )
        (root / "CHANGELOG.md").write_text(
            "# Changelog\n\n## Unreleased\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RuntimeError, "release section is invalid"):
            release_mod.validate_release(
                "beta", "develop", "2026.8.0b1", root=root
            )

    def test_dated_changelog_heading_is_accepted(self):
        root = self._root("2026.8.0b1")
        (root / "CHANGELOG.md").write_text(
            "# Changelog\n\n## Unreleased\n\n"
            "## 2026.8.0b1 - 2026-07-17\n\n- Prepared release.\n",
            encoding="utf-8",
        )
        self.assertEqual(
            release_mod.validate_release(
                "beta", "develop", "2026.8.0b1", root=root
            ),
            "2026.8.0b1",
        )


if __name__ == "__main__":
    unittest.main()
