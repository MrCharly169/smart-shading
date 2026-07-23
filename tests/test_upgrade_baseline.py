from __future__ import annotations

import unittest

from scripts.ha_e2e.select_upgrade_baseline import (
    newest_stable_tag,
    select_upgrade_baseline,
)


class UpgradeBaselineTests(unittest.TestCase):
    def test_newest_stable_tag_excludes_prereleases(self):
        self.assertEqual(
            newest_stable_tag(
                (
                    "v4.6.2-beta.9",
                    "v2026.7.0",
                    "v2026.8.0b0",
                    "v2026.7.1b1",
                )
            ),
            "v2026.7.0",
        )

    def test_newest_stable_tag_uses_numeric_calver_order(self):
        self.assertEqual(
            newest_stable_tag(("v2026.7.10", "v2026.8.0", "v2026.8.1b2")),
            "v2026.8.0",
        )

    def test_explicit_baseline_is_preserved_for_supplemental_checks(self):
        self.assertEqual(
            select_upgrade_baseline(" v4.6.2-beta.9 ", ("v4.6.2",)),
            "v4.6.2-beta.9",
        )

    def test_automatic_selection_requires_a_stable_tag(self):
        with self.assertRaisesRegex(RuntimeError, "No stable"):
            newest_stable_tag(("v2026.8.0b0", "not-a-version"))


if __name__ == "__main__":
    unittest.main()
