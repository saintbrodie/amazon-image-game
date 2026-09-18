import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from quality import analyze_round, audit_dataset, jaccard, review_leak_ratio  # noqa: E402
from score_dataset import score_dataset  # noqa: E402


def make_round(**overrides):
    round_data = {
        "id": "r1",
        "source_category": "Pet_Supplies",
        "review_image": "https://images.example.test/r1.jpg",
        "rating": 4,
        "review_title": "Works well",
        "review_text": "Our cat uses this every day and the bowl stays full.",
        "verified_purchase": True,
        "helpful_vote": 2,
        "product": {
            "title": "Automatic Pet Water Fountain",
            "category": "Pet Supplies",
            "source_url": "https://www.amazon.com/dp/A1",
        },
        "choices": [
            "Automatic Pet Water Fountain",
            "Gravity Pet Water Dispenser",
            "Automatic Dry Food Feeder",
            "Ceramic Cat Food Bowl",
        ],
    }
    round_data.update(overrides)
    return round_data


class QualityTests(unittest.TestCase):
    def test_jaccard_similarity(self):
        self.assertGreater(jaccard("Automatic Cat Water Fountain", "Cat Water Fountain Automatic"), 0.7)
        self.assertEqual(jaccard("Cat Water Fountain", "Cordless Impact Driver"), 0.0)

    def test_review_leak_detects_product_terms(self):
        round_data = make_round(
            review_text="This automatic water fountain is much quieter than our old one."
        )
        self.assertGreaterEqual(review_leak_ratio(round_data), 0.5)

    def test_analysis_flags_near_duplicate_answer(self):
        round_data = make_round(
            choices=[
                "Automatic Pet Water Fountain",
                "Pet Water Fountain Automatic",
                "Automatic Dry Food Feeder",
                "Ceramic Cat Food Bowl",
            ]
        )
        analysis = analyze_round(round_data)
        self.assertIn("near_duplicate_answer_title", analysis["flags"])
        self.assertGreaterEqual(analysis["curation_priority"], 30)

    def test_analysis_flags_missing_review_text(self):
        analysis = analyze_round(make_round(review_text=""))
        self.assertIn("missing_review_text", analysis["flags"])

    def test_scoring_does_not_mutate_source(self):
        payload = {"rounds": [make_round()]}
        result = score_dataset(payload)
        self.assertNotIn("analysis", payload["rounds"][0])
        self.assertIn("analysis", result["rounds"][0])
        self.assertEqual(result["analysis_version"], 1)

    def test_audit_aggregates_rounds(self):
        payload = {
            "rounds": [
                make_round(),
                make_round(
                    id="r2",
                    source_category="Automotive",
                    verified_purchase=False,
                    helpful_vote=0,
                    review_image="assets/demo/example.svg",
                ),
            ]
        }
        report = audit_dataset(payload)
        self.assertEqual(report["rounds"], 2)
        self.assertEqual(report["categories"]["Pet_Supplies"], 1)
        self.assertEqual(report["categories"]["Automotive"], 1)
        self.assertEqual(report["verified_purchase_rounds"], 1)
        self.assertEqual(report["reviews_with_helpful_votes"], 1)
        self.assertEqual(report["image_hosts"]["local"], 1)


if __name__ == "__main__":
    unittest.main()
