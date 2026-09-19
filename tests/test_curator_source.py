import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CuratorSourceTests(unittest.TestCase):
    def test_screening_controls_and_script_are_present(self):
        html = (ROOT / "curate.html").read_text(encoding="utf-8")
        self.assertIn('id="screeningSelect"', html)
        self.assertIn('id="screeningRisk"', html)
        self.assertIn('id="screeningStatus"', html)
        self.assertIn('id="screeningFlags"', html)
        self.assertIn('src="curate-screening.js"', html)

    def test_curator_filters_sorts_and_renders_screening(self):
        source = (ROOT / "curate.js").read_text(encoding="utf-8")
        self.assertIn('screening: "all"', source)
        self.assertIn("CuratorScreening.matches(round, state.screening)", source)
        self.assertIn('state.sort === "screening"', source)
        self.assertIn("CuratorScreening.riskScore", source)
        self.assertIn("renderScreening(round);", source)
        self.assertIn("CuratorScreening.needsReview", source)


if __name__ == "__main__":
    unittest.main()
