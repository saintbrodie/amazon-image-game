import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_dataset import build_game_data, product_image, review_image  # noqa: E402


class BuildDatasetTests(unittest.TestCase):
    def test_image_helpers_prefer_best_available_size(self):
        self.assertEqual(
            review_image({"images": [{"small_image_url": "https://x/s", "large_image_url": "https://x/l"}]}),
            "https://x/l",
        )
        self.assertEqual(
            product_image({"images": [{"variant": "MAIN", "large": "https://x/product"}]}),
            "https://x/product",
        )

    def test_builds_playable_round_with_three_distractors(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            reviews = base / "reviews.jsonl"
            metadata = base / "meta.jsonl"

            review_rows = [
                {
                    "rating": 2.0,
                    "title": "Broke fast",
                    "text": "It lasted two days.",
                    "images": [{"large_image_url": "https://example.test/review.jpg"}],
                    "asin": "A1",
                    "parent_asin": "P1",
                    "verified_purchase": True,
                    "helpful_vote": 7,
                }
            ]
            meta_rows = [
                {"parent_asin": "P1", "title": "Mystery Widget", "main_category": "Widgets", "price": 12.5},
                {"parent_asin": "P2", "title": "Widget Deluxe", "main_category": "Widgets"},
                {"parent_asin": "P3", "title": "Widget Mini", "main_category": "Widgets"},
                {"parent_asin": "P4", "title": "Widget XL", "main_category": "Widgets"},
            ]
            reviews.write_text("\n".join(json.dumps(row) for row in review_rows), encoding="utf-8")
            metadata.write_text("\n".join(json.dumps(row) for row in meta_rows), encoding="utf-8")

            result = build_game_data(reviews, metadata, limit=1, seed=10, name="Test Data")

            self.assertEqual(result["name"], "Test Data")
            self.assertEqual(len(result["rounds"]), 1)
            round_data = result["rounds"][0]
            self.assertEqual(round_data["product"]["title"], "Mystery Widget")
            self.assertEqual(round_data["review_image"], "https://example.test/review.jpg")
            self.assertEqual(len(round_data["choices"]), 4)
            self.assertIn("Mystery Widget", round_data["choices"])
            self.assertEqual(round_data["helpful_vote"], 7)
            self.assertTrue(round_data["verified_purchase"])

    def test_limit_must_be_positive(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.jsonl"
            path.write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_game_data(path, path, limit=0)


if __name__ == "__main__":
    unittest.main()
