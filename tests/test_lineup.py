import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import lineup


class LineupTests(unittest.TestCase):
    def test_sample_roster_maps_to_standard_xi(self):
        players = lineup.load_roster(Path(__file__).parents[1] / "data" / "roster.csv")
        selected = lineup.select_starting_xi(players)
        self.assertEqual(set(selected), set(lineup.ACTIVE_POSITIONS))
        self.assertEqual(selected["GK"].name, "Andre Onana")
        self.assertIn(selected["CDM-L"].name, {"Casemiro", "Kalvin Phillips"})
        self.assertIn(selected["CDM-R"].name, {"Casemiro", "Kalvin Phillips"})
        self.assertNotEqual(selected["CDM-L"].name, selected["CDM-R"].name)

    def test_flex_positions_are_additional_slots(self):
        players = lineup.load_roster(Path(__file__).parents[1] / "data" / "roster.csv")
        selected = lineup.select_starting_xi(players, include_flex=True)
        self.assertEqual(len(selected), 13)
        self.assertIn("CF", selected)
        self.assertIn("LM/W", selected)

    def test_yaml_roster_support(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "roster.yaml"
            path.write_text("players:\n  - name: YAML Player\n    position: GK\n", encoding="utf-8")
            players = lineup.load_roster(path)
        self.assertEqual(players[0].name, "YAML Player")
        self.assertEqual(players[0].position, "GK")

    def test_overrides_by_name_and_club(self):
        player = lineup.Player(name="A Player", position="ST", club="Some Club", club_code="SC")
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "overrides.json"
            config.write_text(json.dumps({
                "players": {"A Player": {"display_name": "MEME NAME"}},
                "clubs": {"Some Club": "LOL"},
            }), encoding="utf-8")
            result = lineup.apply_overrides([player], config)[0]
        self.assertEqual(result.display_name, "MEME NAME")
        self.assertEqual(result.club_code, "LOL")

    def test_render_uses_fallback_assets_and_expected_canvas(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            lineup.ensure_directories(root)
            output = root / "out.png"
            full_xi = lineup.select_starting_xi(
                lineup.load_roster(Path(__file__).parents[1] / "data" / "roster.csv")
            )
            lineup.render_graphic(full_xi, output, root, league_label="Test League")
            with Image.open(output) as rendered:
                self.assertEqual(rendered.size, lineup.CANVAS_SIZE)
                self.assertEqual(rendered.mode, "RGB")

    def test_position_normalization_for_requested_slot_names(self):
        self.assertEqual(lineup.canonical_position("CDM-L"), "CDM")
        self.assertEqual(lineup.canonical_position("LM/W"), "WING")
        self.assertEqual(lineup.canonical_position("CB1"), "CB")


if __name__ == "__main__":
    unittest.main()
