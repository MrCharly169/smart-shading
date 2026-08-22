from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


class EcosystemPolicyTests(unittest.TestCase):
    def test_policy_contract_is_present(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        policy = (ROOT / "docs" / "HA_ECOSYSTEM_POLICY.md").read_text(encoding="utf-8")
        self.assertIn("Policy-Version: 1.6.0", agents)
        self.assertIn("Policy-Version: 1.6.0", policy)
        self.assertIn("Notification navigation contract", policy)
        self.assertIn("back_path", policy)
        self.assertIn("Living customer documentation contract", policy)
        self.assertIn("single multilingual service catalog", policy)
        self.assertIn("certificate-pinned", policy)
        self.assertIn("Luxembourgish, German, French", policy)
        self.assertIn("Native-first Home Assistant contract", policy)
        self.assertIn("Future scheduled or announced occurrences", policy)
        self.assertIn("b0` through `b9", policy)
        self.assertIn("native Interactions", policy)
        self.assertIn("`hass-action` contract", policy)
        self.assertIn("System-wide change protocol", policy)
        self.assertIn("Durable progress and release handoff", policy)
        self.assertIn("fresh release workspace", policy)
        self.assertIn("explicit user authorization", policy)


if __name__ == "__main__":
    unittest.main()

