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
        self.assertIn("VERSION = 13", flow)
        self.assertIn("if entry.version >= 13", migration)
        self.assertIn("version=13", migration)
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

    def test_easy_and_advanced_have_distinct_runtime_and_card_contracts(self):
        engine = (COMP / "engine.py").read_text(encoding="utf-8")
        card = (FRONTEND / "shading.js").read_text(encoding="utf-8")
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        self.assertIn("async def _evaluate_easy_room", engine)
        self.assertIn("Geometry is always mandatory", engine)
        self.assertIn("Binary Sun Presence, Lux and weather", engine)
        self.assertIn("attrs.smart_shading_advanced_mode === true", card)
        self.assertNotIn("_roomSelector(roomState)", card)
        self.assertNotIn('data-toggle="advanced_mode"', card)
        self.assertIn('step_id="room_setup"', flow)
        self.assertIn('"async_step_manage_"', flow)
        self.assertIn("build_main_room_routes", flow)
        self.assertIn("build_room_routes", flow)
        self.assertIn("async_step_room_hub", flow)
        self.assertIn('"manage_room"', flow)
        self.assertIn('"manage_sector"', flow)
        self.assertIn('"manage_layer"', flow)
        self.assertIn('"manage_cover"', flow)
        self.assertIn("DEFAULT_EXTERNAL_MOVEMENT_DETECTION = False", (COMP / "const.py").read_text(encoding="utf-8"))

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

    def test_english_and_german_translation_structures_match(self):
        translations = {}
        for language in ("de", "en"):
            path = COMP / "translations" / f"{language}.json"
            duplicates = []

            def reject_duplicates(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        duplicates.append(key)
                    result[key] = value
                return result

            translations[language] = json.loads(
                path.read_text(encoding="utf-8"),
                object_pairs_hook=reject_duplicates,
            )
            self.assertFalse(duplicates, (language, duplicates))

        def key_paths(value, prefix=()):
            paths = set()
            if isinstance(value, dict):
                for key, child in value.items():
                    path = (*prefix, key)
                    paths.add(path)
                    paths.update(key_paths(child, path))
            return paths

        self.assertEqual(
            key_paths(translations["en"]),
            key_paths(translations["de"]),
        )

    def test_primary_setup_fields_have_customer_help_in_both_languages(self):
        required = {
            ("config", "room_setup", "room_and_covers"): {
                "name", "direction", "group_name", "profile", "cover_entities"
            },
            ("config", "room_setup", "advanced_conditions"): {
                "indoor_temperature", "outdoor_temperature", "outdoor_minimum",
                "safety_blockers", "schedule_profile", "default_pause_mode",
                "heat_during_pause", "external_movement_detection",
            },
            ("options", "add_room", "room_and_covers"): {
                "name", "direction", "group_name", "profile", "cover_entities"
            },
            ("options", "add_room", "advanced_conditions"): {
                "indoor_temperature", "outdoor_temperature", "outdoor_minimum",
                "safety_blockers", "external_movement_detection",
            },
        }
        for language in ("de", "en"):
            data = json.loads(
                (COMP / "translations" / f"{language}.json").read_text(
                    encoding="utf-8"
                )
            )
            for (section, step, group), fields in required.items():
                help_text = data[section]["step"][step]["sections"][group][
                    "data_description"
                ]
                self.assertTrue(fields.issubset(help_text), (language, step, group))
            for section in ("config", "options"):
                help_text = data[section]["step"]["global_settings"][
                    "data_description"
                ]
                self.assertIn("sun_entity", help_text)
                self.assertIn("unknown_feedback_policy", help_text)

    def test_reachable_options_forms_have_safe_optional_entities(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        self.assertIn('vol.Required("room_and_covers"): section(', flow)
        self.assertIn('vol.Required("sun_control"): section(', flow)
        self.assertIn("CONF_SUN_PRESENCE_ENTITY", flow)
        self.assertIn("CONF_WEATHER_ENTITY", flow)
        self.assertIn("CONF_EASY_TEMPERATURE_GATE", flow)
        options = flow[flow.index("class SmartShadingOptionsFlow"):]
        for step in ("manage_room", "manage_sector", "manage_cover"):
            start = options.index(f"async def async_step_{step}")
            self.assertIn("_optional_marker", options[start:start + 14000])
        for language in ("de", "en"):
            data = json.loads(
                (COMP / "translations" / f"{language}.json").read_text(
                    encoding="utf-8"
                )
            )
            room_setup = data["config"]["step"]["room_setup"]
            add_room = data["options"]["step"]["add_room"]
            for step in (room_setup, add_room):
                self.assertEqual(
                    set(step["sections"]),
                    {
                        "room_and_covers",
                        "sun_control",
                        "optional_improvements",
                        "advanced_conditions",
                    },
                )
                sun_data = step["sections"]["sun_control"]["data"]
                self.assertIn("lux_sensor", sun_data)
                self.assertIn("sun_presence_entity", sun_data)
            self.assertIn(
                "choose_one_sun_confirmation", data["config"]["error"]
            )
            self.assertIn(
                "choose_one_sun_confirmation", data["options"]["error"]
            )

    def test_translation_placeholders_are_intentional(self):
        allowed = {
            "current", "count", "entity_name", "room_name", "sector_name",
            "group_name", "cover_name",
        }
        pattern = re.compile(r"\{([a-zA-Z0-9_]+)\}")
        for language in ("de", "en"):
            data = json.loads((COMP / "translations" / f"{language}.json").read_text(encoding="utf-8"))
            found = set(pattern.findall(json.dumps(data, ensure_ascii=False)))
            self.assertTrue(found.issubset(allowed), (language, found))

    def test_customer_text_is_generic(self):
        paths = [
            COMP / "translations" / "de.json", COMP / "translations" / "en.json",
            ROOT / "README.md", ROOT / "docs" / "FAQ.md",
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
        self.assertIn("const existingDialog", card)
        self.assertIn("const contentChanged = !existingDialog || this._mainHtml !== mainHtml", card)
        self.assertIn("if (contentChanged)", card)
        self.assertIn("this._contentWriteCount += 1", card)
        self.assertIn("disconnectedCallback()", card)
        self.assertIn("overscroll-behavior:contain", card)
        self.assertIn("dataset.renderCount", card)
        self.assertNotIn("<details", card)

    def test_options_editor_keeps_root_menu_room_only(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        options = flow[flow.index("class SmartShadingOptionsFlow"):]
        init = options[
            options.index("async def async_step_init"):
            options.index("async def async_step_room_hub")
        ]
        self.assertIn("def _add_option_route", options)
        self.assertIn("build_main_room_routes", init)
        self.assertNotIn("for sector in", init)
        self.assertNotIn("for layer in", init)
        self.assertNotIn("for cover_index", init)

        hub = options[
            options.index("async def async_step_room_hub"):
            options.index("async def async_step_manage_room")
        ]
        self.assertIn("build_room_routes", hub)
        self.assertIn('step_id="room_hub"', hub)
        for action in (
            "manage_room", "add_sector_flat", "manage_sector",
            "add_layer_flat", "manage_layer", "add_covers_flat",
            "manage_cover",
        ):
            self.assertIn(f'"{action}"', options)
            self.assertIn(f"async_step_{action}", options)
        self.assertIn('return self.async_show_menu(step_id="init"', options)

    def test_new_options_forms_are_fully_translated_in_en_and_de(self):
        required = {
            "room_hub",
            "manage_room", "add_sector_flat", "manage_sector",
            "add_layer_flat", "manage_layer", "add_covers_flat",
            "manage_cover", "sector_hub", "group_hub", "cover_hub",
            "manage_room_details", "manage_room_maintenance",
            "manage_automation", "manage_night", "manage_pause",
            "manage_conditions", "choose_sector_for_group",
            "choose_group_for_covers",
        }
        for language in ("de", "en"):
            data = json.loads(
                (COMP / "translations" / f"{language}.json").read_text(
                    encoding="utf-8"
                )
            )
            steps = data["options"]["step"]
            self.assertTrue(required.issubset(steps), language)
            for step in required:
                self.assertTrue(steps[step].get("title"), (language, step))
            for error in (
                "cannot_delete_last_sector",
                "cannot_delete_last_layer",
                "cannot_delete_last_cover",
            ):
                self.assertIn(error, data["options"]["error"])

    def test_initial_setup_offers_complete_features_in_safe_order(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        cover = flow.index("async def async_step_compact_cover_details")
        night = flow.index("async def async_step_initial_night_setup")
        pause = flow.index("async def async_step_initial_pause_setup")
        conditions = flow.index("async def async_step_initial_conditions_setup")
        finish = flow.index("async def async_step_finish", conditions)
        self.assertLess(cover, night)
        self.assertLess(night, pause)
        self.assertLess(pause, conditions)
        self.assertLess(conditions, finish)
        initial_cover = flow[cover:night]
        for field in ("lock", "window", "invert_position", "invert_tilt"):
            self.assertIn(f'"{field}"', initial_cover)
        room_setup = flow[
            flow.index("async def async_step_room_setup"):
            flow.index("async def async_step_add_room", flow.index("async def async_step_room_setup"))
        ]
        self.assertNotIn('vol.Required("default_pause_mode"', room_setup)
        self.assertIn("async_step_compact_cover_details", room_setup)

    def test_customer_navigation_uses_task_categories(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        options = flow[flow.index("class SmartShadingOptionsFlow"):]
        hub = options[
            options.index("async def async_step_room_hub"):
            options.index("async def async_step_manage_room_details")
        ]
        for builder in (
            "build_room_routes", "build_sector_routes", "build_group_routes",
            "build_cover_routes",
        ):
            self.assertIn(builder, options)
        self.assertNotIn("for sector in room.get", hub)
        self.assertIn("full=self.advanced_mode", hub)

    def test_external_sun_confirmation_is_unambiguous(self):
        for language, expected in (
            ("en", "External sun confirmation (optional)"),
            ("de", "Externe Sonnenbestätigung (optional)"),
        ):
            data = json.loads(
                (COMP / "translations" / f"{language}.json").read_text(
                    encoding="utf-8"
                )
            )
            for section, step in (("config", "room_setup"), ("options", "manage_sector")):
                groups = data[section]["step"][step].get("sections", {})
                sun = groups["sun_control" if step == "room_setup" else "sun_confirmation"]
                self.assertEqual(sun["data"]["sun_presence_entity"], expected)
                self.assertIn("Lux", sun["data_description"]["lux_sensor"])

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
        self.assertNotIn("advanced_mode: false", engine)

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
        easy = engine.index("if not self.advanced_mode:", engine.index("async def _evaluate_room"))
        self.assertLess(easy, safety)
        self.assertIn("if self.advanced_mode and window_unsafe", engine)

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

    def test_card_icons_use_centered_fixed_boxes(self):
        card = (FRONTEND / "shading.js").read_text(encoding="utf-8")
        self.assertIn('.round{width:36px;height:36px', card)
        self.assertIn('display:grid;place-items:center;align-content:center;justify-content:center', card)
        self.assertIn('.icon-box>ha-icon{display:grid;place-items:center', card)
        self.assertIn('button[data-close]{display:grid;place-items:center', card)
        for token in ("--icon-size:12px", "--icon-size:14px", "--icon-size:15px", "--icon-size:16px"):
            self.assertIn(token, card)

    def test_card_routes_button_and_switch_actions(self):
        card = (FRONTEND / "shading.js").read_text(encoding="utf-8")
        self.assertIn('domain === "button" ? "press" : domain === "switch" ? "toggle"', card)
        self.assertNotIn('callService("button", "press", { entity_id: entityId })', card)

    def test_easy_mode_exposes_no_evaluate_buttons(self):
        button = (COMP / "button.py").read_text(encoding="utf-8")
        easy_branch = button[button.index("if not engine.advanced_mode:"):]
        easy_branch = easy_branch[:easy_branch.index("entities = [EvaluateHouseButton")]
        self.assertIn("async_add_entities([])", easy_branch)
        self.assertNotIn("EvaluateRoomButton", easy_branch)

    def test_options_changes_reload_runtime_and_platform_entities(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        setup = (COMP / "__init__.py").read_text(encoding="utf-8")
        self.assertIn(
            "class SmartShadingOptionsFlow(_SmartShadingWizardMixin, OptionsFlowWithReload)",
            flow,
        )
        self.assertNotIn("entry.add_update_listener(_async_reload_entry)", setup)

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
