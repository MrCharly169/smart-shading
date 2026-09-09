"""Exercise per-user native flow presentation with a conflicting server locale."""
from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

import voluptuous as vol

COMP = Path(__file__).parents[1] / "custom_components/smart_shading"
spec = importlib.util.spec_from_file_location("flow_language", COMP / "flow_language.py")
language = importlib.util.module_from_spec(spec)
spec.loader.exec_module(language)


class NativeBase:
    def async_show_menu(self, **values):
        return {"type": "menu", **values}

    def async_show_form(self, **values):
        return {"type": "form", **values}


class NativeSelector:
    def __init__(self, config):
        if "options" in config:
            options = config["options"]
            assert all(isinstance(item, str) for item in options) or all(isinstance(item, dict) for item in options)
        self.config = config

    def __call__(self, value):
        return value


def wizard_class():
    tree = ast.parse((COMP / "config_flow.py").read_text())
    mixin = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "_SmartShadingWizardMixin")
    methods = {"async_show_menu", "_native_navigation_form", "async_step_native_navigation", "_is_german",
               "_feature_labels", "_feature_context_placeholders", "_new_feature_placeholders", "_choice"}
    mixin.body = [n for n in mixin.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in methods]
    namespace = {"bilingual_placeholders": language.bilingual_placeholders, "vol": vol,
                 "selector": SimpleNamespace(SelectSelector=NativeSelector, SelectSelectorConfig=dict)}
    for node in ast.parse((COMP / "const.py").read_text()).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            try:
                namespace[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    select = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_select")
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), select, mixin], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), "<actual flow methods>", "exec"), namespace)
    class Wizard(namespace["_SmartShadingWizardMixin"], NativeBase):
        _room_id = "room"
        advanced_mode = True
        _option_routes = {}
        rooms = [{"id": "room", "name": "Living Area", "sectors": []}]
        hass = SimpleNamespace(config=SimpleNamespace(language="de"))
        def _option_placeholders(self):
            return {"room_name": "Living Area"}
        def _initial_feature_queue(self):
            return ["night", "temperature"]
    return Wizard


