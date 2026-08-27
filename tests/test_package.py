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
    def test_card_reports_an_unavailable_selected_sun_source(self):
        card = (FRONTEND / "shading.js").read_text(encoding="utf-8")
        self.assertIn('unavailable: L.sourceUnavailable', card)
        self.assertIn('confirmationState === "unavailable"', card)

    def test_config_flow_uppercase_globals_are_bound(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        tree = ast.parse(flow)
        bound: set[str] = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bound.add(node.name)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                bound.update(
                    alias.asname or alias.name.split(".")[0]
                    for alias in node.names
                )
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                bound.update(
                    target.id for target in targets if isinstance(target, ast.Name)
                )
        loaded_constants = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id.upper() == node.id
            and not node.id.startswith("_")
        }
        self.assertEqual(loaded_constants - bound, set())

    def test_device_info_does_not_publish_relative_configuration_url(self):
        entity = (COMP / "entity.py").read_text(encoding="utf-8")
        self.assertNotIn('configuration_url="/config/', entity)

    def test_config_entry_removal_clears_owned_registry_records(self):
        setup = (COMP / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("er.async_entries_for_config_entry", setup)
        self.assertIn("entity_registry.async_remove", setup)
        self.assertIn("dr.async_entries_for_config_entry", setup)
        self.assertIn("identifier_prefix", setup)
        self.assertIn("device_registry.devices.values()", setup)
        self.assertIn("device_registry.async_remove_device", setup)

    def test_python_sources_parse(self):
        for path in COMP.glob("*.py"):
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_every_customer_form_error_has_an_english_and_german_message(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        tree = ast.parse(flow)
        codes = {
            node.value.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Subscript)
            and isinstance(node.targets[0].value, ast.Name)
            and node.targets[0].value.id == "errors"
            and isinstance(node.targets[0].slice, ast.Constant)
            and node.targets[0].slice.value == "base"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        }
        config_only = {
            "confirm_start_required",
            "sun_missing",
            "sun_unavailable",
        }
        for language in ("de", "en"):
            data = json.loads(
                (COMP / "translations" / f"{language}.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(codes.issubset(data["config"]["error"]), language)
            self.assertTrue(
                (codes - config_only).issubset(data["options"]["error"]),
                language,
            )

    def test_pause_and_sensor_number_bounds_have_one_contract(self):
        self.assertEqual(const.PAUSE_DURATION_MIN_HOURS, 0.5)
        self.assertEqual(const.PAUSE_DURATION_MAX_HOURS, 72.0)
        self.assertEqual(const.PAUSE_DURATION_STEP_HOURS, 0.5)
        self.assertEqual(const.OUTDOOR_MINIMUM_MIN_C, -20.0)
        self.assertEqual(const.OUTDOOR_MINIMUM_MAX_C, 40.0)
        self.assertEqual(const.IRRADIANCE_MINIMUM_MAX, 2000.0)

        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        number = (COMP / "number.py").read_text(encoding="utf-8")
        engine = (COMP / "engine.py").read_text(encoding="utf-8")
        for name in (
            "PAUSE_DURATION_MIN_HOURS",
            "PAUSE_DURATION_MAX_HOURS",
            "PAUSE_DURATION_STEP_HOURS",
            "OUTDOOR_MINIMUM_MIN_C",
            "OUTDOOR_MINIMUM_MAX_C",
            "IRRADIANCE_MINIMUM_MAX",
        ):
            self.assertIn(name, flow)
            self.assertIn(name, number)
        self.assertIn("_configured_pause_duration", engine)

    def test_temperature_controls_exist_only_with_a_room_sensor(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        number = (COMP / "number.py").read_text(encoding="utf-8")

        self.assertIn("has_indoor_temperature", flow)
        self.assertIn(
            'sections[vol.Required("temperature_settings")]', flow
        )
        self.assertIn("profile_target_keys", number)
        self.assertIn('indoor_temperature=bool(room.get("indoor_temperature"))', number)

    def test_outdoor_minimum_is_automatic_and_source_dependent(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        engine = (COMP / "engine.py").read_text(encoding="utf-8")
        self.assertNotIn("easy_temperature_gate", flow)
        self.assertNotIn('outdoor_temperature and "outdoor_minimum" not in values', flow)
        self.assertIn("async_step_configure_outdoor_temperature", flow)
        self.assertIn('step_id="configure_outdoor_temperature"', flow)
        self.assertIn('if not str(room.get("outdoor_temperature") or "").strip()', flow)
        self.assertIn("def _outdoor_temperature_condition", engine)
        self.assertNotIn("_easy_weather_confirmation", engine)

    def test_config_entry_schema_migrates_stable_v4_6_2_and_previous_betas(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        migration = (COMP / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("VERSION = 20", flow)
        self.assertIn("if entry.version >= 20", migration)
        self.assertIn("version=20", migration.replace(" ", ""))
        self.assertIn("result[CONF_SUN_ENTITY] = DEFAULT_SUN_ENTITY", migration)
        self.assertIn("v4.6.2 already used entry schema 15", migration)
        self.assertIn("locked_advanced_mode(raw_data, raw_options)", migration)
        self.assertIn("options = editable_options(effective) if raw_options else {}", migration)
        self.assertIn("if entry.version < 10", migration)
        self.assertIn("migrate_slat_config", migration)
        self.assertIn('cover.setdefault("short", "")', migration)
        self.assertIn('room.setdefault("normal_shading_temperature"', migration)
        self.assertIn('room.pop("easy_temperature_gate", None)', migration)
        self.assertIn('sector["sun_source"] = source', migration)
        self.assertIn('if source != "lux"', migration)
        self.assertIn("profile_supports_tilt", migration)

    def test_issue79_execution_defaults_are_advanced_only_and_freshness_is_opt_in(self):
        execution_keys = {
            "command_stagger_seconds",
            "stagger_scope",
            "safety_bypasses_stagger",
            "target_verification_enabled",
            "verification_retries",
            "movement_seconds",
            "settling_seconds",
            "source_stale_seconds",
        }
        self.assertEqual(const.DEFAULT_SOURCE_STALE_SECONDS, 0.0)
        self.assertEqual(const.DEFAULT_STAGGER_SCOPE, "room")
        self.assertTrue(const.DEFAULT_SAFETY_BYPASSES_STAGGER)
        self.assertFalse(const.DEFAULT_ALLOW_AUTOMATIC_REVERSE)
        self.assertEqual(const.DEFAULT_OPENING_ORDER, "height_then_tilt")
        self.assertTrue(
            execution_keys.issubset(const.ADVANCED_EXECUTION_ROOM_DEFAULTS)
        )
        self.assertFalse(execution_keys & set(const.ROOM_DEFAULTS))

        migration = (COMP / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("for key in ADVANCED_EXECUTION_ROOM_DEFAULTS", migration)
        self.assertIn('cover.pop("feedback_quality", None)', migration)
        self.assertIn('cover.pop("verify_target", None)', migration)
        self.assertIn('cover.pop("allow_automatic_reverse", None)', migration)
        self.assertIn('layer.pop("opening_order", None)', migration)

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

    def test_curtain_heat_position_has_no_redundant_enable_switch(self):
        curtain = const.PROFILE_DEFAULTS[const.DEVICE_CURTAIN]
        self.assertNotIn("heat_close_enabled", curtain)
        self.assertEqual(curtain["heat_position"], curtain["solar_position"])
        self.assertEqual(curtain["open_position"], 100.0)
        self.assertEqual(curtain["comfort_position"], 50.0)
        self.assertEqual(curtain["solar_position"], 0.0)
        self.assertEqual(curtain["heat_position"], 0.0)
        self.assertEqual(curtain["night_position"], 0.0)

        sources = "\n".join(
            (COMP / name).read_text(encoding="utf-8")
            for name in ("config_flow.py", "engine.py")
        )
        self.assertNotIn("heat_close_enabled", sources)
        migration = (COMP / "__init__.py").read_text(encoding="utf-8")
        self.assertIn('layer.pop(\n                    "heat_close_enabled", None', migration)
        self.assertIn('layer.pop("safety_position_override", None)', migration)
        for language in ("de", "en"):
            translated = (COMP / "translations" / f"{language}.json").read_text(
                encoding="utf-8"
            )
            self.assertNotIn("heat_close_enabled", translated)

    def test_cover_profiles_are_the_shared_capability_contract(self):
        self.assertEqual(set(const.PROFILE_TARGET_KEYS), set(const.DEVICE_TYPES))
        for profile, keys in const.PROFILE_TARGET_KEYS.items():
            with self.subTest(profile=profile):
                self.assertTrue(set(keys).issubset(const.PROFILE_DEFAULTS[profile]))
        self.assertTrue(const.profile_supports_tilt(const.DEVICE_VENETIAN))
        self.assertTrue(const.profile_supports_tilt(const.DEVICE_VERTICAL))
        self.assertFalse(const.profile_supports_tilt(const.DEVICE_CURTAIN))
        self.assertFalse(const.profile_supports_position(const.DEVICE_BINARY))
        self.assertTrue(const.profile_uses_exterior_safety(const.DEVICE_AWNING))
        self.assertFalse(const.profile_uses_exterior_safety(const.DEVICE_CURTAIN))
        self.assertNotIn("safety_position", const.PROFILE_TARGET_KEYS[const.DEVICE_CURTAIN])
        self.assertNotIn("safety_tilt", const.PROFILE_TARGET_KEYS[const.DEVICE_VERTICAL])
        self.assertEqual(
            const.PROFILE_DEFAULTS[const.DEVICE_VERTICAL]["comfort_position"],
            50.0,
        )
        for key in (
            "comfort_position",
            "solar_position",
            "heat_position",
            "night_position",
        ):
            self.assertIn(key, const.PROFILE_TARGET_KEYS[const.DEVICE_VERTICAL])
        self.assertNotIn(
            "night_position",
            const.profile_target_keys(const.DEVICE_ROLLER, night=False),
        )
        self.assertNotIn(
            "safety_position",
            const.profile_target_keys(const.DEVICE_ROLLER, safety=False),
        )
        for profile in const.POSITION_PROFILES:
            self.assertEqual(
                const.PROFILE_DEFAULTS[profile]["position_tolerance"], 5.0
            )
        for profile in const.TILT_PROFILES:
            self.assertEqual(
                const.PROFILE_DEFAULTS[profile]["tilt_tolerance"], 5.0
            )

        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        numbers = (COMP / "number.py").read_text(encoding="utf-8")
        card = (FRONTEND / "shading.js").read_text(encoding="utf-8")
        self.assertIn("profile_target_keys", flow)
        self.assertIn("profile_target_keys", numbers)
        self.assertIn("profileIcon", card)
        self.assertIn("profileSupportsTilt", card)

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
        self.assertIn(
            "self.hass.states.get(DEFAULT_SUN_ENTITY)",
            flow,
        )
        self.assertIn('errors["base"] = "sun_unavailable"', flow)
        self.assertIn("_async_sync_sun_requirement_notification", engine)

    def test_default_pause_is_next_sunrise(self):
        self.assertEqual(const.ROOM_DEFAULTS["default_pause_mode"], const.PAUSE_NEXT_SUNRISE)
        engine = (COMP / "engine.py").read_text(encoding="utf-8")
        self.assertIn('attribute = "next_rising" if mode == PAUSE_NEXT_SUNRISE', engine)
        self.assertIn("async_pause_default", engine)
        select = (COMP / "select.py").read_text(encoding="utf-8")
        self.assertIn(
            "pause_options = [PAUSE_AUTO, *pause_modes_for_room(room)]",
            select,
        )

    def test_schedule_has_no_duplicate_sun_sector_window(self):
        self.assertEqual(
            const.DAY_WINDOW_OPTIONS,
            [const.DAY_WINDOW_ALL_DAY, const.DAY_WINDOW_FIXED],
        )
        self.assertEqual(
            const.ROOM_DEFAULTS["day_window"], const.DAY_WINDOW_ALL_DAY
        )
        migration = (COMP / "__init__.py").read_text(encoding="utf-8")
        self.assertIn('room.get("day_window") == "sector_sun"', migration)
        for language in ("de", "en"):
            translated = (COMP / "translations" / f"{language}.json").read_text(
                encoding="utf-8"
            )
            self.assertNotIn('"sector_sun":', translated)

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
        self.assertIn("uses exactly its", engine)
        self.assertNotIn("_easy_weather_confirmation", engine)
        self.assertIn('attrs.smart_shading_layout === "detailed"', card)
        self.assertNotIn("_roomSelector(roomState)", card)
        self.assertNotIn('data-toggle="advanced_mode"', card)
        self.assertIn('step_id="room_setup" if first_room else "add_room"', flow)
        self.assertIn('prefix = "async_step_manage_"', flow)
        self.assertIn("build_main_room_routes", flow)
        self.assertIn("build_room_routes", flow)
        self.assertIn("async_step_room_hub", flow)
        self.assertIn('"manage_room_details"', flow)
        self.assertIn('"manage_sector"', flow)
        self.assertIn('"manage_layer"', flow)
        self.assertIn('"manage_cover"', flow)
        self.assertIn("DEFAULT_EXTERNAL_MOVEMENT_DETECTION = False", (COMP / "const.py").read_text(encoding="utf-8"))

    def test_customer_status_does_not_publish_cross_mode_bridges(self):
        entity = (COMP / "entity.py").read_text(encoding="utf-8")
        sensor = (COMP / "sensor.py").read_text(encoding="utf-8")
        card = (FRONTEND / "shading.js").read_text(encoding="utf-8")

        for obsolete in (
            "smart_shading_advanced_mode",
            '"configured_mode"',
            '"effective_mode"',
            '"easy_mode_disabled_features"',
        ):
            self.assertNotIn(obsolete, entity + sensor + card)
        self.assertIn('"smart_shading_layout"', entity)
        self.assertIn('attrs.smart_shading_layout === "detailed"', card)
        self.assertIn("if self.engine.advanced_mode:", sensor)
        self.assertIn('attrs["configuration"] = {', sensor)
        engine = (COMP / "engine.py").read_text(encoding="utf-8")
        self.assertIn(
            "self.config = working_config(self.entry.data, self.entry.options)",
            engine,
        )
        self.assertNotIn('"forced_off_features"', engine)

    def test_full_diagnostics_logs_routine_suppressions_only_in_full_mode(self):
        engine = (COMP / "engine.py").read_text(encoding="utf-8")
        self.assertIn("routine_reasons", engine)
        self.assertIn('full=all(reason in routine_reasons for reason in suppressions)', engine)

    def test_multiple_cover_selector_then_names_each_cover(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        self.assertIn('"cover", multiple=True', flow)
        self.assertIn("async_step_compact_cover_details", flow)
        self.assertIn('vol.Required("name"', flow)
        self.assertIn('vol.Required("short"', flow)
        self.assertIn("_pending_cover_entities", flow)

    def test_sector_identity_is_explicit(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        self.assertIn("async_step_manage_sector", flow)
        self.assertIn('vol.Required("sector_identity"): section(', flow)
        self.assertNotIn("async_step_sector_identity", flow)
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
        self.assertNotIn("if not engine.advanced_mode", binary)
        self.assertIn('if sector.get("lux_sensor")', binary)

    def test_translation_files_cover_every_flow(self):
        shared_steps = {
            "room_setup", "add_room", "init", "room_hub",
            "structure_hub", "sector_hub", "group_hub", "cover_hub",
            "manage_room_details", "configure_outdoor_temperature",
            "manage_room_maintenance", "manage_automation", "manage_night",
            "manage_pause", "manage_conditions", "manage_sector",
            "manage_sector_source", "configure_sector_source",
            "configure_lux_profile", "manage_sector_geometry",
            "protected_zones_hub", "add_protected_zone",
            "manage_protected_zone", "confirm_protected_zone",
            "delete_protected_zone", "manage_layer",
            "manage_cover", "add_sector_flat", "add_sector_group",
            "add_sector_covers", "add_layer_flat", "add_group_covers",
            "add_covers_flat",
            "choose_sector_for_group", "choose_group_for_covers",
            "compact_cover_details", "finish",
        }
        obsolete_steps = {
            "compact_room", "compact_sector", "compact_layer",
            "initial_night_setup", "initial_pause_setup",
            "initial_conditions_setup", "sector_identity", "manage_room",
            "room_advanced_setup",
        }
        self.assertFalse((COMP / "strings.json").exists())
        for language in ("de", "en"):
            data = json.loads((COMP / "translations" / f"{language}.json").read_text(encoding="utf-8"))
            for section in ("config", "options"):
                steps = data[section]["step"]
                required_steps = shared_steps | ({"user"} if section == "config" else set())
                self.assertTrue(required_steps.issubset(steps), f"{language}/{section}")
                self.assertTrue(obsolete_steps.isdisjoint(steps), f"{language}/{section}")
                for step in required_steps:
                    self.assertTrue(steps[step].get("title"), f"{language}/{section}/{step}")

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
            ("config", "room_setup", "sun_control"): {"sun_source"},
            ("config", "room_setup", "optional_improvements"): {
                "outdoor_temperature", "outdoor_minimum",
            },
            ("config", "room_setup", "advanced_conditions"): {
                "indoor_temperature", "outdoor_temperature", "outdoor_minimum",
            },
            ("options", "add_room", "room_and_covers"): {
                "name", "direction", "group_name", "profile", "cover_entities"
            },
            ("options", "add_room", "sun_control"): {"sun_source"},
            ("options", "add_room", "advanced_conditions"): {
                "indoor_temperature", "outdoor_temperature", "outdoor_minimum",
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

    def test_every_literal_form_field_has_customer_copy(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        tree = ast.parse(flow)
        fields = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            name = None
            if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "vol"
                and node.func.attr in {"Required", "Optional"}
            ):
                name = node.func.attr
            elif isinstance(node.func, ast.Name) and node.func.id == "_optional_marker":
                name = node.func.id
            if name and isinstance(node.args[0], ast.Constant) and isinstance(
                node.args[0].value, str
            ):
                fields.add(node.args[0].value)

        section_keys = {
            "room_details", "profile_behavior",
            "room_and_covers", "sun_control", "optional_improvements",
            "advanced_conditions", "schedule_settings", "temperature_settings",
            "execution_settings",
            "sector_identity", "sun_confirmation", "sector_maintenance",
            "protected_zone_identity", "protected_zone_geometry",
            "protected_zone_target", "protected_zone_window",
            "protected_zone_object", "protected_zone_activation",
            "protected_zone_conditions",
            "protected_zone_maintenance",
            "group_identity", "slat_curve", "target_positions",
            "group_maintenance", "cover_identity", "cover_automation",
            "cover_maintenance",
        }
        fields -= section_keys
        for language in ("de", "en"):
            data = json.loads(
                (COMP / "translations" / f"{language}.json").read_text(
                    encoding="utf-8"
                )
            )
            labels = {}
            descriptions = {}
            for section in ("config", "options"):
                for step in data[section]["step"].values():
                    labels.update(step.get("data", {}))
                    descriptions.update(step.get("data_description", {}))
                    for form_section in step.get("sections", {}).values():
                        labels.update(form_section.get("data", {}))
                        descriptions.update(
                            form_section.get("data_description", {})
                        )
            self.assertFalse(fields - labels.keys(), (language, fields - labels.keys()))
            self.assertFalse(fields - descriptions.keys(), (language, fields - descriptions.keys()))
            for key in fields:
                self.assertNotEqual(labels[key], key, (language, key))
                self.assertNotIn("_", labels[key], (language, key, labels[key]))

    def test_reachable_options_forms_have_safe_optional_entities(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        self.assertIn('vol.Required("room_details"): section(', flow)
        self.assertIn('vol.Required("sun_source"', flow)
        self.assertIn("CONF_SUN_PRESENCE_ENTITY", flow)
        self.assertNotIn("CONF_WEATHER_ENTITY", flow)
        self.assertNotIn("CONF_EASY_TEMPERATURE_GATE", flow)
        self.assertIn("profile_supports_tilt", flow)
        tree = ast.parse(flow)
        options_class = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "SmartShadingOptionsFlow"
        )
        for step in ("manage_room_details", "manage_cover"):
            method = next(
                node for node in options_class.body
                if isinstance(node, ast.AsyncFunctionDef)
                and node.name == f"async_step_{step}"
            )
            source = ast.get_source_segment(flow, method)
            self.assertIsNotNone(source)
            self.assertIn("_optional_marker", source)
        source_method = next(
            node for node in options_class.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "async_step_manage_sector_source"
        )
        source_selector = ast.get_source_segment(flow, source_method) or ""
        self.assertIn('"sun_source", default=current_source', source_selector)
        sector_method = next(
            node for node in options_class.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "async_step_configure_sector_source"
        )
        sector_source = ast.get_source_segment(flow, sector_method) or ""
        self.assertIn('vol.Required(\n                    "lux_sensor"', sector_source)
        self.assertIn("CONF_SUN_PRESENCE_ENTITY", sector_source)
        for language in ("de", "en"):
            data = json.loads(
                (COMP / "translations" / f"{language}.json").read_text(
                    encoding="utf-8"
                )
            )
            for section in ("config", "options"):
                self.assertIn(
                    "room_details",
                    data[section]["step"]["room_setup"]["sections"],
                )
                self.assertIn(
                    "room_details",
                    data[section]["step"]["add_room"]["sections"],
                )
            self.assertIn("sun_source_required", data["config"]["error"])
            self.assertIn("sun_source_required", data["options"]["error"])

    def test_translation_placeholders_are_intentional(self):
        allowed = {
            "current", "count", "entity_name", "room_name", "sector_name",
            "group_name", "cover_name", "room_count", "sector_count",
            "group_count", "cover_count", "sun_sources", "active_functions",
            "review_warnings", "feature_name", "feature_context",
            "feature_progress", "feature_description", "next_feature",
            "zone_name", "calculation_status", "geometry_summary",
            "current_sun", "calculated_target", "calculation_reason",
            "new_features", "temperature_behavior",
        }
        pattern = re.compile(r"\{([a-zA-Z0-9_]+)\}")
        for language in ("de", "en"):
            data = json.loads((COMP / "translations" / f"{language}.json").read_text(encoding="utf-8"))
            found = set(pattern.findall(json.dumps(data, ensure_ascii=False)))
            self.assertTrue(found.issubset(allowed), (language, found))

    def test_mode_names_are_customer_visible_only_at_first_choice(self):
        active_steps = {
            "room_setup", "add_room", "init", "room_hub",
            "structure_hub", "sector_hub", "group_hub", "cover_hub",
            "manage_room_details", "configure_outdoor_temperature",
            "manage_room_maintenance", "manage_automation", "manage_night",
            "manage_pause", "manage_conditions", "manage_sector",
            "manage_sector_source", "configure_sector_source",
            "configure_lux_profile", "manage_sector_geometry",
            "protected_zones_hub", "add_protected_zone",
            "manage_protected_zone", "confirm_protected_zone",
            "delete_protected_zone", "manage_layer",
            "manage_cover", "add_sector_flat", "add_sector_group",
            "add_sector_covers", "add_layer_flat", "add_group_covers",
            "add_covers_flat",
            "choose_sector_for_group", "choose_group_for_covers",
            "compact_cover_details", "finish",
        }

        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for child in value.values():
                    yield from strings(child)
            elif isinstance(value, list):
                for child in value:
                    yield from strings(child)

        for language in ("de", "en"):
            data = json.loads(
                (COMP / "translations" / f"{language}.json").read_text(
                    encoding="utf-8"
                )
            )
            first_choice = " ".join(strings(data["config"]["step"]["user"]))
            self.assertIn("Easy", first_choice)
            self.assertIn("Advanced", first_choice)
            for section in ("config", "options"):
                post_choice = " ".join(
                    text
                    for step in active_steps
                    for text in strings(data[section]["step"][step])
                )
                self.assertNotRegex(post_choice, r"\b(?:Easy|Advanced)\b")

        card = (FRONTEND / "shading.js").read_text(encoding="utf-8")
        for visible_phrase in (
            "Easy Mode", "Advanced Mode", "Easy mode", "Advanced mode",
            "Easy-Modus", "Advanced-Modus", "optional advanced dialog",
        ):
            self.assertNotIn(visible_phrase, card)

    def test_product_names_appear_only_at_the_initial_choice(self):
        pattern = re.compile(r"\b(?:easy|advanced)\b", re.IGNORECASE)

        def text_values(value):
            if isinstance(value, dict):
                for child in value.values():
                    yield from text_values(child)
            elif isinstance(value, list):
                for child in value:
                    yield from text_values(child)
            elif isinstance(value, str):
                yield value

        for language in ("de", "en"):
            data = json.loads(
                (COMP / "translations" / f"{language}.json").read_text(
                    encoding="utf-8"
                )
            )
            allowed = {
                data["config"]["step"]["user"]["description"],
                data["config"]["step"]["user"]["data_description"][
                    "setup_type"
                ],
                *data["selector"]["setup_type"]["options"].values(),
            }
            found = {
                text for text in text_values(data) if pattern.search(text)
            }
            self.assertEqual(found, allowed, language)

    def test_customer_titles_never_expose_internal_identifiers(self):
        for language in ("de", "en"):
            data = json.loads(
                (COMP / "translations" / f"{language}.json").read_text(
                    encoding="utf-8"
                )
            )
            for section in ("config", "options"):
                for step_id, step in data[section]["step"].items():
                    title = re.sub(
                        r"\{[a-z0-9_]+\}", "", step.get("title", "")
                    )
                    self.assertNotRegex(
                        title,
                        r"[a-z]+_[a-z]+",
                        (language, section, step_id),
                    )

    def test_setup_route_is_fixed_before_room_creation(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        tree = ast.parse(flow)
        config = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "SmartShadingConfigFlow"
        )

        def source(name):
            node = next(
                node for node in config.body
                if isinstance(node, ast.AsyncFunctionDef) and node.name == name
            )
            return ast.get_source_segment(flow, node) or ""

        user = source("async_step_user")
        wizard_mixin = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "_SmartShadingWizardMixin"
        )
        global_method = next(
            node for node in wizard_mixin.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "async_step_global_settings"
        )
        global_source = ast.get_source_segment(flow, global_method) or ""
        init = source("async_step_init")
        self.assertIn("self._fixed_advanced_mode = advanced", user)
        self.assertIn("return await self.async_step_advanced_room_setup()", user)
        self.assertIn("return await self.async_step_easy_room_setup()", user)
        self.assertNotIn("async_step_global_settings", user)
        self.assertIn(
            "self._working[CONF_SUN_ENTITY] = DEFAULT_SUN_ENTITY",
            global_source,
        )
        self.assertIn("return await self.async_step_init()", global_source)
        self.assertIn("async_step_advanced_room_setup", init)
        self.assertIn("async_step_easy_room_setup", init)
        self.assertNotIn("CONF_ADVANCED_MODE", source("async_step_add_room"))

    def test_profile_values_are_advanced_only_and_not_help_text(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        self.assertIn(
            'key in {"sun_preset", "tilt_preset", "schedule_profile"}',
            flow,
        )
        self.assertIn("and self.advanced_mode", flow)
        self.assertIn("for preset, values in SUN_PRESETS.items()", flow)
        self.assertIn("for preset, curve in TILT_CURVE_PRESETS.items()", flow)

        for language in ("de", "en"):
            data = json.loads(
                (COMP / "translations" / f"{language}.json").read_text(
                    encoding="utf-8"
                )
            )
            for selector_key in ("sun_preset", "tilt_preset"):
                easy_labels = data["selector"][selector_key]["options"].values()
                self.assertFalse(
                    any(re.search(r"\d", label) for label in easy_labels),
                    (language, selector_key),
                )
            for section in ("config", "options"):
                explanation = data[section]["step"][
                    "configure_sector_source"
                ]["data_description"]["sun_preset"]
                self.assertNotRegex(explanation, r"\d")

    def test_house_settings_are_not_customer_reachable(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        self.assertNotIn('menu_options["global_settings"]', flow)
        self.assertNotIn(
            "return await self.async_step_global_settings()",
            flow,
        )
        self.assertIn(
            "self._working[CONF_SUN_ENTITY] = DEFAULT_SUN_ENTITY",
            flow,
        )

    def test_removed_noop_heat_fields_cannot_return(self):
        paths = [
            COMP / "config_flow.py", COMP / "const.py", COMP / "number.py",
            COMP / "sensor.py", COMP / "translations" / "de.json",
            COMP / "translations" / "en.json",
        ]
        text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
        self.assertNotIn("heat_fail_safe", text)
        self.assertNotIn("heat_release_temperature", text)

    def test_dynamic_routes_include_position_and_cover_identity(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        tree = ast.parse(flow)
        mixin = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "_SmartShadingWizardMixin"
        )
        route_method = next(
            node for node in mixin.body
            if isinstance(node, ast.FunctionDef) and node.name == "_add_option_route"
        )
        route_source = ast.get_source_segment(flow, route_method) or ""
        self.assertIn('"cover_entity"', route_source)
        self.assertIn('"zone_id"', route_source)
        self.assertIn('"placement"', route_source)
        getattr_method = next(
            node for node in mixin.body
            if isinstance(node, ast.FunctionDef) and node.name == "__getattr__"
        )
        getattr_source = ast.get_source_segment(flow, getattr_method) or ""
        self.assertIn('route.get("cover_entity")', getattr_source)
        self.assertIn('route.get("zone_id")', getattr_source)
        self.assertIn("stale cover route", getattr_source)

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
        tree = ast.parse(flow)
        classes = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
        }
        mixin = classes["_SmartShadingWizardMixin"]
        options_flow = classes["SmartShadingOptionsFlow"]
        mixin_methods = {
            node.name
            for node in mixin.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        option_methods = {
            node.name
            for node in options_flow.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertIn("_add_option_route", mixin_methods)
        self.assertNotIn("_add_option_route", option_methods)
        for method_name in (
            "async_step_room_hub", "async_step_structure_hub",
            "async_step_sector_hub",
            "async_step_group_hub", "async_step_cover_hub",
        ):
            self.assertIn(method_name, mixin_methods)
            self.assertNotIn(method_name, option_methods)

        init_node = next(
            node
            for node in options_flow.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "async_step_init"
        )
        init_calls = {
            node.func.attr
            for node in ast.walk(init_node)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        }
        self.assertIn("_add_option_route", init_calls)

        init = ast.get_source_segment(flow, init_node)
        self.assertIsNotNone(init)
        self.assertIn("build_main_room_routes", init)
        self.assertNotIn("for sector in", init)
        self.assertNotIn("for layer in", init)
        self.assertNotIn("for cover_index", init)

        hub_node = next(
            node for node in mixin.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "async_step_room_hub"
        )
        hub = ast.get_source_segment(flow, hub_node)
        self.assertIsNotNone(hub)
        self.assertIn("build_room_routes", hub)
        self.assertIn('step_id="room_hub"', hub)
        options = flow[flow.index("class SmartShadingOptionsFlow"):]
        for action in (
            "manage_room_details", "add_sector_flat", "add_sector_group",
            "add_sector_covers", "manage_sector", "manage_sector_source",
            "configure_sector_source", "add_layer_flat", "add_group_covers",
            "manage_layer", "add_covers_flat", "manage_cover",
        ):
            self.assertIn(f'"{action}"', options)
            self.assertIn(f"async_step_{action}", options)
        self.assertIn('return self.async_show_menu(step_id="init"', options)
        self.assertIn('menu_options["finish"] = labels["save_changes"]', options)

    def test_new_options_forms_are_fully_translated_in_en_and_de(self):
        required = {
            "room_hub", "structure_hub",
            "add_sector_flat", "add_sector_group", "add_sector_covers",
            "manage_sector", "manage_sector_source",
            "configure_sector_source", "configure_lux_profile",
            "manage_sector_geometry", "protected_zones_hub",
            "add_protected_zone", "manage_protected_zone",
            "delete_protected_zone", "add_layer_flat", "add_group_covers",
            "manage_layer", "add_covers_flat",
            "manage_cover", "sector_hub", "group_hub", "cover_hub",
            "manage_room_details", "manage_room_maintenance",
            "manage_automation", "manage_night", "manage_pause",
            "manage_conditions", "manage_dashboard_badges",
            "choose_sector_for_group",
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

    def test_initial_setup_runs_selected_features_in_safe_order(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        tree = ast.parse(flow)
        config_flow = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "SmartShadingConfigFlow"
        )

        options_flow = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "SmartShadingOptionsFlow"
        )

        def method(owner, name):
            return next(
                node
                for node in owner.body
                if isinstance(node, ast.AsyncFunctionDef) and node.name == name
            )

        def calls(owner, name):
            return {
                node.func.attr
                for node in ast.walk(method(owner, name))
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr.startswith("async_step_")
            }

        self.assertIn(
            "async_step_choose_advanced_features",
            calls(config_flow, "async_step_compact_cover_details"),
        )
        mixin = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "_SmartShadingWizardMixin"
        )
        dispatcher = ast.get_source_segment(
            flow, method(mixin, "async_step_configure_next_advanced_feature")
        ) or ""
        for handler in (
            "manage_schedule",
            "manage_temperature",
            "manage_night",
            "manage_safety",
            "manage_weather_conditions",
            "initial_glare_protection",
            "initial_maximum_opening",
            "manage_dashboard_badges",
            "manage_execution",
        ):
            self.assertIn(f'"{handler}"', dispatcher)
        automation = ast.get_source_segment(
            flow, method(options_flow, "async_step_manage_automation")
        ) or ""
        self.assertNotIn('vol.Required(\n                "schedule_enabled"', automation)
        night = ast.get_source_segment(
            flow, method(options_flow, "async_step_manage_night")
        ) or ""
        self.assertNotIn('vol.Required(\n                "night_enabled"', night)

        initial_cover = ast.get_source_segment(
            flow, method(config_flow, "async_step_compact_cover_details")
        )
        self.assertIsNotNone(initial_cover)
        for field in ("lock", "window", "invert_position", "invert_tilt"):
            self.assertIn(f'"{field}"', initial_cover)

    def test_customer_navigation_uses_task_categories(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        tree = ast.parse(flow)
        mixin = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "_SmartShadingWizardMixin"
        )
        hub_methods = {
            node.name: ast.get_source_segment(flow, node)
            for node in mixin.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name in {
                "async_step_room_hub", "async_step_structure_hub",
                "async_step_sector_hub", "async_step_protected_zones_hub",
                "async_step_group_hub", "async_step_cover_hub",
            }
        }
        self.assertEqual(len(hub_methods), 6)
        hub = "\n".join(source or "" for source in hub_methods.values())
        options = flow[flow.index("class SmartShadingOptionsFlow"):]
        for builder in (
            "build_room_routes", "build_structure_routes",
            "build_sector_routes", "build_protected_zone_routes",
            "build_group_routes",
        ):
            self.assertIn(builder, hub)
        self.assertNotIn("for sector in room.get", hub)
        self.assertIn("full=self.advanced_mode", hub)
        self.assertNotIn("async def async_step_room_hub", options)

    def test_external_sun_confirmation_is_unambiguous(self):
        for language, expected in (
            ("en", "External on/off sensor"),
            ("de", "Externer Ein/Aus-Sensor"),
        ):
            data = json.loads(
                (COMP / "translations" / f"{language}.json").read_text(
                    encoding="utf-8"
                )
            )
            setup_sun = data["config"]["step"]["room_setup"]["sections"]["sun_control"]
            self.assertEqual(set(setup_sun["data"]), {"sun_source"})
            self.assertTrue(setup_sun["data_description"]["sun_source"])
            edit_sun = data["options"]["step"]["configure_sector_source"]
            self.assertEqual(edit_sun["data"]["sun_presence_entity"], expected)
            self.assertIn("Lux", edit_sun["data_description"]["lux_sensor"])

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
        self.assertIn('"type: custom:smart-shading-badge\\n"', engine)
        self.assertNotIn("advanced_mode: false", engine)

    def test_custom_badge_and_scroll_stability_are_registered(self):
        frontend = (FRONTEND / "shading.js").read_text(encoding="utf-8")
        sensor = (COMP / "sensor.py").read_text(encoding="utf-8")
        self.assertIn('customElements.define("smart-shading-badge"', frontend)
        self.assertIn("window.customBadges", frontend)
        self.assertIn("class SmartShadingBadgeEditor", frontend)
        self.assertIn('new CustomEvent("hass-action"', frontend)
        self.assertIn('selector: { entity: { domain: "sensor", integration: "smart_shading" } }', frontend)
        self.assertNotIn('<select data-entity>', frontend.split("class SmartShadingBadgeEditor", 1)[1].split("class SmartShadingV4CardEditor", 1)[0])
        self.assertIn('<ha-badge type="button" icon-only', frontend)
        self.assertIn('slot="icon"', frontend)
        self.assertIn('class="cover-symbol"', frontend)
        self.assertIn('class="state-marker"', frontend)
        self.assertNotIn('class="badge" data-mode=', frontend)
        self.assertNotIn("captureScrollPositions", frontend)
        self.assertNotIn("restoreScrollPositions", frontend)
        self.assertNotIn("scrollTop", frontend)
        self.assertNotIn("scrollLeft", frontend)
        self.assertNotIn("scrollIntoView", frontend)
        self.assertNotIn("ResizeObserver", frontend)
        self.assertIn("reconcileDomChildren", frontend)
        self.assertIn("updateStableMarkup(this.shadowRoot, nextCardHtml)", frontend)
        self.assertNotIn("this.shadowRoot.innerHTML = nextCardHtml", frontend)
        self.assertIn('"pause_until": runtime.pause_until', sensor)
        self.assertNotIn('"card_yaml"', sensor)
        self.assertNotIn('"badge_yaml"', sensor)
        self.assertIn('"cover_profiles"', sensor)
        self.assertIn("STATE_ATTRIBUTE_BUDGET = 15_500", sensor)
        self.assertIn("_compact_room_configuration", sensor)
        self.assertIn('"condition_activation_delay_seconds"', sensor)
        self.assertIn('"condition_release_delay_seconds"', sensor)
        self.assertIn("_fit_attribute_budget", sensor)

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
        logic = (COMP / "logic.py").read_text(encoding="utf-8")
        self.assertIn("def finalize_sector_identity", logic)
        self.assertIn('result["id"] = str(result.get("id") or id_factory(clean_name))', logic)
        self.assertIn("sun_source_for_sector", flow)
        self.assertNotIn("needs_custom_sun_settings", flow)

    def test_safety_precedes_pause_and_disable(self):
        engine = (COMP / "engine.py").read_text(encoding="utf-8")
        evaluation = engine.index("async def _evaluate_room")
        easy = engine.index("if not self.advanced_mode:", evaluation)
        priority = engine.index(
            "priority_result = self._resolve_advanced_decision(", evaluation
        )
        safety = engine.index("if priority_result.mode == MODE_SAFETY:", priority)
        disabled = engine.index("if priority_result.mode == MODE_DISABLED:", safety)
        paused = engine.index("if priority_result.mode == MODE_PAUSED:", disabled)
        self.assertLess(easy, priority)
        self.assertLess(priority, safety)
        self.assertLess(safety, disabled)
        self.assertLess(disabled, paused)
        self.assertIn('"safety_active": bool(blockers)', engine[evaluation:priority])
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
        for step in ("compact_cover_details", "manage_sector", "manage_layer"):
            self.assertIn(f"async_step_{step}", flow)
        for removed in ("compact_room", "compact_sector", "compact_layer"):
            self.assertNotIn(f"async_step_{removed}", flow)
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
                step = data[section]["step"]["manage_cover"]["sections"]["cover_automation"]
                self.assertIn("window_returns_to_automation", step["data"])
                self.assertIn(
                    "window_returns_to_automation", step["data_description"]
                )

    def test_advanced_execution_controls_are_translated_and_scoped(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        for field in (
            "command_stagger_seconds",
            "stagger_scope",
            "safety_bypasses_stagger",
            "target_verification_enabled",
            "verification_retries",
            "movement_seconds",
            "settling_seconds",
            "source_stale_seconds",
            "feedback_quality",
            "verify_target",
            "allow_automatic_reverse",
            "opening_order",
        ):
            self.assertIn(f'"{field}"', flow)
        for language in ("de", "en"):
            data = json.loads(
                (COMP / "translations" / f"{language}.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn("feedback_quality", data["selector"])
            self.assertIn("stagger_scope", data["selector"])
            self.assertIn("opening_order", data["selector"])
            for section in ("config", "options"):
                execution = data[section]["step"]["manage_automation"][
                    "sections"
                ]["execution_settings"]
                self.assertTrue(
                    {
                        "command_stagger_seconds",
                        "stagger_scope",
                        "safety_bypasses_stagger",
                        "target_verification_enabled",
                        "verification_retries",
                        "movement_seconds",
                        "settling_seconds",
                        "source_stale_seconds",
                    }.issubset(execution["data"])
                )
                cover = data[section]["step"]["manage_cover"]["sections"][
                    "cover_automation"
                ]["data"]
                self.assertTrue(
                    {
                        "feedback_quality",
                        "verify_target",
                        "allow_automatic_reverse",
                    }.issubset(cover)
                )
                profile = data[section]["step"]["manage_layer_profile"][
                    "sections"
                ]["profile_behavior"]["data"]
                self.assertIn("opening_order", profile)

    def test_preview_day_service_is_async_and_translated(self):
        """The customer-facing day preview must work and remain localizable."""
        integration = (COMP / "__init__.py").read_text(encoding="utf-8")
        service_schema = (COMP / "services.yaml").read_text(encoding="utf-8")
        self.assertIn("async def async_handle_preview_day", integration)
        self.assertIn("async_handle_preview_day,", integration)
        self.assertIn("raise ServiceValidationError(", integration)
        self.assertIn("preview_day:", service_schema)
        for language in ("en", "de"):
            data = json.loads(
                (COMP / "translations" / f"{language}.json").read_text(
                    encoding="utf-8"
                )
            )
            preview = data["services"]["preview_day"]
            self.assertTrue(preview["name"])
            self.assertTrue(preview["description"])
            self.assertEqual(
                set(preview["fields"]), {"room_id", "date", "entry_id"}
            )
            for field in preview["fields"].values():
                self.assertTrue(field["name"])
                self.assertTrue(field["description"])

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
        self.assertIn(
            "CONF_EVALUATION_INTERVAL: DEFAULT_EVALUATION_INTERVAL", flow
        )
        self.assertNotIn('vol.Required("evaluation_interval_minutes"', flow)
        engine = (COMP / "engine.py").read_text(encoding="utf-8")
        self.assertIn("timedelta(seconds=interval)", engine)

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

    def test_normal_state_changes_are_event_driven_and_debounced(self):
        engine = (COMP / "engine.py").read_text(encoding="utf-8")
        self.assertIn("async def _queue_evaluation", engine)
        self.assertIn("_evaluation_debounce_unsub", engine)
        self.assertIn('await self._queue_evaluation(f"input_state:{entity_id}")', engine)
        self.assertIn("sun_presence_transition", engine)
        self.assertIn('await self.async_evaluate_all("watchdog")', engine)
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
        self.assertIn("push:", workflow)
        self.assertIn("- develop", workflow)
        self.assertIn("- main", workflow)
        self.assertIn("- custom_components/smart_shading/manifest.json", workflow)
        self.assertIn("release-metadata:", workflow)
        self.assertIn("publish=false", workflow)
        self.assertIn(
            "needs.release-metadata.outputs.publish == 'true'", workflow
        )
        self.assertIn("validate_release_channel.py", workflow)
        self.assertIn("CHANNEL: ${{ needs.release-metadata.outputs.channel }}", workflow)
        self.assertIn("prerelease: ${{ github.ref_name == 'develop' }}", workflow)
        self.assertIn("make_latest: ${{ github.ref_name == 'main' }}", workflow)
        self.assertIn("release_changelog.py notes", workflow)
        self.assertIn("body_path: dist/release-notes.md", workflow)
        self.assertNotIn("generate_release_notes:", workflow)
        self.assertNotIn("push:\n    tags:", workflow)

    def test_every_release_path_uses_the_repository_wide_syntax_gate(self):
        for relative in (
            ".github/workflows/validate.yml",
            ".github/workflows/prepare-release.yml",
            ".github/workflows/release.yml",
        ):
            with self.subTest(workflow=relative):
                workflow = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn("python scripts/check_source_syntax.py", workflow)

        checker = (ROOT / "scripts" / "check_source_syntax.py").read_text(
            encoding="utf-8"
        )
        for expected in (
            "py_compile.compile",
            '"node", "--check"',
            '"bash", "-n"',
            'require "yaml"',
            "json.load",
        ):
            self.assertIn(expected, checker)

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
