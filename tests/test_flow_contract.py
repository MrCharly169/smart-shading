from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
COMP = ROOT / "custom_components" / "smart_shading"
FLOW_PATH = COMP / "config_flow.py"

spec = importlib.util.spec_from_file_location(
    "smart_shading_flow_contract", COMP / "flow_contract.py"
)
contract = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(contract)


def _class(tree: ast.Module, name: str) -> ast.ClassDef:
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == name
    )


def _method(class_node: ast.ClassDef, name: str) -> ast.AsyncFunctionDef:
    return next(
        node
        for node in class_node.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name
    )


def _async_step_calls(node: ast.AST) -> set[str]:
    return {
        child.func.attr
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and child.func.attr.startswith("async_step_")
    }


def _attribute_calls(node: ast.AST) -> set[str]:
    return {
        child.func.attr
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
    }


def _qualified_attribute_calls(node: ast.AST) -> set[tuple[str, str]]:
    return {
        (child.func.value.id, child.func.attr)
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and isinstance(child.func.value, ast.Name)
    }


def _vol_schema_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if not (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and isinstance(child.func.value, ast.Name)
            and child.func.value.id == "vol"
            and child.func.attr in {"Required", "Optional"}
            and child.args
        ):
            continue
        key = child.args[0]
        if isinstance(key, ast.Name):
            names.add(key.id)
        elif isinstance(key, ast.Constant) and isinstance(key.value, str):
            names.add(key.value)
    return names


