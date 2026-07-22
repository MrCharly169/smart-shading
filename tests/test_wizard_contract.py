from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
COMP = ROOT / "custom_components" / "smart_shading"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


contract = _load("smart_shading_wizard_contract", COMP / "wizard_contract.py")
const = _load("smart_shading_contract_const", COMP / "const.py")
migration = _load(
    "smart_shading_migration_contract", COMP / "migration_contract.py"
)


class WizardContractTests(unittest.TestCase):
    def test_easy_room_contains_only_name_and_optional_outdoor_temperature(self):
        self.assertEqual(
            contract.room_fields(False),
            ("name", "outdoor_temperature"),
        )
        self.assertNotIn("indoor_temperature", contract.room_fields(False))
        self.assertNotIn("safety_blockers", contract.room_fields(False))

    def test_advanced_room_adds_inputs_without_changing_the_automation(self):
        self.assertEqual(
            set(contract.room_fields(True)) - set(contract.room_fields(False)),
            {"indoor_temperature", "safety_blockers"},
        )
        self.assertIn("indoor_temperature_name", contract.room_fields(True, editing=True))
        self.assertEqual(
            contract.schedule_fields(False),
            ("schedule_profile", "default_pause_mode"),
        )
        self.assertEqual(
            set(contract.schedule_fields(True)) - set(contract.schedule_fields(False)),
            {"heat_during_pause"},
        )

    def test_easy_never_offers_custom_geometry_lux_or_tilt(self):
        for options in (
            const.DIRECTION_OPTIONS,
            const.SUN_PRESET_OPTIONS,
            const.TILT_PRESET_OPTIONS,
        ):
            self.assertNotIn("custom", contract.customer_options(options, False))
            self.assertIn("custom", contract.customer_options(options, True))

    def test_sun_confirmation_pages_are_mutually_exclusive(self):
        self.assertEqual(
            set(contract.SECTOR_IDENTITY_FIELDS),
            {"direction", "name", "short", "sun_source"},
        )
        self.assertEqual(
            set(contract.LUX_CONFIRMATION_FIELDS),
            {"lux_sensor", "sun_preset"},
        )
        self.assertEqual(
            contract.EXTERNAL_CONFIRMATION_FIELDS,
            ("sun_presence_entity",),
        )
        self.assertTrue(
            set(contract.LUX_CONFIRMATION_FIELDS).isdisjoint(
                contract.EXTERNAL_CONFIRMATION_FIELDS
            )
        )

    def test_every_cover_profile_exposes_only_supported_controls(self):
        for profile, capabilities in const.PROFILE_CAPABILITIES.items():
            fields = set(contract.cover_fields(capabilities))
            self.assertEqual(
                "max_open_position" in fields,
                capabilities["supports_position"],
                profile,
            )
            self.assertEqual(
                "invert_tilt" in fields,
                capabilities["supports_tilt"],
                profile,
            )
            self.assertEqual(
                contract.layer_has_advanced_settings(True, capabilities),
                not capabilities["binary"],
                profile,
            )
            self.assertFalse(
                contract.layer_has_advanced_settings(False, capabilities),
                profile,
            )

    def test_production_flow_consumes_the_executable_contract(self):
        flow = (COMP / "config_flow.py").read_text(encoding="utf-8")
        for name in (
            "contract_room_fields",
            "customer_options",
            "contract_cover_fields",
            "layer_has_advanced_settings",
            "contract_schedule_fields",
        ):
            self.assertIn(name, flow)

    def test_later_add_actions_cannot_bypass_the_compact_contract(self):
        tree = ast.parse(
            (COMP / "config_flow.py").read_text(encoding="utf-8")
        )
        methods = {
            node.name: ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertIn("async_step_compact_room", methods["async_step_add_room"])
        self.assertIn("async_step_compact_sector", methods["async_step_add_sector"])
        self.assertIn("async_step_compact_layer", methods["async_step_add_layer"])
        self.assertIn(
            "async_step_compact_cover_details", methods["async_step_add_covers"]
        )

    def test_v9_sun_sources_migrate_to_exactly_one_authoritative_source(self):
        both = {
            "lux_sensor": "sensor.legacy_lux",
            "sun_presence_entity": "binary_sensor.legacy_sun",
        }
        self.assertEqual(migration.normalize_sector_sun_source(both), "external")
        self.assertEqual(both["lux_sensor"], "")

        lux = {"lux_sensor": "sensor.legacy_lux"}
        self.assertEqual(migration.normalize_sector_sun_source(lux), "lux")
        self.assertEqual(lux["sun_presence_entity"], "")

        geometry = {}
        self.assertEqual(
            migration.normalize_sector_sun_source(geometry), "geometry"
        )
        self.assertEqual(geometry["lux_sensor"], "")
        self.assertEqual(geometry["sun_presence_entity"], "")


if __name__ == "__main__":
    unittest.main()
