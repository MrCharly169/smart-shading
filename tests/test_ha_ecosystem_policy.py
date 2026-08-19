from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


class EcosystemPolicyTests(unittest.TestCase):
    def test_policy_contract_is_present(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        policy = (ROOT / "docs" / "HA_ECOSYSTEM_POLICY.md").read_text(encoding="utf-8")
        self.assertIn("Policy-Version: 1.1.0", agents)
        self.assertIn("Policy-Version: 1.1.0", policy)
        self.assertIn("Native-first Home Assistant contract", policy)
        self.assertIn("b0` through `b9", policy)
        self.assertIn("native Interactions", policy)
        self.assertIn("`hass-action` contract", policy)
        self.assertIn("System-wide change protocol", policy)


if __name__ == "__main__":
    unittest.main()

