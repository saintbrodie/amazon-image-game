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


if __name__ == "__main__":
    unittest.main()