class UserLanguageTests(unittest.TestCase):
    def setUp(self):
        self.wizard = wizard_class()()
        self.catalogs = {lang: json.loads((COMP / "translations" / f"{lang}.json").read_text()) for lang in ("en", "de")}

    def test_native_static_menu_translates_for_each_viewer(self):
        result = self.wizard.async_show_menu(step_id="init", menu_options={"add_room": "Raum hinzufügen"})
        self.assertEqual(result["menu_options"], ["add_room"])
        texts = [self.catalogs[lang]["options"]["step"]["init"]["menu_options"][result["menu_options"][0]] for lang in ("en", "de")]
        self.assertEqual(texts, ["Add room", "Raum hinzufügen"])

    def test_dynamic_navigation_preserves_names_and_translates_actions(self):
        self.wizard._option_routes = {
            "hash1": {"action": "room_hub", "room_id": "room"},
            "hash2": {"action": "manage_room_details", "room_id": "room"},
        }
        result = self.wizard.async_show_menu(step_id="init", menu_options={
            "manage_hash1": "Raum · Living Area", "manage_hash2": "Raumdaten · Living Area", "add_room": "Raum hinzufügen"})
        schema = result["data_schema"]
        select = next(iter(getattr(schema, "schema", schema).values()))
        self.assertEqual(select.config["options"], [
            {"value": "manage_hash1", "label": "Living Area"},
            {"value": "manage_room_details", "label": "Raumdaten · Living Area"},
            {"value": "add_room", "label": "Raum hinzufügen"}])
        self.assertEqual(select.config["translation_key"], "navigation_action")
        for lang,expected in (("en", "Room details"), ("de", "Raumdaten")):
            self.assertEqual(self.catalogs[lang]["selector"]["navigation_action"]["options"]["manage_room_details"], expected)
        async def selected():
            return "original stable route"
        self.wizard.async_step_manage_hash2 = selected
        self.assertEqual(asyncio.run(self.wizard.async_step_native_navigation({"route":"manage_room_details"})), "original stable route")
        invalid = asyncio.run(self.wizard.async_step_native_navigation({"route":"stale"}))
        self.assertEqual(invalid["errors"], {"base":"invalid_navigation"})

    def test_same_summary_supports_simultaneous_users(self):
        self.wizard._initial_setup = True
        values = self.wizard._feature_context_placeholders("night")
        self.assertEqual(values["feature_name__en"], "Night mode")
        self.assertEqual(values["feature_name__de"], "Nachtfunktion")
        self.assertIn("Additional feature", values["feature_progress__en"])
        self.assertIn("Zusatzfunktion", values["feature_progress__de"])
        for lang in ("en", "de"):
            for section in ("config", "options"):
                description = self.catalogs[lang][section]["step"]["manage_night"]["description"]
                title = self.catalogs[lang][section]["step"]["manage_night"]["title"]
                rendered = (title + " " + description).format(**values)
                self.assertIn(values[f"feature_name__{lang}"], rendered)
        self.assertEqual(self.wizard.hass.config.language, "de")
        self.assertEqual(self.wizard._copy_language, "en")

    def test_each_glare_sector_retains_its_own_route(self):
        self.wizard.rooms = [{"id": "room", "name": "Living Area", "sectors": [
            {"id": "west", "name": "West"}, {"id": "south", "name": "South"}]}]
        self.wizard._option_routes = {
            key: {"action": "protected_zones_hub", "room_id": "room", "sector_id": key}
            for key in ("west", "south")}
        result = self.wizard.async_show_menu(step_id="glare_protection_hub", menu_options={
            "manage_west": "West · 1 Zone", "manage_south": "South · 2 Zonen", "back_to_room": "Zurück"})
        self.assertEqual(self.wizard._native_navigation_choices[:2], [
            {"value": "manage_west", "label": "West"}, {"value": "manage_south", "label": "South"}])
        self.assertEqual(result["description_placeholders"]["navigation_step"], "glare_protection_hub")

    def test_e2e_navigation_adapter_keeps_real_schema_and_route_identity(self):
        tree = ast.parse((COMP.parents[1] / "scripts/ha_e2e/run_scenarios.py").read_text())
        method = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "navigation_surface")
        namespace = {"Any": object}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "<actual E2E adapter>", "exec"), namespace)
        schema = [{"name": "route", "selector": {"select": {
            "translation_key": "navigation_action", "options": ["add_protected_zone",
                {"value": "manage_west", "label": "Table"}, "back_to_sector"]}}}]
        raw = {"type": "form", "step_id": "native_navigation", "data_schema": schema,
               "description_placeholders": {"navigation_step": "protected_zones_hub"}}
        result = namespace["navigation_surface"](raw)
        self.assertEqual(raw["type"], "form")
        self.assertIs(result["data_schema"], schema)
        self.assertEqual(result["step_id"], "protected_zones_hub")
        self.assertEqual(result["menu_options"]["manage_west"], "Table")
        self.assertTrue(result["menu_options"]["add_protected_zone"].startswith("+"))

    def test_profiles_use_native_translation_keys_with_advanced_values(self):
        choice = self.wizard._choice(["medium"], "sun_preset")
        self.assertEqual(choice.config["translation_key"], "sun_preset_advanced")
        for lang in ("en", "de"):
            catalog = self.catalogs[lang]["selector"]
            self.assertIn("lx", catalog["sun_preset_advanced"]["options"]["medium"])
            self.assertNotIn("lx", catalog["sun_preset"]["options"]["medium"])

    def test_no_entity_name_override_blocks_native_translations(self):
        for filename in ("button.py", "switch.py", "sensor.py", "select.py", "number.py", "binary_sensor.py"):
            source = ast.parse((COMP / filename).read_text())
            assignments = [n for n in ast.walk(source) if isinstance(n, ast.Assign) and any(
                getattr(t, "attr", None) == "_attr_name" or getattr(t, "id", None) == "_attr_name" for t in n.targets)]
            self.assertEqual(assignments, [], filename)
