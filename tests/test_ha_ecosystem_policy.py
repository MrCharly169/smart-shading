from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


class EcosystemPolicyTests(unittest.TestCase):
    def test_policy_contract_is_present(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        policy = (ROOT / "docs" / "HA_ECOSYSTEM_POLICY.md").read_text(encoding="utf-8")
        self.assertIn("Policy-Version: 1.9.0", agents)
        self.assertIn("Policy-Version: 1.9.0", policy)
        self.assertIn("long-list scroll offsets", policy)
        self.assertIn("Notification presentation contract", policy)
        self.assertIn("Notification navigation contract", policy)
        self.assertIn("Home Assistant language contract", policy)
        self.assertIn("regardless of the conversation language", policy)
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

    def test_persistent_notifications_use_the_shading_title_style(self) -> None:
        component = ROOT / "custom_components" / "smart_shading"
        style = (component / "notification_style.py").read_text(encoding="utf-8")
        engine = (component / "engine.py").read_text(encoding="utf-8")
        button = (component / "button.py").read_text(encoding="utf-8")
        self.assertIn('value.startswith("🪟")', style)
        self.assertIn("notification_title(title)", engine)
        self.assertIn("notification_title(localized", button)


if __name__ == "__main__":
    unittest.main()

