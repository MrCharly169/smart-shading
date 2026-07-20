from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).parents[1]
COMP = ROOT / "custom_components" / "smart_shading"
FRONTEND = COMP / "frontend"

spec = importlib.util.spec_from_file_location("smart_shading_const", COMP / "const.py")
const = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(const)


class PackageTests(unittest.TestCase):
    def test_python_sources_parse(self):
        for path in COMP.glob("*.py"):
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_config_entry_schema_migrates_previous_v4_beta(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        migration = (COMP / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("VERSION = 11", flow)
        self.assertIn("if entry.version >= 11", migration)
        self.assertIn("version=11", migration)
        self.assertIn("if entry.version < 10", migration)
        self.assertIn("migrate_slat_config", migration)
        self.assertIn('cover.setdefault("short", "")', migration)
        self.assertIn('room.setdefault("normal_shading_temperature"', migration)

    def test_versions_and_resources_match(self):
        manifest = json.loads((COMP / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], const.VERSION)
        self.assertEqual(manifest["name"], "Smart Shading")
        self.assertEqual(const.CARD_RESOURCE, "/smart_shading/shading.js")
        card = (FRONTEND / "shading.js").read_text(encoding="utf-8")
        legacy = (FRONTEND / "smart-shading-card.js").read_text(encoding="utf-8")
        self.assertNotIn("const VERSION =", card)
        self.assertIn('import "./shading.js"', legacy)

    def test_direction_presets_cover_customer_choices(self):
        self.assertEqual(len(const.DIRECTION_OPTIONS), 9)
        self.assertEqual(const.DIRECTION_PRESETS["south"]["azimuth_start"], 120.0)
        self.assertEqual(const.DIRECTION_PRESETS["south"]["azimuth_end"], 240.0)
        self.assertGreater(const.DIRECTION_PRESETS["north"]["azimuth_start"], const.DIRECTION_PRESETS["north"]["azimuth_end"])

    def test_venetian_profile_has_only_normal_and_heat_motion(self):
        profile = const.PROFILE_DEFAULTS[const.DEVICE_VENETIAN]
        self.assertEqual(profile["comfort_position"], 0.0)
        self.assertEqual(profile["solar_position"], 0.0)
        self.assertEqual(profile["heat_position"], 0.0)
        self.assertEqual(profile["heat_tilt"], 100.0)
        self.assertEqual(profile["night_position"], 0.0)
        self.assertEqual(profile["night_tilt"], 100.0)
        self.assertEqual(profile["open_tilt"], 0.0)
        self.assertEqual(profile["open_position"], 100.0)
        self.assertEqual(profile["safety_position"], 100.0)
        engine = (COMP / "engine.py").read_text(encoding="utf-8")
        self.assertIn("normal_shading_temperature", engine)
        self.assertIn("venetian_only", engine)
        self.assertIn('mode = MODE_SOLAR', engine)

    def test_venetian_numbers_hide_redundant_comfort_and_solar(self):
        number = (COMP / "number.py").read_text(encoding="utf-8")
        self.assertIn('NumberDefinition("normal_shading_temperature"', number)
        self.assertIn('if key in {"comfort_temperature", "solar_temperature"}', number)
        self.assertIn('return not venetian_only', number)

    def test_balanced_tilt_curve_uses_knx_closedness_semantics(self):
        curve = const.TILT_CURVE_PRESETS[const.TILT_PRESET_BALANCED]
        self.assertEqual(
            [(point["elevation"], point["tilt"]) for point in curve],
            [(10.0, 90.0), (20.0, 65.0), (40.0, 35.0), (60.0, 15.0)],
        )

    def test_all_cover_profiles_exist(self):
        self.assertEqual(set(const.DEVICE_TYPES), {
            "venetian", "roller_shutter", "exterior_screen", "curtain",
            "vertical_blind", "awning", "binary_cover",
        })

    def test_sun_requirement_is_checked_and_reported(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        engine = (COMP / "engine.py").read_text(encoding="utf-8")
        self.assertIn('self.hass.states.get("sun.sun")', flow)
        self.assertIn('errors["base"] = "sun_unavailable"', flow)
        self.assertIn("_async_sync_sun_requirement_notification", engine)

    def test_default_pause_is_next_sunrise(self):
        self.assertEqual(const.ROOM_DEFAULTS["default_pause_mode"], const.PAUSE_NEXT_SUNRISE)
        engine = (COMP / "engine.py").read_text(encoding="utf-8")
        self.assertIn('attribute = "next_rising" if mode == PAUSE_NEXT_SUNRISE', engine)
        self.assertIn("async_pause_default", engine)

    def test_diagnostic_logging_is_separate_from_advanced_mode(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        select = (COMP / "select.py").read_text(encoding="utf-8")
        engine = (COMP / "engine.py").read_text(encoding="utf-8")
        self.assertIn("CONF_ADVANCED_MODE", flow)
        self.assertIn("CONF_DIAGNOSTIC_LEVEL", flow)
        self.assertIn("DiagnosticLoggingSelect", select)
        self.assertIn("diagnostic_journal", engine)
        self.assertIn("DIAGNOSTIC_FULL", engine)

    def test_full_diagnostics_logs_routine_suppressions_only_in_full_mode(self):
        engine = (COMP / "engine.py").read_text(encoding="utf-8")
        self.assertIn("routine_reasons", engine)
        self.assertIn('full=all(reason in routine_reasons for reason in suppressions)', engine)

    def test_multiple_cover_selector_then_names_each_cover(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        self.assertIn('"cover", multiple=True', flow)
        self.assertIn("async_step_name_selected_cover", flow)
        self.assertIn('vol.Required("name"', flow)
        self.assertIn('vol.Required("short"', flow)
        self.assertIn("_pending_cover_entities", flow)

    def test_sector_identity_is_explicit(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        self.assertIn("async_step_sector_identity", flow)
        self.assertIn('step_id="sector_identity"', flow)
        sensor = (COMP / "sensor.py").read_text(encoding="utf-8")
        self.assertIn("SectorStatusSensor", sensor)
        self.assertIn("sector_statuses", sensor)

    def test_sector_control_entities_include_sector_name(self):
        switch = (COMP / "switch.py").read_text(encoding="utf-8")
        select = (COMP / "select.py").read_text(encoding="utf-8")
        binary = (COMP / "binary_sensor.py").read_text(encoding="utf-8")
        self.assertIn("sector.get('name'", switch)
        self.assertIn("sector.get('name'", select)
        self.assertIn("sector.get('name'", binary)

    def test_translation_files_cover_every_flow(self):
        required_steps = {
            "user", "global_settings", "add_room", "room_pause_setup",
            "room_pause_sun_setup", "room_pause_duration_setup", "room_schedule",
            "room_schedule_custom", "sector_direction", "sector_identity", "sector_lux",
            "sector_lux_custom", "add_layer", "layer_tilt_profile", "layer_tilt_custom",
            "add_covers", "name_selected_cover", "after_room", "init", "room_actions",
            "sector_actions", "layer_actions", "edit_cover", "edit_room_pause",
            "room_advanced_setup", "edit_sector_customer",
        }
        self.assertFalse((COMP / "strings.json").exists())
        for language in ("de", "en"):
            data = json.loads((COMP / "translations" / f"{language}.json").read_text(encoding="utf-8"))
            for section in ("config", "options"):
                steps = data[section]["step"]
                self.assertTrue(required_steps.issubset(steps), f"{language}/{section}")
                for step in required_steps:
                    self.assertTrue(steps[step].get("title"), f"{language}/{section}/{step}")
                advanced = steps["room_advanced_setup"]["data"]
                self.assertIn("normal_shading_temperature", advanced)

    def test_translation_placeholders_are_intentional(self):
        allowed = {"current", "count", "entity_name"}
        pattern = re.compile(r"\{([a-zA-Z0-9_]+)\}")
        for language in ("de", "en"):
            data = json.loads((COMP / "translations" / f"{language}.json").read_text(encoding="utf-8"))
            found = set(pattern.findall(json.dumps(data, ensure_ascii=False)))
            self.assertTrue(found.issubset(allowed), (language, found))

    def test_customer_text_is_generic(self):
        paths = [
            COMP / "translations" / "de.json", COMP / "translations" / "en.json",
            ROOT / "README_DE.md", ROOT / "INSTALL_CHECKLIST_DE.md",
        ]
        text = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
        for banned in ("terrace door", "terrassentür", "terrasse doors", "haus2", "livingarea"):
            self.assertNotIn(banned, text)

    def test_card_is_responsive_and_clips_no_side_content(self):
        card = (FRONTEND / "shading.js").read_text(encoding="utf-8")
        self.assertIn(":host{display:block;width:100%;max-width:100%;min-width:0", card)
        self.assertIn("grid-template-columns:repeat(auto-fit", card)
        self.assertIn("text-overflow:ellipsis", card)
        self.assertIn("max-width:100%", card)

    def test_card_uses_compact_reference_structure(self):
        card = (FRONTEND / "shading.js").read_text(encoding="utf-8")
        for token in (".chips", ".sunbox", ".sectors", ".cover-row", ".sector-bar", ".sun-dot"):
            self.assertIn(token, card)
        self.assertNotIn("position_already_correct</", card)

    def test_advanced_view_is_document_level_dialog_not_inline_details(self):
        card = (FRONTEND / "shading.js").read_text(encoding="utf-8")
        self.assertIn("class SmartShadingV4Dialog", card)
        self.assertIn("document.body.appendChild(this)", card)
        self.assertIn("position:fixed;inset:0", card)
        self.assertIn("aria-modal=\"true\"", card)
        self.assertNotIn("<details", card)

    def test_card_editor_initializes_config_and_emits_changes(self):
        card = (FRONTEND / "shading.js").read_text(encoding="utf-8")
        editor = card[card.index("class SmartShadingV4CardEditor"):]
        self.assertIn("this._config = {", editor)
        self.assertIn("setConfig(config = {})", editor)
        self.assertNotIn("this.config", card)
        self.assertIn('new CustomEvent("config-changed"', editor)

    def test_card_never_uses_raw_entity_id_as_display_fallback(self):
        card = (FRONTEND / "shading.js").read_text(encoding="utf-8")
        self.assertIn("isRawEntityId", card)
        self.assertIn("cleanDisplayName", card)
        self.assertIn('const fallback = `${L.cover} ${index + 1}`', card)
        self.assertNotIn("configuredName || entityId", card)
        self.assertNotIn("friendly || entityId", card)

    def test_card_defensively_handles_missing_values(self):
        card = (FRONTEND / "shading.js").read_text(encoding="utf-8")
        self.assertIn('String(value ?? "")', card)
        self.assertIn("if (!roomState)", card)
        self.assertIn("No covers assigned", card)
        self.assertNotIn("this.config", card)

    def test_card_notification_uses_stable_id_and_current_card(self):
        engine = (COMP / "engine.py").read_text(encoding="utf-8")
        self.assertIn("persistent_notification", engine)
        self.assertIn("smart_shading_card_", engine)
        self.assertIn("type: custom:smart-shading-card", engine)
        self.assertIn("advanced_mode: false", engine)

    def test_canonical_domain_and_card_names(self):
        manifest = json.loads((COMP / "manifest.json").read_text(encoding="utf-8"))
        card = (FRONTEND / "shading.js").read_text(encoding="utf-8")
        self.assertEqual(COMP.name, "smart_shading")
        self.assertEqual(manifest["domain"], "smart_shading")
        self.assertEqual(const.DOMAIN, "smart_shading")
        self.assertEqual('/smart_shading/shading.js', const.CARD_RESOURCE)
        self.assertIn('customElements.define("smart-shading-card"', card)
        self.assertNotIn("smart_shading_v3", card)
        self.assertNotIn("smart-shading-v3", card)

    def test_compact_sector_always_gets_id_and_custom_is_explicit(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        self.assertIn("finalize_sector_identity", flow)
        self.assertIn("id_factory=_new_id", flow)
        self.assertIn("needs_custom_sun_settings", flow)
        self.assertNotIn('if preset and self._pending_sector.get("lux_sensor")', flow)

    def test_safety_precedes_pause_and_disable(self):
        engine = (COMP / "engine.py").read_text(encoding="utf-8")
        safety = engine.index("# Safety has the highest priority")
        disabled = engine.index("if not runtime.enabled:", safety)
        paused = engine.index("pause_active = self._pause_active(runtime, now)", safety)
        self.assertLess(safety, disabled)
        self.assertLess(safety, paused)
        self.assertIn("if window_unsafe and mode != MODE_SAFETY", engine)

    def test_reopen_threshold_is_implemented_for_venetian(self):
        engine = (COMP / "engine.py").read_text(encoding="utf-8")
        self.assertIn("if runtime.shading_active and indoor < reopen_temperature", engine)
        self.assertIn("elif not runtime.shading_active and indoor >= normal_shading_temperature", engine)

    def test_daily_state_survives_same_day_restart(self):
        engine = (COMP / "engine.py").read_text(encoding="utf-8")
        storage = (COMP / "storage.py").read_text(encoding="utf-8")
        self.assertIn("self._day_key = self.store.day_key()", engine)
        self.assertIn("async_set_day_key", engine)
        self.assertIn('"day_key": None', storage)

    def test_compact_customer_wizard(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        for step in (
            "compact_room",
            "compact_sector",
            "compact_layer",
            "compact_cover_details",
        ):
            self.assertIn(f"async_step_{step}", flow)
        self.assertIn('vol.Optional("window")', flow)
        self.assertIn('multiple=True', flow)

    def test_window_return_to_automation_is_defaulted_and_translated(self):
        self.assertTrue(const.DEFAULT_WINDOW_RETURNS_TO_AUTOMATION)
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        migration = (COMP / "__init__.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(flow.count("CONF_WINDOW_RETURNS_TO_AUTOMATION"), 4)
        self.assertIn("DEFAULT_WINDOW_RETURNS_TO_AUTOMATION", migration)
        for language in ("de", "en"):
            data = json.loads(
                (COMP / "translations" / f"{language}.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn(
                "window_returns_to_automation",
                data["config"]["step"]["compact_cover_details"]["data"],
            )
            for section in ("config", "options"):
                step = data[section]["step"]["edit_cover"]
                self.assertIn("window_returns_to_automation", step["data"])
                self.assertIn(
                    "window_returns_to_automation", step["data_description"]
                )

    def test_sun_sensitivity_is_inverse_threshold(self):
        self.assertGreater(
            const.SUN_PRESETS["low"]["sun_on_lux"],
            const.SUN_PRESETS["medium"]["sun_on_lux"],
        )
        self.assertGreater(
            const.SUN_PRESETS["medium"]["sun_on_lux"],
            const.SUN_PRESETS["high"]["sun_on_lux"],
        )
    def test_engine_imports_default_sun_preset(self):
        engine = (COMP / "engine.py").read_text(encoding="utf-8")
        self.assertIn("PRESET_MEDIUM", engine)
        import_block = engine[engine.index("from .const import ("):engine.index(")\nfrom .logic")]
        self.assertIn("PRESET_MEDIUM", import_block)

    def test_default_evaluation_interval_is_twenty_minutes(self):
        self.assertEqual(const.DEFAULT_EVALUATION_INTERVAL, 1200)
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        self.assertIn('"evaluation_interval_minutes", default=20', flow)
        self.assertIn('interval_minutes * 60', flow)

    def test_card_footer_icons_are_compact(self):
        card = (FRONTEND / "shading.js").read_text(encoding="utf-8")
        self.assertIn('.round{width:32px;height:32px', card)
        self.assertIn('.round ha-icon{width:15px;height:15px}', card)
        for token in ("--mdc-icon-size:12px", "--mdc-icon-size:13px", "--mdc-icon-size:14px", "--mdc-icon-size:15px"):
            self.assertIn(token, card)

    def test_card_routes_button_and_switch_actions(self):
        card = (FRONTEND / "shading.js").read_text(encoding="utf-8")
        self.assertIn('domain === "button" ? "press" : domain === "switch" ? "toggle"', card)
        self.assertNotIn('callService("button", "press", { entity_id: entityId })', card)

    def test_local_pause_variable_is_defined_before_use(self):
        card = (FRONTEND / "shading.js").read_text(encoding="utf-8")
        definition = card.index("const locallyPaused = Boolean(localPause.active)")
        use = card.index("roomPaused || locallyPaused", definition)
        self.assertLess(definition, use)

    def test_numeric_states_do_not_silently_fall_back_to_zero(self):
        engine = (COMP / "engine.py").read_text(encoding="utf-8")
        logic = (COMP / "logic.py").read_text(encoding="utf-8")
        self.assertIn("parse_numeric_value", engine)
        self.assertIn("def parse_numeric_value", logic)
        self.assertIn("return None", logic)
        self.assertNotIn("def _state_float", engine)

    def test_normal_state_changes_are_deferred_to_twenty_minute_interval(self):
        engine = (COMP / "engine.py").read_text(encoding="utf-8")
        self.assertIn("state_change_deferred", engine)
        self.assertIn("sun_presence_transition_deferred_to_interval", engine)
        self.assertIn('await self.async_evaluate_all(f"critical_state:{entity_id}")', engine)

    def test_startup_reconciles_existing_manual_locks(self):
        engine = (COMP / "engine.py").read_text(encoding="utf-8")
        self.assertIn("await self._async_sync_configured_locks()", engine)
        self.assertIn("manual_lock_entity", engine)


    def test_hacs_uses_only_published_versions(self):
        hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
        self.assertTrue(hacs["hide_default_branch"])
        self.assertFalse(hacs["content_in_root"])

    def test_release_workflow_separates_beta_and_stable(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("channel:", workflow)
        self.assertIn("- beta", workflow)
        self.assertIn("- stable", workflow)
        self.assertIn("validate_release_channel.py", workflow)
        self.assertIn("prerelease: ${{ inputs.channel == 'beta' }}", workflow)
        self.assertIn("make_latest: ${{ inputs.channel == 'stable' }}", workflow)
        self.assertIn("release_changelog.py notes", workflow)
        self.assertIn("body_path: dist/release-notes.md", workflow)
        self.assertNotIn("generate_release_notes:", workflow)
        self.assertNotIn("push:\n    tags:", workflow)

    def test_prepare_release_workflow_creates_only_a_reviewable_draft_pr(self):
        workflow = (
            ROOT / ".github" / "workflows" / "prepare-release.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("inputs.channel == 'stable' && 'main' || 'develop'", workflow)
        self.assertIn("pull-requests: write", workflow)
        self.assertIn("actions: write", workflow)
        self.assertIn("release_changelog.py prepare", workflow)
        self.assertIn('--source-branch "develop"', workflow)
        self.assertIn('TARGET_BRANCH="main"', workflow)
        self.assertIn('git switch -c "$RELEASE_BRANCH"', workflow)
        self.assertIn("git merge --no-commit --no-ff origin/develop", workflow)
        self.assertIn('FILE" != ".github/workflows/release.yml"', workflow)
        self.assertIn("git merge --abort", workflow)
        self.assertNotIn("git merge -X theirs", workflow)
        self.assertIn("gh pr create", workflow)
        self.assertIn('--base "$TARGET_BRANCH"', workflow)
        self.assertIn("--draft", workflow)
        self.assertIn("gh workflow run validate.yml", workflow)
        self.assertNotIn("gh pr merge", workflow)
        self.assertNotIn("gh release create", workflow)

        create_branch = workflow.index('git switch -c "$RELEASE_BRANCH"')
        prepare_changelog = workflow.index("release_changelog.py prepare")
        run_tests = workflow.index("python -m unittest discover")
        push_branch = workflow.index('git push --set-upstream origin "$RELEASE_BRANCH"')
        self.assertLess(create_branch, prepare_changelog)
        self.assertLess(prepare_changelog, run_tests)
        self.assertLess(run_tests, push_branch)



if __name__ == "__main__":
    unittest.main()
