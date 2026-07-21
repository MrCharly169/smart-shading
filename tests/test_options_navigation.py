from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
MODULE = (
    ROOT
    / "custom_components"
    / "smart_shading"
    / "options_navigation.py"
)
spec = importlib.util.spec_from_file_location("smart_shading_options_navigation", MODULE)
navigation = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(navigation)


def _room(room_id: str, name: str) -> dict:
    return {
        "id": room_id,
        "name": name,
        "sectors": [
            {
                "id": f"{room_id}_south",
                "name": "South",
                "layers": [
                    {
                        "id": f"{room_id}_windows",
                        "name": "Windows",
                        "covers": [
                            {
                                "entity": f"cover.{room_id}_left",
                                "name": "Left",
                            },
                            {
                                "entity": f"cover.{room_id}_right",
                                "name": "Right",
                            },
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
        self.assertEqual(
            [route["room_id"] for route in routes], ["living", "office"]
        )
        self.assertTrue(all(route["action"] == "room_hub" for route in routes))
        self.assertTrue(
            all(
                set(route) == {"label", "action", "room_id"}
                for route in routes
            )
        )

    def test_nested_objects_never_change_the_main_navigation(self):
        before = navigation.build_main_room_routes(self.rooms, german=False)
        changed = deepcopy(self.rooms)
        changed[0]["sectors"].append(
            {
                "id": "living_west",
                "name": "West",
                "layers": [
                    {
                        "id": "living_west_doors",
                        "name": "Doors",
                        "covers": [{"entity": "cover.terrace", "name": "Terrace"}],
                    }
                ],
            }
        )

        self.assertEqual(
            navigation.build_main_room_routes(changed, german=False), before
        )

    def test_room_navigation_is_scoped_and_complete(self):
        routes = navigation.build_room_routes(self.rooms[0], german=False)

        self.assertTrue(all(route["room_id"] == "living" for route in routes))
        self.assertNotIn("office", " ".join(route["label"] for route in routes))
        self.assertEqual(
            [route["action"] for route in routes],
            [
                "manage_room",
                "add_sector_flat",
                "manage_sector",
                "add_layer_flat",
                "manage_layer",
                "add_covers_flat",
                "manage_cover",
                "manage_cover",
            ],
        )
        self.assertTrue(all(not route["label"].startswith(" ") for route in routes))

    def test_customer_labels_are_localized_without_fake_indentation(self):
        english = navigation.build_room_routes(self.rooms[0], german=False)
        german = navigation.build_room_routes(self.rooms[0], german=True)

        self.assertEqual(english[0]["label"], "Room settings")
        self.assertEqual(german[0]["label"], "Raumeinstellungen")
        self.assertIn("Add sun sector", english[1]["label"])
        self.assertIn("Sonnensektor hinzufügen", german[1]["label"])
        self.assertIn("Cover · Windows / Left", english[-2]["label"])
        self.assertIn("Behang · Windows / Left", german[-2]["label"])


if __name__ == "__main__":
    unittest.main()
