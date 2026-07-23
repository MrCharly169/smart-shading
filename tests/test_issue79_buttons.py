from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest


ROOT = Path(__file__).parents[1]
COMPONENT = ROOT / "custom_components" / "smart_shading"
PACKAGE = "issue79_button_component"


def _load_module(fullname: str, path: Path):
    spec = importlib.util.spec_from_file_location(fullname, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[fullname] = module
    spec.loader.exec_module(module)
    return module


def _install_home_assistant_stubs() -> None:
    homeassistant = types.ModuleType("homeassistant")
    components = types.ModuleType("homeassistant.components")
    button = types.ModuleType("homeassistant.components.button")
    helpers = types.ModuleType("homeassistant.helpers")
    entity = types.ModuleType("homeassistant.helpers.entity")
    device_registry = types.ModuleType("homeassistant.helpers.device_registry")
    exceptions = types.ModuleType("homeassistant.exceptions")

    class ButtonEntity:
        pass

    class Entity:
        pass

    class EntityCategory:
        DIAGNOSTIC = "diagnostic"

    class DeviceInfo(dict):
        pass

    class HomeAssistantError(Exception):
        pass

    button.ButtonEntity = ButtonEntity
    entity.Entity = Entity
    entity.EntityCategory = EntityCategory
    device_registry.DeviceInfo = DeviceInfo
    exceptions.HomeAssistantError = HomeAssistantError
    sys.modules.update(
        {
            "homeassistant": homeassistant,
            "homeassistant.components": components,
            "homeassistant.components.button": button,
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.entity": entity,
            "homeassistant.helpers.device_registry": device_registry,
            "homeassistant.exceptions": exceptions,
        }
    )


_install_home_assistant_stubs()
package = types.ModuleType(PACKAGE)
package.__path__ = [str(COMPONENT)]
sys.modules[PACKAGE] = package
_load_module(f"{PACKAGE}.const", COMPONENT / "const.py")
_load_module(f"{PACKAGE}.entity", COMPONENT / "entity.py")
button_module = _load_module(f"{PACKAGE}.button", COMPONENT / "button.py")


class _Engine:
    def __init__(self, *, advanced_mode: bool = True, test_tools: bool = True) -> None:
        self.advanced_mode = advanced_mode
        self.entry = types.SimpleNamespace(entry_id="entry", title="Test")
        self.hass = types.SimpleNamespace(config=types.SimpleNamespace(language="en"))
        self.diagnostic_level = "off"
        self.rooms = {"room": types.SimpleNamespace(name="Room")}
        self.config = {"rooms": [{"id": "room", "sectors": []}]}
        self.simulations: list[str] = []
        self.previews: list[str] = []
        self.evaluations: list[str] = []
        self.test_tools = test_tools

    def room_test_tools_enabled(self, room_id: str) -> bool:
        return self.test_tools

    async def async_simulate_room(self, room_id: str) -> None:
        self.simulations.append(room_id)

    async def async_preview_room_day(self, room_id: str) -> None:
        self.previews.append(room_id)

    async def async_evaluate_all(self, trigger: str) -> None:
        self.evaluations.append(trigger)


class Issue79ButtonTests(unittest.TestCase):
    def test_advanced_entities_run_only_non_actuating_apis(self) -> None:
        engine = _Engine()
        entities = []
        asyncio.run(
            button_module.async_setup_entry(
                None,
                types.SimpleNamespace(runtime_data=engine),
                entities.extend,
            )
        )

        simulation = next(
            entity
            for entity in entities
            if isinstance(entity, button_module.SimulateRoomButton)
        )
        preview = next(
            entity
            for entity in entities
            if isinstance(entity, button_module.PreviewRoomDayButton)
        )
        self.assertEqual(
            simulation.extra_state_attributes["smart_shading_control_key"],
            "simulate",
        )
        self.assertEqual(
            preview.extra_state_attributes["smart_shading_control_key"],
            "preview_day",
        )

        asyncio.run(simulation.async_press())
        asyncio.run(preview.async_press())
        self.assertEqual(engine.simulations, ["room"])
        self.assertEqual(engine.previews, ["room"])
        self.assertEqual(engine.evaluations, [])

    def test_easy_mode_and_unavailable_adapters_are_safe(self) -> None:
        easy_engine = _Engine(advanced_mode=False)
        entities = []
        asyncio.run(
            button_module.async_setup_entry(
                None,
                types.SimpleNamespace(runtime_data=easy_engine),
                entities.extend,
            )
        )
        self.assertEqual(entities, [])

        engine = _Engine()
        engine.async_simulate_room = None
        engine.async_preview_room_day = None
        with self.assertRaises(button_module.HomeAssistantError):
            asyncio.run(button_module.SimulateRoomButton(engine, "room").async_press())
        with self.assertRaises(button_module.HomeAssistantError):
            asyncio.run(button_module.PreviewRoomDayButton(engine, "room").async_press())
        self.assertEqual(engine.evaluations, [])

    def test_existing_advanced_rooms_do_not_receive_test_tools_without_opt_in(self) -> None:
        engine = _Engine(test_tools=False)
        entities = []
        asyncio.run(
            button_module.async_setup_entry(
                None,
                types.SimpleNamespace(runtime_data=engine),
                entities.extend,
            )
        )
        self.assertFalse(any(isinstance(entity, button_module.SimulateRoomButton) for entity in entities))
        self.assertFalse(any(isinstance(entity, button_module.PreviewRoomDayButton) for entity in entities))
        self.assertEqual(len(entities), 2)
