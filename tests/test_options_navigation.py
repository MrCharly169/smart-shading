from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
MODULE = ROOT / "custom_components" / "smart_shading" / "options_navigation.py"
spec = importlib.util.spec_from_file_location("smart_shading_options_navigation", MODULE)
navigation = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(navigation)


def _room(room_id: str, name: str) -> dict:
    return {
        "id": room_id,
        "name": name,
        "night_enabled": False,
        "sectors": [
            {
                "id": f"{room_id}_south",
                "name": "South",
                "layers": [
                    {
                        "id": f"{room_id}_windows",
                        "name": "Windows",
                        "covers": [
                            {"entity": f"cover.{room_id}_left", "name": "Left"},
                            {"entity": f"cover.{room_id}_right", "name": "Right"},
                        ],
                    }
                ],
            }
        ],
    }


class OptionsNavigationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rooms = [_room("living", "Living"), _room("office", "Office")]

    def test_main_navigation_contains_exactly_one_route_per_room(self):
        routes = navigation.build_main_room_routes(self.rooms, german=False)
        self.assertEqual(len(routes), len(self.rooms))
        self.assertEqual([r["room_id"] for r in routes], ["living", "office"])
        self.assertTrue(all(r["action"] == "room_hub" for r in routes))

    def test_nested_objects_never_change_the_main_navigation(self):
        before = navigation.build_main_room_routes(self.rooms, german=False)
        changed = deepcopy(self.rooms)
        changed[0]["sectors"].append({"id": "west", "name": "West", "layers": []})
        self.assertEqual(navigation.build_main_room_routes(changed, german=False), before)

    def test_room_navigation_contains_tasks_not_internal_objects(self):
        routes = navigation.build_room_routes(
            self.rooms[0], german=False, full=True
        )
        self.assertEqual(
            [route["action"] for route in routes],
            [
                "manage_room_details", "sector_hub", "group_hub", "cover_hub",
                "manage_automation", "manage_night", "manage_pause",
                "manage_conditions", "manage_room_maintenance",
            ],
        )
        labels = " ".join(route["label"] for route in routes)
        self.assertIn("Room details · Living", labels)
        self.assertIn("Sun sectors · 1", labels)
        self.assertIn("Cover groups · 1", labels)
        self.assertIn("Individual covers · 2", labels)
        self.assertNotIn("South / Windows", labels)

    def test_simple_room_hides_unavailable_function_categories(self):
        actions = [
            route["action"]
            for route in navigation.build_room_routes(
                self.rooms[0], german=False, full=False
            )
        ]
        self.assertNotIn("manage_night", actions)
        self.assertNotIn("manage_pause", actions)
        self.assertEqual(actions[:4], [
            "manage_room_details", "sector_hub", "group_hub", "cover_hub"
        ])

    def test_object_categories_have_one_add_action_and_scoped_items(self):
        sectors = navigation.build_sector_routes(self.rooms[0], german=False)
        groups = navigation.build_group_routes(self.rooms[0], german=False)
        covers = navigation.build_cover_routes(self.rooms[0], german=False)
        self.assertEqual([r["action"] for r in sectors], ["add_sector_flat", "manage_sector", "add_sector_flat"])
        self.assertEqual([r["action"] for r in groups], ["choose_sector_for_group", "manage_layer", "choose_sector_for_group"])
        self.assertEqual(
            [r["action"] for r in covers],
            ["choose_group_for_covers", "manage_cover", "manage_cover", "choose_group_for_covers"],
        )
        self.assertTrue(all(r["room_id"] == "living" for r in sectors + groups + covers))
        self.assertNotIn("placement", sectors[0])
        self.assertEqual(sectors[-1]["placement"], "bottom")
        self.assertNotIn("placement", groups[0])
        self.assertEqual(groups[-1]["placement"], "bottom")
        self.assertNotIn("placement", covers[0])
        self.assertEqual(covers[-1]["placement"], "bottom")

    def test_cover_routes_keep_stable_entity_identity(self):
        routes = navigation.build_cover_routes(self.rooms[0], german=False)
        cover_routes = [route for route in routes if route["action"] == "manage_cover"]
        self.assertEqual(
            [route["cover_entity"] for route in cover_routes],
            ["cover.living_left", "cover.living_right"],
        )
        self.assertEqual([route["cover_index"] for route in cover_routes], [0, 1])

    def test_legacy_cover_without_name_never_exposes_raw_entity_id(self):
        room = self.rooms[0]
        room["sectors"][0]["layers"][0]["covers"][0].update(
            {"name": "", "entity": "cover.living_room_left"}
        )

        routes = navigation.build_cover_routes(room, german=False)

        cover_route = next(
            route for route in routes if route["action"] == "manage_cover"
        )
        self.assertEqual(cover_route["label"], "Cover 1 · Windows")
        self.assertNotIn("_", cover_route["label"])

    def test_next_night_pause_requires_complete_night_source(self):
        room = self.rooms[0]
        self.assertNotIn("next_night_end", navigation.pause_modes_for_room(room))
        room.update({"night_enabled": True, "night_source": "entity", "night_entity": ""})
        self.assertNotIn("next_night_end", navigation.pause_modes_for_room(room))
        room["night_entity"] = "schedule.living_night"
        self.assertIn("next_night_end", navigation.pause_modes_for_room(room))
        room.update({"night_source": "sun", "night_entity": ""})
        self.assertIn("next_night_end", navigation.pause_modes_for_room(room))


if __name__ == "__main__":
    unittest.main()