class FlowContractTests(unittest.TestCase):
    def test_config_flow_delegates_initial_function_target_helpers(self):
        tree = ast.parse(FLOW_PATH.read_text(encoding="utf-8"))
        config_flow = _class(tree, "SmartShadingConfigFlow")
        method_names = {
            node.name
            for node in config_flow.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertIn("_layers_with_function_targets", method_names)
        self.assertIn("_async_step_initial_function_targets", method_names)

    def test_standard_layer_profile_submit_initializes_custom_rerender_flag(self):
        tree = ast.parse(FLOW_PATH.read_text(encoding="utf-8"))
        options_flow = _class(tree, "SmartShadingOptionsFlow")
        profile_step = _method(options_flow, "async_step_manage_layer_profile")

        initializers = [
            node
            for node in profile_step.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "rerender_custom_curve"
                for target in node.targets
            )
        ]

        self.assertEqual(len(initializers), 1)
        self.assertIsInstance(initializers[0].value, ast.Constant)
        self.assertIs(initializers[0].value.value, False)

    def test_setup_choice_maps_only_the_supported_values(self):
        self.assertEqual(
            contract.SETUP_TYPES,
            (contract.SETUP_EASY, contract.SETUP_ADVANCED),
        )
        self.assertFalse(contract.setup_is_advanced(contract.SETUP_EASY))
        self.assertTrue(contract.setup_is_advanced(contract.SETUP_ADVANCED))
        with self.assertRaises(ValueError):
            contract.setup_is_advanced("unexpected")

    def test_v14_mode_is_locked_to_entry_data(self):
        cases = (
            ({"advanced_mode": True}, {"advanced_mode": False}, True),
            ({"advanced_mode": False}, {"advanced_mode": True}, False),
            ({"advanced_mode": True}, {}, True),
            ({"advanced_mode": False}, None, False),
            ({}, {"advanced_mode": True}, True),
            ({}, {"advanced_mode": False}, False),
            ({}, {}, False),
            ({}, None, False),
        )
        for data, options, expected in cases:
            with self.subTest(data=data, options=options):
                self.assertIs(
                    contract.locked_advanced_mode(data, options), expected
                )

    def test_legacy_migration_preserves_the_original_data_choice(self):
        cases = (
            ({"advanced_mode": True}, {}, True),
            ({"advanced_mode": False}, {}, False),
            ({"advanced_mode": True}, {"rooms": []}, True),
            ({"advanced_mode": False}, {"rooms": []}, False),
            ({"advanced_mode": False}, {"advanced_mode": True}, False),
            ({"advanced_mode": True}, {"advanced_mode": False}, True),
            ({}, {"advanced_mode": True}, True),
            ({}, {"advanced_mode": False}, False),
            ({}, {}, False),
            ({}, None, False),
        )
        for data, options, expected in cases:
            with self.subTest(data=data, options=options):
                self.assertIs(
                    contract.locked_advanced_mode(data, options),
                    expected,
                )

    def test_legacy_effective_config_merges_partial_options_without_data_loss(self):
        data = {
            "house_name": "Home",
            "evaluation_interval": 1200,
            "rooms": [
                {
                    "id": "living",
                    "name": "Living room",
                    "sectors": [{"id": "south", "name": "South"}],
                }
            ],
        }
        options = {"evaluation_interval": 600}

        result = contract.legacy_effective_config(data, options)

        self.assertEqual(result["house_name"], "Home")
        self.assertEqual(result["evaluation_interval"], 600)
        self.assertEqual(result["rooms"], data["rooms"])
        self.assertIsNot(result["rooms"], data["rooms"])
        self.assertIsNot(
            result["rooms"][0]["sectors"], data["rooms"][0]["sectors"]
        )

        result["rooms"][0]["sectors"][0]["name"] = "Changed"
        result["house_name"] = "Changed house"
        self.assertEqual(data["house_name"], "Home")
        self.assertEqual(data["rooms"][0]["sectors"][0]["name"], "South")
        self.assertEqual(options, {"evaluation_interval": 600})

    def test_working_config_ignores_an_option_level_mode_override(self):
        data = {
            "advanced_mode": True,
            "house_name": "House",
            "rooms": [{"id": "original"}],
        }
        options = {
            "advanced_mode": False,
            "rooms": [{"id": "edited"}],
        }

        result = contract.working_config(data, options)

        self.assertTrue(result["advanced_mode"])
        self.assertEqual(result["rooms"], [{"id": "edited"}])
        result["rooms"][0]["id"] = "mutated"
        self.assertEqual(options["rooms"], [{"id": "edited"}])
        self.assertEqual(data["rooms"], [{"id": "original"}])

    def test_editable_options_remove_immutable_mode_and_are_copied(self):
        config = {
            "advanced_mode": True,
            "diagnostic_level": "events",
            "rooms": [{"id": "living"}],
        }

        options = contract.editable_options(config)

        self.assertNotIn("advanced_mode", options)
        self.assertEqual(options["diagnostic_level"], "events")
        options["rooms"][0]["id"] = "changed"
        self.assertEqual(config["rooms"], [{"id": "living"}])

    def test_saved_options_cannot_change_the_locked_mode_on_reload(self):
        data = {"advanced_mode": False, "rooms": [{"id": "living"}]}
        crafted_working_copy = {
            "advanced_mode": True,
            "rooms": [{"id": "office"}],
        }

        saved = contract.editable_options(crafted_working_copy)
        reloaded = contract.working_config(data, saved)

        self.assertNotIn("advanced_mode", saved)
        self.assertFalse(reloaded["advanced_mode"])
        self.assertEqual(reloaded["rooms"], [{"id": "office"}])

    def test_sun_source_is_explicit_and_legacy_safe(self):
        self.assertEqual(
            contract.sun_source_for_sector(
                {"sun_source": "geometry", "lux_sensor": "sensor.facade"},
                advanced=False,
            ),
            "geometry",
        )

    def test_legacy_sun_sources_migrate_to_one_explicit_choice(self):
        self.assertEqual(
            contract.sun_source_for_sector(
                {"lux_sensor": "sensor.facade"}, advanced=True
            ),
            "lux",
        )
        self.assertEqual(
            contract.sun_source_for_sector(
                {"sun_presence_entity": "binary_sensor.facade"},
                advanced=False,
            ),
            "external",
        )
        self.assertEqual(
            contract.sun_source_for_sector(
                {
                    "sun_source": "external",
                    "sun_presence_entity": "binary_sensor.facade",
                },
                advanced=True,
            ),
            "external",
        )

    def test_runtime_overrides_are_folded_into_one_editable_snapshot(self):
        config = {
            "advanced_mode": True,
            "diagnostic_level": "off",
            "rooms": [
                {
                    "id": "living",
                    "heat_temperature": 27,
                    "sectors": [
                        {
                            "id": "south",
                            "enabled": True,
                            "sun_preset": "medium",
                            "layers": [
                                {
                                    "id": "blind",
                                    "open_position": 100,
                                    "tilt_curve": [
                                        {"elevation": 10, "tilt": 90},
                                        {"elevation": 30, "tilt": 60},
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        overrides = {
            "house": {
                "house": {
                    "diagnostic_level": "full",
                    "advanced_mode": False,
                }
            },
            "room": {"living": {"heat_temperature": 30}},
            "sector": {"south": {"enabled": False, "sun_preset": "high"}},
            "layer": {
                "blind": {
                    "open_position": 85,
                    "tilt_elevation_1": 12,
                    "tilt_value_2": 55,
                }
            },
        }

        result = contract.config_with_runtime_overrides(config, overrides)

        self.assertTrue(result["advanced_mode"])
        self.assertEqual(result["diagnostic_level"], "full")
        room = result["rooms"][0]
        self.assertEqual(room["heat_temperature"], 30)
        sector = room["sectors"][0]
        self.assertFalse(sector["enabled"])
        self.assertEqual(sector["sun_preset"], "high")
        layer = sector["layers"][0]
        self.assertEqual(layer["open_position"], 85)
        self.assertEqual(layer["tilt_curve"][0], {"elevation": 12, "tilt": 90})
        self.assertEqual(layer["tilt_curve"][1], {"elevation": 30, "tilt": 55})
        self.assertEqual(config["rooms"][0]["heat_temperature"], 27)

    def test_malformed_runtime_override_scopes_are_ignored(self):
        config = {
            "advanced_mode": False,
            "rooms": [{"id": "living", "sectors": []}],
        }

        result = contract.config_with_runtime_overrides(
            config,
            {"house": [], "room": "invalid", "sector": None, "layer": 42},
        )

        self.assertEqual(result, config)


class WizardRouteContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(
            FLOW_PATH.read_text(encoding="utf-8"), filename=str(FLOW_PATH)
        )
        cls.mixin = _class(cls.tree, "_SmartShadingWizardMixin")
        cls.config_flow = _class(cls.tree, "SmartShadingConfigFlow")
        cls.options_flow = _class(cls.tree, "SmartShadingOptionsFlow")

    def test_initial_choice_dispatches_to_distinct_immutable_entry_routes(self):
        method_names = {
            node.name
            for node in self.config_flow.body
            if isinstance(node, ast.AsyncFunctionDef)
        }
        self.assertIn("async_step_easy_room_setup", method_names)
        self.assertIn("async_step_advanced_room_setup", method_names)

        user_calls = _async_step_calls(
            _method(self.config_flow, "async_step_user")
        )
        self.assertEqual(
            user_calls,
            {"async_step_easy_room_setup", "async_step_advanced_room_setup"},
        )

        init_calls = _async_step_calls(
            _method(self.config_flow, "async_step_init")
        )
        self.assertIn("async_step_easy_room_setup", init_calls)
        self.assertIn("async_step_advanced_room_setup", init_calls)

        easy_calls = _async_step_calls(
            _method(self.config_flow, "async_step_easy_room_setup")
        )
        advanced_calls = _async_step_calls(
            _method(self.config_flow, "async_step_advanced_room_setup")
        )
        self.assertNotIn("async_step_advanced_room_setup", easy_calls)
        self.assertNotIn("async_step_easy_room_setup", advanced_calls)
        self.assertIn("async_step_init", easy_calls)
        self.assertIn("async_step_init", advanced_calls)

        for route in (
            "async_step_easy_room_setup",
            "async_step_advanced_room_setup",
        ):
            with self.subTest(route=route):
                self.assertIn(
                    "_async_step_room_setup",
                    _attribute_calls(_method(self.config_flow, route)),
                )

    def test_shared_navigation_is_defined_once(self):
        shared_methods = {
            "async_step_room_hub",
            "async_step_sector_hub",
            "async_step_protected_zones_hub",
            "async_step_group_hub",
            "async_step_cover_hub",
            "async_step_choose_sector_for_group",
            "async_step_choose_group_for_covers",
        }
        mixin_methods = {
            node.name
            for node in self.mixin.body
            if isinstance(node, ast.AsyncFunctionDef)
        }
        self.assertTrue(shared_methods.issubset(mixin_methods))
        for flow_class in (self.config_flow, self.options_flow):
            class_methods = {
                node.name
                for node in flow_class.body
                if isinstance(node, ast.AsyncFunctionDef)
            }
            self.assertTrue(shared_methods.isdisjoint(class_methods))

        shared_form = _method(self.config_flow, "_async_step_room_setup")
        shared_source = ast.get_source_segment(
            FLOW_PATH.read_text(encoding="utf-8"), shared_form
        )
        self.assertIsNotNone(shared_source)
        self.assertIn('step_id="room_setup"', shared_source)

        # A form step is submitted by method name on the next request.  The
        # shared renderer therefore needs a public handler for its literal
        # first-room step id; otherwise Home Assistant removes the flow and
        # the frontend reports "Invalid flow specified".
        first_room_handler = _method(
            self.config_flow, "async_step_room_setup"
        )
        self.assertIn(
            "_async_step_room_setup",
            _attribute_calls(first_room_handler),
        )

    def test_indoor_temperature_is_owned_by_the_optional_temperature_feature(self):
        room_setup = ast.get_source_segment(
            FLOW_PATH.read_text(encoding="utf-8"),
            _method(self.config_flow, "_async_step_room_setup"),
        ) or ""
        room_details = ast.get_source_segment(
            FLOW_PATH.read_text(encoding="utf-8"),
            _method(self.options_flow, "async_step_manage_room_details"),
        ) or ""
        automation = ast.get_source_segment(
            FLOW_PATH.read_text(encoding="utf-8"),
            _method(self.options_flow, "async_step_manage_automation"),
        ) or ""

        self.assertNotIn('vol.Optional("indoor_temperature")', room_setup)
        self.assertNotIn('room["indoor_temperature"]', room_setup)
        self.assertNotIn('"indoor_temperature"', room_details)
        self.assertIn('vol.Required(\n                    "indoor_temperature"', automation)
        self.assertIn("temperature_selected", automation)

    def test_protected_zone_wizard_is_advanced_and_pipeline_compatible(self):
        source = FLOW_PATH.read_text(encoding="utf-8")
        mixin_methods = {
            node.name
            for node in self.mixin.body
            if isinstance(node, ast.AsyncFunctionDef)
        }
        self.assertIn("async_step_protected_zones_hub", mixin_methods)

        options_methods = {
            node.name
            for node in self.options_flow.body
            if isinstance(node, ast.AsyncFunctionDef)
        }
        for method_name in (
            "async_step_add_protected_zone",
            "async_step_manage_protected_zone",
            "async_step_delete_protected_zone",
        ):
            with self.subTest(method=method_name):
                self.assertIn(method_name, options_methods)
                self.assertIn(
                    ("SmartShadingOptionsFlow", method_name),
                    _qualified_attribute_calls(
                        _method(self.config_flow, method_name)
                    ),
                )
                method_source = ast.get_source_segment(
                    source, _method(self.options_flow, method_name)
                ) or ""
                self.assertIn("if not self.advanced_mode", method_source)
                self.assertIn("async_step_sector_hub", method_source)
        self.assertIn("async_step_confirm_protected_zone", options_methods)
        self.assertIn(
            ("SmartShadingOptionsFlow", "async_step_confirm_protected_zone"),
            _qualified_attribute_calls(
                _method(self.config_flow, "async_step_confirm_protected_zone")
            ),
        )

        zones_source = ast.get_source_segment(
            source,
            next(
                node
                for node in self.mixin.body
                if isinstance(node, ast.FunctionDef)
                and node.name == "protected_zones"
            ),
        ) or ""
        self.assertIn("_new_id", zones_source)
        self.assertIn('zone["sector_id"]', zones_source)

        selector_source = ast.get_source_segment(
            source,
            next(
                node
                for node in self.mixin.body
                if isinstance(node, ast.FunctionDef)
                and node.name == "_protected_zone_cover_selector"
            ),
        ) or ""
        self.assertIn("multiple=False", selector_source)
        self.assertIn("_protected_zone_covers()", selector_source)

        payload_source = ast.get_source_segment(
            source,
            next(
                node
                for node in self.mixin.body
                if isinstance(node, ast.FunctionDef)
                and node.name == "_validated_protected_zone_values"
            ),
        ) or ""
        for field in (
            "sector_id",
            "cover_entity",
            "distance_m",
            "lower_height_m",
            "upper_height_m",
            "window_width_m",
            "window_height_m",
            "window_sill_height_m",
            "object_distance_m",
            "object_center_height_m",
            "object_height_m",
            "object_lateral_center_m",
            "object_width_m",
            "curtain_movement",
            "sun_confirmation_enabled",
            "minimum_sun_elevation_degrees",
            "conditions",
        ):
            self.assertIn(f'"{field}"', payload_source)
        self.assertNotIn('"group_ids"', payload_source)
        self.assertNotIn('"calculated"', payload_source)
        self.assertNotIn("distance_from_facade", payload_source)
        self.assertNotIn("protection_strength", payload_source)

        form_source = ast.get_source_segment(
            source,
            next(
                node
                for node in self.mixin.body
                if isinstance(node, ast.FunctionDef)
                and node.name == "_protected_zone_form_sections"
            ),
        ) or ""
        self.assertIn("selector.ConditionSelector()", form_source)
        self.assertIn('vol.Required("protected_zone_activation")', form_source)
        self.assertIn('"sun_confirmation_enabled"', form_source)
        self.assertIn('"minimum_sun_elevation_degrees"', form_source)
        self.assertIn('vol.Optional("protected_zone_conditions")', form_source)
        self.assertIn('"left_to_right"', form_source)
        self.assertIn('"right_to_left"', form_source)
        self.assertNotIn("curtain_max_closing_step_percent", payload_source)

        add_source = ast.get_source_segment(
            source, _method(self.options_flow, "async_step_add_protected_zone")
        ) or ""
        delete_source = ast.get_source_segment(
            source, _method(self.options_flow, "async_step_delete_protected_zone")
        ) or ""
        self.assertIn('zone_values["id"] = _new_id', add_source)
        self.assertIn("_pending_protected_zone", add_source)
        self.assertIn("async_step_confirm_protected_zone", add_source)
        self.assertIn("confirm_delete_protected_zone", delete_source)

    def test_advanced_execution_controls_stay_in_room_and_cover_forms(self):
        source = FLOW_PATH.read_text(encoding="utf-8")
        automation = ast.get_source_segment(
            source, _method(self.options_flow, "async_step_manage_automation")
        ) or ""
        cover = ast.get_source_segment(
            source, _method(self.options_flow, "async_step_manage_cover")
        ) or ""
        layer_profile = ast.get_source_segment(
            source, _method(self.options_flow, "async_step_manage_layer_profile")
        ) or ""

        self.assertIn("if not self.advanced_mode", automation)
        for field, default in (
            ("command_stagger_seconds", "DEFAULT_STAGGER_SECONDS"),
            ("stagger_scope", "DEFAULT_STAGGER_SCOPE"),
            ("safety_bypasses_stagger", "DEFAULT_SAFETY_BYPASSES_STAGGER"),
            ("target_verification_enabled", "False"),
            ("verification_retries", "DEFAULT_VERIFICATION_RETRIES"),
            ("movement_seconds", "DEFAULT_MOVEMENT_SECONDS"),
            ("settling_seconds", "DEFAULT_SETTLING_SECONDS"),
            ("source_stale_seconds", "DEFAULT_SOURCE_STALE_SECONDS"),
        ):
            with self.subTest(room_field=field):
                self.assertIn(f'"{field}"', automation)
                self.assertIn(default, automation)
        self.assertIn('_number(0, 86400, 30, "s", mode="box")', automation)

        self.assertIn("if self.advanced_mode:", cover)
        self.assertIn("FEEDBACK_QUALITY_OPTIONS", cover)
        self.assertIn('"feedback_quality"', cover)
        self.assertIn('"verify_target"', cover)
        self.assertIn('"allow_automatic_reverse"', cover)
        self.assertIn("DEFAULT_ALLOW_AUTOMATIC_REVERSE", cover)

        self.assertIn("self.advanced_mode and has_tilt", layer_profile)
        self.assertIn('"opening_order"', layer_profile)
        self.assertIn("OPENING_ORDER_OPTIONS", layer_profile)

    def test_object_creation_is_atomic_and_hierarchically_scoped(self):
        add_sector = _method(
            self.options_flow, "async_step_add_sector_flat"
        )
        commit_sector = _method(
            self.options_flow, "async_step_commit_pending_sector"
        )
        add_group = _method(
            self.options_flow, "async_step_add_layer_flat"
        )
        commit_group = _method(
            self.options_flow, "async_step_commit_pending_layer"
        )
        add_covers = _method(
            self.options_flow, "async_step_add_covers_flat"
        )
        source = FLOW_PATH.read_text(encoding="utf-8")

        add_sector_source = ast.get_source_segment(source, add_sector) or ""
        self.assertIn("self._pending_sector = sector", add_sector_source)
        self.assertNotIn('setdefault("sectors", []).append', add_sector_source)
        self.assertIn("async_step_add_sector_group", add_sector_source)

        commit_sector_source = (
            ast.get_source_segment(source, commit_sector) or ""
        )
        self.assertIn('setdefault("sectors", []).append', commit_sector_source)
        self.assertIn('sector["layers"][0].get("covers")', commit_sector_source)

        add_group_source = ast.get_source_segment(source, add_group) or ""
        self.assertIn("self._pending_layer = layer", add_group_source)
        self.assertIn("async_step_add_group_covers", add_group_source)
        self.assertNotIn('setdefault("layers", []).append', add_group_source)

        commit_group_source = ast.get_source_segment(source, commit_group) or ""
        self.assertIn('setdefault("layers", []).append', commit_group_source)
        self.assertIn('layer.get("covers")', commit_group_source)

        self.assertIn(
            'self._pending_cover_return_step = "group_hub"',
            ast.get_source_segment(source, add_covers) or "",
        )

    def test_initial_advanced_room_structure_finishes_before_features(self):
        source = FLOW_PATH.read_text(encoding="utf-8")
        structure_hub = ast.get_source_segment(
            source, _method(self.mixin, "async_step_structure_hub")
        ) or ""
        commit_sector = ast.get_source_segment(
            source,
            _method(self.options_flow, "async_step_commit_pending_sector"),
        ) or ""
        complete_structure = ast.get_source_segment(
            source,
            _method(self.mixin, "async_step_complete_initial_structure"),
        ) or ""
        initial_structure_handler = ast.get_source_segment(
            source,
            _method(self.mixin, "async_step_initial_structure_hub"),
        ) or ""

        self.assertIn('step_id="initial_structure_hub"', structure_hub)
        self.assertIn('"complete_initial_structure"', structure_hub)
        self.assertIn(
            "async_step_structure_hub", commit_sector
        )
        self.assertIn(
            "async_step_choose_advanced_features", complete_structure
        )
        self.assertIn(
            "async_step_structure_hub", initial_structure_handler
        )

    def test_cover_profiles_unlock_only_supported_optional_features(self):
        source = FLOW_PATH.read_text(encoding="utf-8")
        choose = ast.get_source_segment(
            source,
            _method(self.mixin, "async_step_choose_advanced_features"),
        ) or ""
        discovery = ast.get_source_segment(
            source,
            _method(self.mixin, "_finish_structure_change"),
        ) or ""
        maximum = ast.get_source_segment(
            source,
            _method(self.mixin, "async_step_initial_maximum_opening"),
        ) or ""

        self.assertIn("_room_supports_glare_protection", choose)
        self.assertIn("_room_supports_maximum_opening", choose)
        self.assertIn("newly_available", discovery)
        self.assertIn(
            "async_step_new_optional_feature_available", discovery
        )
        self.assertIn("enforce_max_open_position", maximum)
        self.assertIn("max_open_position", maximum)

    def test_temperature_copy_is_derived_from_room_profiles(self):
        source = FLOW_PATH.read_text(encoding="utf-8")
        helper = ast.get_source_segment(
            source,
            next(
                node
                for node in self.mixin.body
                if isinstance(node, ast.FunctionDef)
                and node.name == "_temperature_behavior_text"
            ),
        ) or ""
        automation = ast.get_source_segment(
            source,
            _method(self.options_flow, "async_step_manage_automation"),
        ) or ""

        self.assertIn("DEVICE_VENETIAN", helper)
        self.assertIn("has_other_profiles", helper)
        self.assertIn('"temperature_behavior"', automation)

    def test_advanced_creation_configures_only_selected_features_in_order(self):
        compact_calls = _async_step_calls(
            _method(self.config_flow, "async_step_compact_cover_details")
        )
        self.assertIn("async_step_choose_advanced_features", compact_calls)
        self.assertNotIn("async_step_manage_automation", compact_calls)

        dispatcher = ast.get_source_segment(
            FLOW_PATH.read_text(encoding="utf-8"),
            _method(self.mixin, "async_step_configure_next_advanced_feature"),
        ) or ""
        ordered_handlers = (
            "manage_schedule",
            "manage_temperature",
            "manage_night",
            "manage_safety",
            "manage_weather_conditions",
            "initial_glare_protection",
            "initial_maximum_opening",
            "manage_dashboard_badges",
            "manage_execution",
        )
        offsets = [dispatcher.index(f'"{handler}"') for handler in ordered_handlers]
        self.assertEqual(offsets, sorted(offsets))

        chooser = ast.get_source_segment(
            FLOW_PATH.read_text(encoding="utf-8"),
            _method(self.mixin, "async_step_choose_advanced_features"),
        ) or ""
        self.assertIn('room["schedule_enabled"] = True', chooser)
        self.assertIn('room["night_enabled"] = True', chooser)
        self.assertIn("_start_initial_feature_sequence", chooser)
        self.assertIn("newly_enabled", chooser)
        self.assertIn("self._queued_feature_setup = newly_enabled", chooser)
        self.assertIn("SHARED_FEATURES", chooser)

        badge_setup = ast.get_source_segment(
            FLOW_PATH.read_text(encoding="utf-8"),
            _method(self.mixin, "async_step_manage_dashboard_badges"),
        ) or ""
        self.assertIn("_finish_feature_step", badge_setup)
        self.assertIn('step_id="manage_dashboard_badges"', badge_setup)

        night_source = ast.get_source_segment(
            FLOW_PATH.read_text(encoding="utf-8"),
            _method(self.options_flow, "async_step_manage_night"),
        ) or ""
        conditions_source = ast.get_source_segment(
            FLOW_PATH.read_text(encoding="utf-8"),
            _method(self.options_flow, "async_step_manage_conditions"),
        ) or ""
        self.assertNotIn("async_step_initial_night_targets", night_source)
        self.assertIn("_finish_feature_step", night_source)
        self.assertNotIn('vol.Required(\n                "night_enabled"', night_source)
        self.assertIn(
            '_optional_marker(\n                    "night_entity"',
            night_source,
        )
        self.assertIn("inline_safety_target", conditions_source)
        self.assertIn('_layers_with_function_targets("safety_")', conditions_source)
        self.assertIn("for key in target_keys", conditions_source)
        self.assertNotIn("async_step_initial_safety_targets", conditions_source)
        self.assertIn("_complete_initial_feature", conditions_source)

        profile_source = ast.get_source_segment(
            FLOW_PATH.read_text(encoding="utf-8"),
            _method(self.options_flow, "async_step_manage_layer_profile"),
        ) or ""
        self.assertIn("night=True", profile_source)

        initial_glare_source = ast.get_source_segment(
            FLOW_PATH.read_text(encoding="utf-8"),
            _method(self.mixin, "async_step_initial_glare_protection"),
        ) or ""
        self.assertIn(
            'self._sector_id = str(user_input["sector_id"])',
            initial_glare_source,
        )
        self.assertIn("elif len(sectors) == 1", initial_glare_source)
        self.assertIn(
            'step_id="initial_glare_protection"',
            initial_glare_source,
        )
        self.assertIn('vol.Required("sector_id")', initial_glare_source)

    def test_schedule_and_temperature_forms_show_the_complete_feature_once(self):
        source = ast.get_source_segment(
            FLOW_PATH.read_text(encoding="utf-8"),
            _method(self.options_flow, "async_step_manage_automation"),
        ) or ""

        self.assertNotIn('vol.Required(\n                "schedule_enabled"', source)
        self.assertNotIn("return await self._rerender_automation_feature()", source)
        for field in (
            "schedule_profile",
            "day_window",
            "active_months",
            "active_weekdays",
            "start_time",
            "end_time",
            "outside_schedule_behavior",
            "indoor_temperature",
            "heat_temperature",
        ):
            with self.subTest(field=field):
                self.assertIn(f'"{field}"', source)
        self.assertIn(
            'sections[vol.Required("temperature_settings")]', source
        )
        self.assertNotIn('"heat_outside_schedule"', source)

    def test_dynamic_choices_use_focused_follow_up_steps(self):
        source = FLOW_PATH.read_text(encoding="utf-8")
        automation = ast.get_source_segment(
            source,
            _method(self.options_flow, "async_step_manage_automation"),
        ) or ""
        sector_source = ast.get_source_segment(
            source,
            _method(self.options_flow, "async_step_manage_sector_source"),
        ) or ""
        source_details = ast.get_source_segment(
            source,
            _method(self.options_flow, "async_step_configure_sector_source"),
        ) or ""
        night = ast.get_source_segment(
            source,
            _method(self.options_flow, "async_step_manage_night"),
        ) or ""

        self.assertIn("for key, value in values.items()", automation)
        self.assertNotIn(
            "return await self._rerender_automation_feature()", automation
        )
        self.assertIn("async_step_configure_sector_source", sector_source)
        self.assertNotIn("async_step_manage_sector_source()", sector_source)
        self.assertIn('step_id="configure_sector_source"', source_details)
        self.assertNotIn("async_step_configure_sector_source()", source_details)
        night_change = night[night.index("source != current_source"):]
        self.assertLess(
            night_change.index('"night_morning_transition_minutes"'),
            night_change.index("return await self.async_step_manage_night()"),
        )

    def test_clearable_condition_sources_are_explicitly_cleared(self):
        source = ast.get_source_segment(
            FLOW_PATH.read_text(encoding="utf-8"),
            _method(self.options_flow, "async_step_manage_conditions"),
        ) or ""

        self.assertIn('values.get("safety_blockers") or []', source)
        self.assertIn('selected = str(values.get(key) or "")', source)
        self.assertIn("room[key] = selected", source)
        self.assertIn("occupancy_source_required", source)

    def test_final_review_rejects_an_enabled_night_without_a_source(self):
        navigation_imports = {
            alias.name
            for node in self.tree.body
            if isinstance(node, ast.ImportFrom)
            and node.module == "options_navigation"
            for alias in node.names
        }
        source = ast.get_source_segment(
            FLOW_PATH.read_text(encoding="utf-8"),
            next(
                node
                for node in self.config_flow.body
                if isinstance(node, ast.FunctionDef)
                and node.name == "_review_snapshot"
            ),
        ) or ""

        self.assertIn("night_is_configured", navigation_imports)
        self.assertIn('room.get("night_enabled")', source)
        self.assertIn("and not night_is_configured(room)", source)
        self.assertIn("night function has no valid source", source)
        self.assertIn('source == "lux"', source)
        self.assertIn('sector.get("lux_sensor", "")', source)
        self.assertIn('source == "external"', source)
        self.assertIn("CONF_SUN_PRESENCE_ENTITY", source)

        for step in (
            "async_step_manage_automation",
            "async_step_manage_night",
            "async_step_manage_pause",
            "async_step_manage_conditions",
        ):
            with self.subTest(shared_step=step):
                self.assertIn(
                    ("SmartShadingOptionsFlow", step),
                    _qualified_attribute_calls(_method(self.config_flow, step)),
                )

    def test_options_add_room_reuses_the_config_flow_room_form(self):
        option_method_names = [
            node.name
            for node in self.options_flow.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        self.assertNotIn("_async_step_room_setup", option_method_names)
        self.assertEqual(option_method_names.count("async_step_add_room"), 1)

        add_room = _method(self.options_flow, "async_step_add_room")
        self.assertIn(
            ("SmartShadingConfigFlow", "_async_step_room_setup"),
            _qualified_attribute_calls(add_room),
        )
        self.assertNotIn("async_show_form", _attribute_calls(add_room))

    def test_retired_global_settings_is_only_a_safe_redirect(self):
        global_settings = _method(self.mixin, "async_step_global_settings")
        self.assertEqual(set(), _vol_schema_names(global_settings))

        source = ast.get_source_segment(
            FLOW_PATH.read_text(encoding="utf-8"), global_settings
        )
        self.assertIsNotNone(source)
        self.assertIn("DEFAULT_SUN_ENTITY", source)
        self.assertIn("return await self.async_step_init()", source)

    def test_options_are_saved_without_the_immutable_mode(self):
        finish = _method(self.options_flow, "async_step_finish")
        call_names = {
            child.func.id
            for child in ast.walk(finish)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        }
        self.assertIn("editable_options", call_names)

    def test_mode_switch_copy_is_removed_from_global_settings(self):
        for language in ("de", "en"):
            with self.subTest(language=language):
                data = json.loads(
                    (COMP / "translations" / f"{language}.json").read_text(
                        encoding="utf-8"
                    )
                )
                unexpected_locations: list[str] = []
                for section in ("config", "options"):
                    global_settings = data[section]["step"]["global_settings"]
                    for field_group in ("data", "data_description"):
                        if "advanced_mode" in global_settings.get(
                            field_group, {}
                        ):
                            unexpected_locations.append(
                                f"{section}.global_settings.{field_group}"
                            )
                self.assertEqual([], unexpected_locations)


if __name__ == "__main__":
    unittest.main()
