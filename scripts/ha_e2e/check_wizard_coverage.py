#!/usr/bin/env python3
"""Reject new customer flow surfaces or choices without an E2E owner."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import sys


ROOT = Path(__file__).parents[2]
FLOW = ROOT / "custom_components" / "smart_shading" / "config_flow.py"
CONSTANTS = ROOT / "custom_components" / "smart_shading" / "const.py"
FLOW_CONTRACT = ROOT / "custom_components" / "smart_shading" / "flow_contract.py"
COVERAGE = ROOT / "e2e" / "ha" / "scenarios" / "wizard_coverage.json"

# These surface IDs are selected dynamically instead of appearing as a literal
# async_show_form/async_show_menu keyword in the Python AST.
DYNAMIC_SURFACES = {
    "room_setup",
    "add_room",
    "structure_hub",
    "sector_hub",
    "group_hub",
    "initial_night_targets",
    "initial_safety_targets",
}


def literal_surfaces(tree: ast.AST) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"async_show_form", "async_show_menu"}:
            continue
        for keyword in node.keywords:
            if (
                keyword.arg == "step_id"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            ):
                result.add(keyword.value.value)
    return result


def choice_values(tree: ast.AST, variable: str) -> set[str]:
    """Read literal values passed to _choice(..., variable)."""
    result: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "_choice" or len(node.args) < 2:
            continue
        key = node.args[1]
        values = node.args[0]
        if not isinstance(key, ast.Constant) or key.value != variable:
            continue
        if isinstance(values, (ast.List, ast.Tuple)):
            for item in values.elts:
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    result.add(item.value)
    return result


def resolved_symbols(*paths: Path) -> dict[str, object]:
    """Resolve the string/list constants that own customer choice values."""
    assignments: list[ast.Assign] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assignments.extend(
            node for node in tree.body if isinstance(node, ast.Assign)
        )
    symbols: dict[str, object] = {}

    def evaluate(node: ast.AST) -> object:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return symbols[node.id]
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return [evaluate(item) for item in node.elts]
        raise ValueError

    pending = list(assignments)
    while pending:
        progress = False
        for node in pending[:]:
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                pending.remove(node)
                continue
            try:
                symbols[node.targets[0].id] = evaluate(node.value)
            except (KeyError, ValueError):
                continue
            pending.remove(node)
            progress = True
        if not progress:
            break
    return symbols


def main() -> int:
    tree = ast.parse(FLOW.read_text(encoding="utf-8"), filename=str(FLOW))
    contract = json.loads(COVERAGE.read_text(encoding="utf-8"))
    declared = set(contract["all_surfaces"])
    actual = literal_surfaces(tree) | DYNAMIC_SURFACES
    missing = sorted(actual - declared)
    stale = sorted(declared - actual)
    errors: list[str] = []
    if missing:
        errors.append(f"Flow surfaces missing E2E ownership: {missing}")
    if stale:
        errors.append(f"Stale E2E surface declarations: {stale}")

    symbols = resolved_symbols(CONSTANTS, FLOW_CONTRACT)
    source_contracts = {
        "setup_type": set(symbols["SETUP_TYPES"]),
        "direction_easy": set(symbols["DIRECTION_OPTIONS"]) - {"custom"},
        "direction_advanced": set(symbols["DIRECTION_OPTIONS"]),
        "sun_preset_easy": set(symbols["SUN_PRESET_OPTIONS"]) - {"custom"},
        "sun_preset_advanced": set(symbols["SUN_PRESET_OPTIONS"]),
        "profile": set(symbols["DEVICE_TYPES"]),
        "tilt_preset": set(symbols["TILT_PRESET_OPTIONS"]),
        "diagnostic_level": set(symbols["DIAGNOSTIC_OPTIONS"]),
        "schedule_profile": set(symbols["SCHEDULE_OPTIONS"]),
        "day_window": set(symbols["DAY_WINDOW_OPTIONS"]),
        "outside_schedule_behavior": set(symbols["OUTSIDE_OPTIONS"]),
        "pause_mode": set(symbols["PAUSE_OPTIONS"]) - {"auto"},
        "window_policy": set(symbols["WINDOW_POLICIES"]),
    }
    literal_contracts = {
        "sun_source": "sun_source",
        "night_source": "night_source",
        "safety_behavior": "safety_behavior",
        "weather_logic": "weather_logic",
        "window_safe_state": "safe_state",
    }
    for contract_key, actual_choices in source_contracts.items():
        expected = set(contract["choice_contract"][contract_key])
        if expected != actual_choices:
            errors.append(
                f"Choice contract {contract_key} differs from source: "
                f"declared={sorted(expected)}, source={sorted(actual_choices)}"
            )
    for contract_key, flow_key in literal_contracts.items():
        expected = set(contract["choice_contract"][contract_key])
        actual_choices = choice_values(tree, flow_key)
        if expected != actual_choices:
            errors.append(
                f"Choice contract {contract_key} differs from flow: "
                f"declared={sorted(expected)}, flow={sorted(actual_choices)}"
            )

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(
        f"Wizard coverage contract owns {len(actual)} customer flow surfaces"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
