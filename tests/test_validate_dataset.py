import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_dataset import validate_payload  # noqa: E402


class ValidateDatasetTests(unittest.TestCase):
    def test_valid_payload_passes(self):
        payload = {
            "rounds": [
                {
                    "id": "r1",
                    "review_image": "assets/demo/example.svg",
                    "rating": 4,
                    "product": {"title": "Correct", "parent_asin": "P1"},
                    "choices": ["Correct", "Wrong A", "Wrong B", "Wrong C"],
                }
            ]
        }
        self.assertEqual(validate_payload(payload), [])

    def test_duplicate_product_and_missing_correct_answer_fail(self):
        payload = {
            "rounds": [
                {
                    "id": "r1",
                    "review_image": "https://x/1.jpg",
                    "product": {"title": "Correct", "parent_asin": "P1"},
                    "choices": ["Correct", "A", "B", "C"],
                },
                {
                    "id": "r2",
                    "review_image": "https://x/2.jpg",
                    "product": {"title": "Another", "parent_asin": "P1"},
                    "choices": ["Nope", "A", "B", "C"],
                },
            ]
        }
        errors = validate_payload(payload)
        self.assertTrue(any("parent_asin duplicates" in error for error in errors))
        self.assertTrue(any("does not include the correct product title" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
