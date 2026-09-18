import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AppSourceTests(unittest.TestCase):
    def test_daily_photo_mode_does_not_persist_over_normal_preference(self):
        source = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("normalMode: DEFAULT_MODE", source)
        self.assertIn('setMode("photo", { persist: false });', source)
        self.assertIn("setMode(state.normalMode);", source)
        self.assertIn("function setMode(mode, { persist = true } = {})", source)

    def test_app_prefers_manifest_catalog_and_lazy_round_loading(self):
        source = (ROOT / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('const MANIFEST_SOURCE = "data/rounds.manifest.json";', source)
        self.assertIn("const loader = await DatasetLoader.open", source)
        self.assertIn("state.catalog = loader.index", source)
        self.assertIn("await state.loader.loadEntries(entries)", source)
        self.assertIn("GameCore.dailyRounds(state.catalog, resolvedDate, 5)", source)
        self.assertIn('src="dataset-loader.js"', html)

    def test_app_ignores_stale_async_round_loads(self):
        source = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("const loadToken = ++state.loadToken;", source)
        self.assertIn("if (loadToken !== state.loadToken) return;", source)


if __name__ == "__main__":
    unittest.main()
