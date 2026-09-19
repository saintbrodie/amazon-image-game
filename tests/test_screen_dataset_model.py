import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from screen_dataset import analyze_round, screen_dataset  # noqa: E402


def make_round(round_id: str) -> dict:
    return {
        "id": round_id,
        "review_image": "image.jpg",
        "review_title": "Review",
        "review_text": "Works fine.",
        "rating": 5,
        "product": {"title": "Mystery Product"},
        "choices": ["Mystery Product", "A", "B", "C"],
    }


class FakeSafetyClassifier:
    def __init__(self, severity: str = "medium", score: float = 0.72):
        self.severity = severity
        self.score = score
        self.calls = []

    def describe(self):
        return {
            "type": "test_classifier",
            "model": "fake/safety",
            "review_threshold": 0.6,
            "high_threshold": 0.9,
        }

    def classify(self, path: Path):
        self.calls.append(path)
        return ([{
            "name": "model_sensitive_content",
            "severity": self.severity,
            "source": "image_model",
        }], {
            "model": "fake/safety",
            "positive_score": self.score,
            "scores": {"positive": self.score},
        })


class ScreenDatasetModelTests(unittest.TestCase):
    def test_model_adds_flag_and_score_metadata(self):
        classifier = FakeSafetyClassifier()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "image.jpg").write_bytes(b"fixture")
            with patch("screen_dataset.pillow_image_flags", return_value=([], {"width": 640, "height": 480})), patch(
                "screen_dataset.opencv_image_flags", return_value=([], {})
            ):
                result = analyze_round(
                    make_round("model"),
                    image_root=root,
                    inspect_images=True,
                    safety_classifier=classifier,
                )

        self.assertEqual(len(classifier.calls), 1)
        self.assertEqual(classifier.calls[0].name, "image.jpg")
        self.assertEqual(result["flags"][-1]["source"], "image_model")
        self.assertEqual(result["flags"][-1]["severity"], "medium")
        self.assertEqual(result["image"]["safety_model"]["positive_score"], 0.72)
        self.assertTrue(result["needs_review"])
        self.assertFalse(result["high_risk"])

    def test_high_model_flag_can_be_excluded(self):
        classifier = FakeSafetyClassifier(severity="high", score=0.97)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "image.jpg").write_bytes(b"fixture")
            with patch("screen_dataset.pillow_image_flags", return_value=([], {})), patch(
                "screen_dataset.opencv_image_flags", return_value=([], {})
            ):
                result = screen_dataset(
                    {"rounds": [make_round("model-high")]},
                    image_root=root,
                    inspect_images=True,
                    safety_classifier=classifier,
                    exclude_high=True,
                )

        self.assertEqual(result["rounds"], [])
        summary = result["screening_summary"]
        self.assertEqual(summary["high_risk_rounds"], 1)
        self.assertEqual(summary["excluded_high_risk_rounds"], 1)
        self.assertEqual(summary["safety_model"]["model"], "fake/safety")

    def test_model_requires_image_inspection(self):
        with self.assertRaisesRegex(ValueError, "requires inspect_images"):
            screen_dataset(
                {"rounds": [make_round("x")]},
                safety_classifier=FakeSafetyClassifier(),
            )


if __name__ == "__main__":
    unittest.main()
