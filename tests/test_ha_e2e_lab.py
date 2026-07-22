from __future__ import annotations

import ast
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.ha_e2e.run_scenarios import (
    ApiError,
    assert_entry_variant,
    submit_options_expect_error,
    wait_for_home_assistant,
)
from scripts.ha_e2e.check_registry import registry_result
from scripts.ha_e2e.wait_for_config_entries import (
    stored_smart_shading_entry_ids,
)


ROOT = Path(__file__).parents[1]
LAB = ROOT / "e2e" / "ha"
FIXTURE = LAB / "fixture" / "custom_components" / "smart_shading_test_fixture"


class HomeAssistantE2ELabTests(unittest.TestCase):
    def test_upgrade_checkpoint_reads_only_persisted_smart_shading_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = Path(temp_dir) / "core.config_entries"
            storage.write_text(
                json.dumps(
                    {
                        "data": {
                            "entries": [
                                {"domain": "smart_shading", "entry_id": "easy"},
                                {
                                    "domain": "smart_shading",
                                    "entry_id": "advanced",
                                },
                                {"domain": "sun", "entry_id": "ignored"},
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            result = stored_smart_shading_entry_ids(storage)
        self.assertEqual(result, {"easy", "advanced"})

    def test_registry_audit_distinguishes_removed_and_reinstalled_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = Path(temp_dir)
            (storage / "core.entity_registry").write_text(
                json.dumps(
                    {
                        "data": {
                            "entities": [
                                {
                                    "entity_id": "sensor.current_room",
                                    "config_entry_id": "current-entry",
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            (storage / "core.device_registry").write_text(
                json.dumps({"data": {"devices": []}}), encoding="utf-8"
            )

            result = registry_result(
                storage,
                {
                    "removed_entry_id": "removed-entry",
                    "reinstalled_entry_id": "current-entry",
                },
            )

        self.assertEqual(result["stale_entities"], [])
        self.assertEqual(result["stale_devices"], [])
        self.assertEqual(result["current_entities"], ["sensor.current_room"])

    def test_invalid_choice_can_be_rejected_by_home_assistant_schema(self):
        class RejectingApi:
            def post(self, path, data):
                raise ApiError(
                    "POST",
                    path,
                    400,
                    '{"errors":{"direction":"value must be one of [south]"}}',
                )

        result = submit_options_expect_error(
            RejectingApi(),
            "flow-id",
            "add_sector_flat",
            {"direction": "custom"},
            "option_not_available",
            expected_schema_field="direction",
        )
        self.assertEqual(result["type"], "schema_error")

    def test_variant_contract_uses_public_layout_attribute(self):
        class StatesApi:
            def get(self, path):
                self.path = path
                return [
                    {
                        "entity_id": "sensor.customer_room_status",
                        "attributes": {
                            "smart_shading_entry_id": "easy-entry",
                            "smart_shading_layout": "compact",
                        },
                    },
                    {
                        "entity_id": "sensor.customer_room_status_2",
                        "attributes": {
                            "smart_shading_entry_id": "advanced-entry",
                            "smart_shading_layout": "detailed",
                        },
                    },
                ]

        api = StatesApi()
        assert_entry_variant(api, "easy-entry", False)
        assert_entry_variant(api, "advanced-entry", True)
        self.assertEqual(api.path, "/api/states")

    def test_readiness_retries_transient_connection_reset(self):
        class ResetOnceApi:
            token = None

            def __init__(self):
                self.calls = 0

            def get(self, path, *, authenticated=True):
                self.calls += 1
                if self.calls == 1:
                    raise ConnectionResetError("Home Assistant is still starting")
                return {"done": False}

        api = ResetOnceApi()
        with patch("scripts.ha_e2e.run_scenarios.time.sleep") as sleep:
            wait_for_home_assistant(api, timeout=1)

        self.assertEqual(api.calls, 2)
        sleep.assert_called_once_with(2)

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
        self.assertIn("LIGHT_LUX", recorder)
        self.assertNotIn("UnitOfIlluminance", recorder)
        self.assertIn('"set_entry_enabled"', setup)
        self.assertIn("async_set_disabled_by", setup)

    def test_runner_installs_release_and_never_exports_token(self):
        shell = (ROOT / "scripts" / "ha_e2e" / "run_lab.sh").read_text(
            encoding="utf-8"
        )
        runner = (ROOT / "scripts" / "ha_e2e" / "run_scenarios.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("scripts/build_release.py", shell)
        self.assertIn("HA_E2E_RELEASE_ARCHIVE", shell)
        self.assertIn("docker restart", shell)
        self.assertIn('docker stop --time 30 "${CONTAINER_NAME}"', shell)
        self.assertIn("--wait-seconds 60", shell)
        self.assertIn("--tmpfs /run:rw,exec,nosuid,size=64m", shell)
        self.assertIn('chown -R "${HOST_UID}:${HOST_GID}" /config', shell)
        self.assertIn("docker run --rm --entrypoint chown", shell)
        self.assertNotIn('cp "${STATE_FILE}"', shell)
        self.assertIn("/api/config/config_entries/flow", runner)
        self.assertIn('"/api/onboarding/integration"', runner)
        self.assertIn('"/api/onboarding/analytics"', runner)
        self.assertIn("Home Assistant onboarding remains incomplete", runner)
        self.assertIn('"setup_type": "simple"', runner)
        self.assertIn('"setup_type": "complete"', runner)
        self.assertNotIn('expect_step(result, "compact_room")', runner)
        self.assertIn("start_options_flow", runner)
        self.assertIn("probe_choice_matrix", runner)
        self.assertIn("assert_choice_contract", runner)
        self.assertIn("probe_invalid_wizard_inputs", runner)
        self.assertIn("assert_live_wizard_coverage", runner)
        self.assertIn("assert_existing_room_night_transition", runner)
        self.assertIn("assert_existing_room_schedule_transition", runner)
        self.assertIn("assert_existing_cover_limit_transition", runner)
        self.assertIn("LIVE_WIZARD_TRANSITIONS", runner)
        self.assertIn("/api/config/config_entries/entry/{entry_id}/reload", runner)
        self.assertIn("create_advanced_entry", runner)
        self.assertIn("run_upgrade_bootstrap", runner)
        self.assertIn("legacy_compatible=True", runner)
        self.assertIn('saved_state.get("upgrade_baseline")', runner)
        self.assertIn("entity IDs disappeared during upgrade", runner)
        self.assertIn('--bootstrap-mode "${BOOTSTRAP_MODE}"', shell)
        self.assertIn("wait_for_config_entries.py", shell)
        self.assertIn("run_interaction_matrix", runner)
        self.assertIn('"set_entry_enabled"', runner)
        self.assertNotIn('/unload"', runner)
        self.assertIn('item.get("state") == "unavailable"', runner)
        self.assertIn('sector.get("confirmation_state")', runner)
        self.assertNotIn('sector.get("source_valid")', runner)
        self.assertIn("wait_for_entry_removed", runner)
        self.assertNotIn("check_registry.py", shell)
        self.assertIn("registry_snapshot?return_response", runner)
        self.assertIn('registry_response.get("service_response")', runner)
        self.assertIn('registry_result["stale_devices"]', runner)
        self.assertIn("live HA registries", runner)

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
        self.assertIn("HA_E2E_RUN_UI", ui)
        self.assertIn("scripts/ha_e2e/run_lab.sh", ui)
        playwright = (ROOT / "e2e" / "ui" / "playwright.config.js").read_text(
            encoding="utf-8"
        )
        browser = (ROOT / "e2e" / "ui" / "card.spec.js").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("webServer", playwright)
        self.assertIn("HA_E2E_BASE_URL", playwright)
        self.assertIn("workers: 1", playwright)
        self.assertIn("/config/integrations/dashboard/add", browser)
        self.assertIn('getByRole("dialog")', browser)
        self.assertNotIn("ha-dialog:visible", browser)
        self.assertIn("Do you want to set up Smart Shading?", browser)
        self.assertIn('name: "OK"', browser)
        self.assertIn('getByRole("textbox", {', browser)
        self.assertIn('name: "Username"', browser)
        self.assertIn('name: "Password"', browser)
        self.assertIn('username.waitFor({ state: "visible" })', browser)
        self.assertNotIn("username.isVisible()", browser)
        self.assertNotIn('input[name="username"]', browser)
        self.assertIn('smart_shading_layout === "compact"', browser)
        self.assertIn('smart_shading_layout === "detailed"', browser)
        self.assertNotIn("smart_shading_advanced_mode", browser)
        self.assertIn('type: "lovelace/resources/list"', browser)
        self.assertIn('type: "lovelace/resources/create"', browser)
        self.assertIn('res_type: "module"', browser)
        self.assertIn('type: "lovelace/dashboards/list"', browser)
        self.assertIn('type: "lovelace/dashboards/create"', browser)
        self.assertIn("url_path: dashboardPath", browser)
        self.assertIn('page.goto("/smart-shading-e2e/binding")', browser)
        self.assertNotIn('page.goto("/home/', browser)
        self.assertNotIn('page.goto("/lovelace/', browser)
        self.assertIn('type: "lovelace/config/save"', browser)
        self.assertIn('type: "custom:smart-shading-card"', browser)
        self.assertIn("home-assistant:beta", nightly)
        self.assertNotIn("continue-on-error", nightly)
        self.assertIn("workflow_call:", nightly)
        self.assertIn("pull_request:", nightly)
        self.assertIn("github.event.pull_request.head.sha", nightly)
        self.assertIn("github.sha", nightly)
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
        self.assertIn("uses: ./.github/workflows/ha-upgrade-e2e.yml", release)
        self.assertIn("uses: ./.github/workflows/ha-nightly.yml", release)
        self.assertIn(
            "needs: [ha-e2e, ha-ui-e2e, ha-upgrade-e2e, ha-matrix-e2e]",
            release,
        )
        self.assertIn("uses: ./.github/workflows/ha-hacs-e2e.yml", release)
        self.assertIn("needs: release", release)

    def test_release_preparation_does_not_auto_close_delivery_issues(self):
        workflow = (
            ROOT / ".github" / "workflows" / "prepare-release.yml"
        ).read_text(encoding="utf-8")
        self.assertNotIn("Implements #19", workflow)
        self.assertIn("does not automatically close a delivery issue", workflow)
        self.assertIn("passes HACS qualification", workflow)

    def test_hacs_qualification_is_hosted_and_runs_the_public_tag_in_real_ha(self):
        workflow = (
            ROOT / ".github" / "workflows" / "ha-hacs-e2e.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("runs-on: ubuntu-latest", workflow)
        self.assertNotIn("runs-on: [self-hosted", workflow)
        self.assertIn("hacs/action@", workflow)
        self.assertIn("check_hacs_release.py", workflow)
        self.assertIn("HA_E2E_RELEASE_ARCHIVE", workflow)
        self.assertIn("scripts/ha_e2e/run_lab.sh", workflow)
        self.assertNotIn("ref: ${{ inputs.tag }}", workflow)
        self.assertNotIn("HA_PERSISTENT_", workflow)

    def test_wizard_coverage_contract_owns_every_customer_surface(self):
        coverage = json.loads(
            (LAB / "scenarios" / "wizard_coverage.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertGreaterEqual(len(coverage["all_surfaces"]), 35)
        self.assertEqual(len(coverage["live_transitions"]), 4)
        self.assertEqual(
            coverage["boolean_field_contract"]["night_enabled"],
            "real-ha-transition",
        )
        self.assertTrue(
            {
                "protected_zones_hub",
                "add_protected_zone",
                "manage_protected_zone",
                "delete_protected_zone",
            }.issubset(coverage["all_surfaces"])
        )
        self.assertEqual(
            coverage["boolean_field_contract"]["confirm_delete_protected_zone"],
            "validation-unit",
        )
        self.assertEqual(
            coverage["boolean_field_contract"]["target_verification_enabled"],
            "validation-unit",
        )
        self.assertEqual(
            coverage["boolean_field_contract"]["allow_automatic_reverse"],
            "validation-unit",
        )
        self.assertEqual(
            coverage["boolean_field_contract"]["safety_bypasses_stagger"],
            "validation-unit",
        )
        self.assertEqual(
            set(coverage["choice_contract"]["feedback_quality"]),
            {"trusted", "intermediate", "end_positions", "none"},
        )
        self.assertEqual(
            set(coverage["choice_contract"]["stagger_scope"]),
            {"room", "house"},
        )
        self.assertEqual(
            set(coverage["choice_contract"]["opening_order"]),
            {"height_then_tilt", "tilt_then_height"},
        )
        self.assertEqual(
            set(coverage["choice_contract"]["profile"]),
            {
                "venetian", "roller_shutter", "exterior_screen", "curtain",
                "vertical_blind", "awning", "binary_cover",
            },
        )
        checker = (
            ROOT / "scripts" / "ha_e2e" / "check_wizard_coverage.py"
        ).read_text(encoding="utf-8")
        self.assertIn("Flow surfaces missing E2E ownership", checker)
        self.assertIn(
            "Boolean wizard fields missing an acceptance-test owner", checker
        )

    def test_upgrade_lab_installs_previous_tag_before_candidate(self):
        workflow = (
            ROOT / ".github" / "workflows" / "ha-upgrade-e2e.yml"
        ).read_text(encoding="utf-8")
        selector = (
            ROOT / "scripts" / "ha_e2e" / "select_upgrade_baseline.py"
        ).read_text(encoding="utf-8")
        shell = (ROOT / "scripts" / "ha_e2e" / "run_lab.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("HA_E2E_UPGRADE_FROM_REF", workflow)
        self.assertIn("pull_request:", workflow)
        self.assertIn("select_upgrade_baseline.py", workflow)
        self.assertIn("newest stable release tag", workflow)
        self.assertIn("STABLE_TAG", selector)
        self.assertIn("excluding all prereleases", selector)
        self.assertIn("git archive", shell)
        self.assertIn("manifest-before-upgrade.json", shell)
        self.assertIn("manifest-after-upgrade.json", shell)


if __name__ == "__main__":
    unittest.main()
