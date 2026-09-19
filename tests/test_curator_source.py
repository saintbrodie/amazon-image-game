import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CuratorSourceTests(unittest.TestCase):
    def test_screening_controls_and_loader_scripts_are_present(self):
        html = (ROOT / "curate.html").read_text(encoding="utf-8")
        self.assertIn('id="screeningSelect"', html)
        self.assertIn('id="screeningRisk"', html)
        self.assertIn('id="screeningStatus"', html)
        self.assertIn('id="screeningFlags"', html)
        self.assertIn('src="dataset-loader.js"', html)
        self.assertIn('src="curate-screening.js"', html)

    def test_curator_filters_sorts_and_renders_screening(self):
        source = (ROOT / "curate.js").read_text(encoding="utf-8")
        self.assertIn('screening: "all"', source)
        self.assertIn("CuratorScreening.matches(round, state.screening)", source)
        self.assertIn('state.sort === "screening"', source)
        self.assertIn("CuratorScreening.riskScore", source)
        self.assertIn("renderScreening(round);", source)
        self.assertIn("CuratorScreening.needsReview", source)

    def test_curator_selects_from_catalog_then_lazy_loads_current_round(self):
        source = (ROOT / "curate.js").read_text(encoding="utf-8")
        self.assertIn('const MANIFEST_SOURCE = "data/rounds.manifest.json";', source)
        self.assertIn("const loader = await DatasetLoader.open", source)
        self.assertIn("state.rounds = loader.index;", source)
        self.assertIn("const [round] = await state.loader.loadEntries([entry]);", source)
        self.assertIn("const renderToken = ++state.renderToken;", source)
        self.assertIn("if (renderToken !== state.renderToken) return;", source)
        self.assertNotIn("async function loadDataset()", source)


if __name__ == "__main__":
    unittest.main()
