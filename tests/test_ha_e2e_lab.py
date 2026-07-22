from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
LAB = ROOT / "e2e" / "ha"
FIXTURE = LAB / "fixture" / "custom_components" / "smart_shading_test_fixture"


class HomeAssistantE2ELabTests(unittest.TestCase):
    def test_scenario_declares_setup_action_runtime_and_restart_checks(self):
        scenario = json.loads(
            (LAB / "scenarios" / "easy_lifecycle.json").read_text(encoding="utf-8")
        )
        self.assertEqual(scenario["setup"]["variant"], "easy")
        self.assertEqual(
            scenario["setup"]["cover_entity"], "cover.easy_roller_shutter"
        )
        self.assertIn("sun.sun", scenario["initial"])
        self.assertIn("set_cover_position", scenario["expect"]["cover_services"])
        self.assertTrue(scenario["restart_check"]["entry_must_persist"])
        self.assertEqual(scenario["advanced_setup"]["variant"], "advanced")
        self.assertNotEqual(
            scenario["setup"]["cover_entity"],
            scenario["advanced_setup"]["cover_entity"],
        )

    def test_issue_73_interaction_matrix_has_every_required_area(self):
        matrix = json.loads(
            (LAB / "scenarios" / "interaction_matrix.json").read_text(
                encoding="utf-8"
            )
        )
        cases = matrix["cases"]
        areas = {case["area"] for case in cases}
        self.assertTrue(
            {
                "runtime", "sun-source", "availability", "temperature",
                "cover", "commands", "manual", "priority", "schedule",
                "window", "lifecycle", "registry", "migration", "frontend",
            }.issubset(areas)
        )
        self.assertTrue(all(case.get("automation") for case in cases))
        self.assertGreaterEqual(len(cases), 25)

    def test_fixture_manifest_and_python_sources_are_valid(self):
        manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["domain"], "smart_shading_test_fixture")
        self.assertEqual(manifest["iot_class"], "local_push")
        for path in FIXTURE.glob("*.py"):
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_fixture_controls_availability_geometry_and_records_calls(self):
        setup = (FIXTURE / "__init__.py").read_text(encoding="utf-8")
        cover = (FIXTURE / "cover.py").read_text(encoding="utf-8")
        recorder = (FIXTURE / "sensor.py").read_text(encoding="utf-8")
        self.assertIn('hass.states.async_set(entity_id, "unavailable"', setup)
        self.assertIn("sun.sun", setup)
        self.assertIn('"set_cover_position",', cover)
        self.assertIn('"calls": list(self._store.calls)', recorder)

    def test_runner_installs_release_and_never_exports_token(self):
        shell = (ROOT / "scripts" / "ha_e2e" / "run_lab.sh").read_text(
            encoding="utf-8"
        )
        runner = (ROOT / "scripts" / "ha_e2e" / "run_scenarios.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("scripts/build_release.py", shell)
        self.assertIn("docker restart", shell)
        self.assertNotIn('cp "${STATE_FILE}"', shell)
        self.assertIn("/api/config/config_entries/flow", runner)
        self.assertIn("/api/config/config_entries/entry/{entry_id}/reload", runner)
        self.assertIn("create_advanced_entry", runner)
        self.assertIn("run_interaction_matrix", runner)
        self.assertIn("wait_for_entry_removed", runner)

    def test_workflow_is_separate_filtered_and_collects_evidence(self):
        workflow = (ROOT / ".github" / "workflows" / "ha-e2e.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("pull_request:", workflow)
        self.assertIn("paths:", workflow)
        self.assertIn("scripts/ha_e2e/run_lab.sh", workflow)
        self.assertIn("if: always()", workflow)
        self.assertIn("actions/upload-artifact@v4", workflow)
        self.assertIn("workflow_call:", workflow)

    def test_ui_nightly_and_persistent_workflows_are_present_and_scoped(self):
        ui = (ROOT / ".github" / "workflows" / "ha-ui-e2e.yml").read_text(
            encoding="utf-8"
        )
        nightly = (ROOT / ".github" / "workflows" / "ha-nightly.yml").read_text(
            encoding="utf-8"
        )
        persistent = (
            ROOT / ".github" / "workflows" / "ha-persistent-lab.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("playwright", ui.lower())
        self.assertIn("workflow_call:", ui)
        self.assertIn("home-assistant:beta", nightly)
        self.assertIn("continue-on-error", nightly)
        self.assertIn("[self-hosted, linux, smart-shading-lab]", persistent)
        self.assertIn("environment: ha-persistent-lab", persistent)
        self.assertNotIn("ssh ", persistent.lower())
        self.assertIn("/opt/smart-shading-lab/bin/deploy-candidate", persistent)

    def test_release_requires_real_ha_and_browser_gates(self):
        release = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("uses: ./.github/workflows/ha-e2e.yml", release)
        self.assertIn("uses: ./.github/workflows/ha-ui-e2e.yml", release)
        self.assertIn("needs: [ha-e2e, ha-ui-e2e]", release)


if __name__ == "__main__":
    unittest.main()
