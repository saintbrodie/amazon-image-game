import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from screen_dataset import analyze_round, screen_dataset, text_flags  # noqa: E402


def make_round(round_id: str, text: str) -> dict:
    return {
        "id": round_id,
        "review_image": "https://example.test/image.jpg",
        "review_title": "Review",
        "review_text": text,
        "rating": 5,
        "product": {"title": "Mystery Product"},
        "choices": ["Mystery Product", "A", "B", "C"],
    }


class ScreenDatasetTests(unittest.TestCase):
    def test_contact_information_gets_high_severity_flags(self):
        flags = text_flags(make_round("one", "Email me at person@example.com or call 813-555-1212."))
        names = {flag["name"] for flag in flags}
        self.assertIn("contact_email", names)
        self.assertIn("contact_phone", names)
        self.assertTrue(all(flag["severity"] == "high" for flag in flags))

        sentence_flags = text_flags(make_round("sentence", "Contact me at person@example.com."))
        self.assertIn("contact_email", {flag["name"] for flag in sentence_flags})

    def test_url_social_and_coordinates_are_flagged(self):
        result = analyze_round(
            make_round(
                "two",
                "See https://example.com/details and @sample_user. Pickup was at 27.9506, -82.4572.",
            )
        )
        names = {flag["name"] for flag in result["flags"]}
        self.assertIn("external_url", names)
        self.assertIn("social_handle", names)
        self.assertIn("possible_coordinates", names)
        self.assertTrue(result["needs_review"])
        self.assertTrue(result["high_risk"])

    def test_ordinary_review_is_not_flagged(self):
        result = analyze_round(make_round("three", "Fits well and the zipper feels sturdy after two weeks."))
        self.assertEqual(result["flags"], [])
        self.assertFalse(result["needs_review"])
        self.assertFalse(result["high_risk"])
        self.assertEqual(result["risk_score"], 0)

    def test_screening_annotates_without_removing_by_default(self):
        payload = {
            "rounds": [
                make_round("safe", "Works fine."),
                make_round("risky", "Contact me at person@example.com."),
            ]
        }
        result = screen_dataset(payload)
        self.assertEqual(len(result["rounds"]), 2)
        self.assertEqual(result["screening_summary"]["needs_review_rounds"], 1)
        self.assertEqual(result["screening_summary"]["high_risk_rounds"], 1)
        self.assertEqual(result["screening_summary"]["excluded_high_risk_rounds"], 0)
        self.assertIn("screening", result["rounds"][0])
        self.assertIn("screening", result["rounds"][1])

    def test_exclude_high_only_removes_high_severity_rounds(self):
        payload = {
            "rounds": [
                make_round("safe", "Works fine."),
                make_round("medium", "More photos at https://example.com/item"),
                make_round("high", "Call me at 813-555-1212."),
            ]
        }
        result = screen_dataset(payload, exclude_high=True)
        self.assertEqual([row["id"] for row in result["rounds"]], ["safe", "medium"])
        self.assertEqual(result["screening_summary"]["excluded_high_risk_rounds"], 1)
        self.assertEqual(result["stats"]["rounds_written"], 2)

    def test_remote_image_is_low_priority_when_image_inspection_requested(self):
        result = analyze_round(make_round("remote", "Works fine."), inspect_images=True)
        self.assertEqual(result["flags"], [
            {"name": "image_not_local", "severity": "low", "source": "image"}
        ])
        self.assertFalse(result["high_risk"])


if __name__ == "__main__":
    unittest.main()
