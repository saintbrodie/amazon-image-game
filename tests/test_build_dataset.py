import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_dataset import (  # noqa: E402
    build_game_data,
    normalize_product,
    parse_price,
    product_image,
    review_image,
    title_similarity,
)


class BuildDatasetTests(unittest.TestCase):
    def test_review_image_prefers_largest_size(self):
        self.assertEqual(
            review_image({"images": [{"small_image_url": "https://x/s", "large_image_url": "https://x/l"}]}),
            "https://x/l",
        )

    def test_product_image_supports_list_of_dicts(self):
        self.assertEqual(
            product_image(
                {
                    "images": [
                        {"variant": "PT01", "hi_res": "https://x/detail"},
                        {"variant": "MAIN", "large": "https://x/main"},
                    ]
                }
            ),
            "https://x/main",
        )

    def test_product_image_supports_dict_of_lists(self):
        self.assertEqual(
            product_image(
                {
                    "images": {
                        "hi_res": [None, "https://x/main-hi"],
                        "large": ["https://x/detail", "https://x/main"],
                        "variant": ["PT01", "MAIN"],
                    }
                }
            ),
            "https://x/main-hi",
        )

    def test_price_parsing_handles_dataset_strings(self):
        self.assertEqual(parse_price("$1,299.50"), 1299.5)
        self.assertEqual(parse_price("14.99"), 14.99)
        self.assertIsNone(parse_price("None"))
        self.assertIsNone(parse_price(None))

    def test_normalize_product_keeps_hierarchy(self):
        product = normalize_product(
            {
                "parent_asin": "P1",
                "title": "Cat Drinking Fountain",
                "main_category": "Pet Supplies",
                "categories": ["Cats", "Feeding & Watering Supplies", "Fountains"],
                "price": "29.99",
            }
        )
        self.assertIsNotNone(product)
        self.assertEqual(product["leaf_category"], "Fountains")
        self.assertEqual(product["category_path"][-1], "Fountains")
        self.assertEqual(product["price"], 29.99)

    def test_title_similarity_flags_near_duplicates(self):
        near = title_similarity("Automatic Cat Water Fountain Stainless Steel", "Stainless Steel Cat Water Fountain Automatic")
        far = title_similarity("Automatic Cat Water Fountain", "Cordless Impact Driver Kit")
        self.assertGreater(near, 0.7)
        self.assertLess(far, 0.2)

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
                    "timestamp": 1700000000000,
                }
            ]
            meta_rows = [
                {
                    "parent_asin": "P1",
                    "title": "Mystery Widget",
                    "main_category": "Widgets",
                    "categories": ["Widgets", "Indoor Widgets"],
                    "price": "12.50",
                },
                {"parent_asin": "P2", "title": "Widget Deluxe", "main_category": "Widgets", "categories": ["Widgets", "Indoor Widgets"]},
                {"parent_asin": "P3", "title": "Widget Mini", "main_category": "Widgets", "categories": ["Widgets", "Indoor Widgets"]},
                {"parent_asin": "P4", "title": "Widget XL", "main_category": "Widgets", "categories": ["Widgets", "Indoor Widgets"]},
                {"parent_asin": "P5", "title": "Outdoor Gizmo", "main_category": "Widgets", "categories": ["Widgets", "Outdoor"]},
            ]
            reviews.write_text("\n".join(json.dumps(row) for row in review_rows), encoding="utf-8")
            metadata.write_text("\n".join(json.dumps(row) for row in meta_rows), encoding="utf-8")

            result = build_game_data(
                reviews,
                metadata,
                limit=1,
                seed=10,
                name="Test Data",
                source_category="Test_Category",
            )

            self.assertEqual(result["version"], 2)
            self.assertEqual(result["name"], "Test Data")
            self.assertEqual(len(result["rounds"]), 1)
            round_data = result["rounds"][0]
            self.assertEqual(round_data["source_category"], "Test_Category")
            self.assertEqual(round_data["product"]["title"], "Mystery Widget")
            self.assertEqual(round_data["product"]["price"], 12.5)
            self.assertEqual(round_data["review_image"], "https://example.test/review.jpg")
            self.assertEqual(len(round_data["choices"]), 4)
            self.assertIn("Mystery Widget", round_data["choices"])
            self.assertEqual(round_data["helpful_vote"], 7)
            self.assertTrue(round_data["verified_purchase"])

    def test_one_round_per_parent_product(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            reviews = base / "reviews.jsonl"
            metadata = base / "meta.jsonl"
            reviews.write_text(
                "\n".join(
                    json.dumps(row)
                    for row in [
                        {"images": [{"large_image_url": "https://x/1.jpg"}], "asin": "A1", "parent_asin": "P1"},
                        {"images": [{"large_image_url": "https://x/2.jpg"}], "asin": "A2", "parent_asin": "P1"},
                    ]
                ),
                encoding="utf-8",
            )
            metadata.write_text(
                "\n".join(
                    json.dumps(row)
                    for row in [
                        {"parent_asin": "P1", "title": "Correct Thing", "main_category": "Things"},
                        {"parent_asin": "P2", "title": "Wrong Thing A", "main_category": "Things"},
                        {"parent_asin": "P3", "title": "Wrong Thing B", "main_category": "Things"},
                        {"parent_asin": "P4", "title": "Wrong Thing C", "main_category": "Things"},
                    ]
                ),
                encoding="utf-8",
            )
            result = build_game_data(reviews, metadata, limit=10, seed=4)
            self.assertEqual(len(result["rounds"]), 1)

    def test_limit_must_be_positive(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.jsonl"
            path.write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_game_data(path, path, limit=0)


if __name__ == "__main__":
    unittest.main()
