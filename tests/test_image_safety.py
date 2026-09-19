import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from image_safety import (  # noqa: E402
    DEFAULT_MODEL_ID,
    TransformerImageSafetyClassifier,
    evaluate_scores,
    normalize_scores,
    parse_device,
    validate_thresholds,
)


class ImageSafetyTests(unittest.TestCase):
    def test_normalize_scores_accepts_transformers_output(self):
        scores = normalize_scores([
            {"label": "normal", "score": 0.12},
            {"label": "NSFW", "score": 0.88},
        ])
        self.assertEqual(scores, {"normal": 0.12, "nsfw": 0.88})

        nested = normalize_scores([[
            {"label": "safe", "score": 0.7},
            {"label": "unsafe-content", "score": 0.3},
        ]])
        self.assertEqual(nested, {"safe": 0.7, "unsafe content": 0.3})

    def test_medium_and_high_thresholds_emit_named_flag(self):
        medium_flags, medium_details = evaluate_scores(
            [{"label": "normal", "score": 0.3}, {"label": "nsfw", "score": 0.7}],
            model_id=DEFAULT_MODEL_ID,
            review_threshold=0.6,
            high_threshold=0.9,
        )
        self.assertEqual(medium_flags, [{
            "name": "model_nsfw_content",
            "severity": "medium",
            "source": "image_model",
        }])
        self.assertEqual(medium_details["positive_score"], 0.7)

        high_flags, _ = evaluate_scores(
            [{"label": "normal", "score": 0.04}, {"label": "nsfw", "score": 0.96}],
            model_id=DEFAULT_MODEL_ID,
            review_threshold=0.6,
            high_threshold=0.9,
        )
        self.assertEqual(high_flags[0]["severity"], "high")

    def test_below_review_threshold_records_scores_without_flag(self):
        flags, details = evaluate_scores(
            [{"label": "normal", "score": 0.93}, {"label": "nsfw", "score": 0.07}],
            model_id="example/model",
            review_threshold=0.6,
            high_threshold=0.9,
        )
        self.assertEqual(flags, [])
        self.assertEqual(details["model"], "example/model")
        self.assertEqual(details["scores"]["nsfw"], 0.07)

    def test_custom_positive_labels_are_normalized(self):
        flags, details = evaluate_scores(
            [{"label": "Unsafe_Content", "score": 0.92}, {"label": "safe", "score": 0.08}],
            model_id="example/model",
            positive_labels=["unsafe-content"],
            review_threshold=0.5,
            high_threshold=0.9,
        )
        self.assertEqual(flags[0]["severity"], "high")
        self.assertEqual(details["positive_labels"], ["unsafe content"])

    def test_threshold_validation_rejects_invalid_ranges(self):
        self.assertEqual(validate_thresholds(0.5, 0.9), (0.5, 0.9))
        with self.assertRaises(ValueError):
            validate_thresholds(0.95, 0.9)
        with self.assertRaises(ValueError):
            validate_thresholds(-0.1, 0.9)
        with self.assertRaises(ValueError):
            validate_thresholds(0.5, 1.1)

    def test_device_parser_supports_cpu_gpu_index_and_backend_strings(self):
        self.assertIsNone(parse_device(None))
        self.assertIsNone(parse_device("auto"))
        self.assertEqual(parse_device("cpu"), -1)
        self.assertEqual(parse_device("0"), 0)
        self.assertEqual(parse_device("mps"), "mps")

    def test_classifier_metadata_does_not_load_heavy_dependencies(self):
        classifier = TransformerImageSafetyClassifier(
            model_id="example/model",
            positive_labels=["unsafe"],
            review_threshold=0.6,
            high_threshold=0.95,
            device="cpu",
            pipeline_factory=lambda **_: None,
        )
        self.assertEqual(classifier.describe(), {
            "type": "transformers_image_classification",
            "model": "example/model",
            "revision": None,
            "positive_labels": ["unsafe"],
            "review_threshold": 0.6,
            "high_threshold": 0.95,
            "device": "cpu",
        })


if __name__ == "__main__":
    unittest.main()
