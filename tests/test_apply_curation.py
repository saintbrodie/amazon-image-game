import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from apply_curation import apply_curation, dataset_signature, game_core_hash  # noqa: E402


def sample_dataset():
    return {
        "version": 2,
        "name": "Test Pack",
        "stats": {"rounds_written": 3},
        "rounds": [
            {"id": "aaa111", "product": {"title": "A"}, "choices": ["A", "B", "C", "D"]},
            {"id": "bbb222", "product": {"title": "B"}, "choices": ["B", "A", "C", "D"]},
            {"id": "ccc333", "product": {"title": "C"}, "choices": ["C", "A", "B", "D"]},
        ],
    }


class ApplyCurationTests(unittest.TestCase):
    def test_signature_is_stable_across_round_order(self):
        dataset = sample_dataset()
        forward = dataset_signature(dataset["rounds"])
        backward = dataset_signature(list(reversed(dataset["rounds"])))
        self.assertEqual(forward, backward)
        self.assertRegex(forward, r"^[0-9a-f]+$")

    def test_hash_matches_browser_utf16_semantics(self):
        self.assertEqual(game_core_hash("hello"), 0x4F9F2CAB)
        unicode_rounds = [{"id": "round-🐈"}, {"id": "café"}]
        self.assertEqual(dataset_signature(unicode_rounds), "272e4c5a")

    def test_default_removes_rejected_and_preserves_unreviewed(self):
        dataset = sample_dataset()
        decisions = {
            "dataset_signature": dataset_signature(dataset["rounds"]),
            "kept_ids": ["aaa111"],
            "rejected_ids": ["bbb222"],
        }
        result = apply_curation(dataset, decisions)
        self.assertEqual([row["id"] for row in result["rounds"]], ["aaa111", "ccc333"])
        self.assertEqual(result["curation"]["kept_present"], 1)
        self.assertEqual(result["curation"]["rejected_present"], 1)
        self.assertEqual(result["curation"]["unreviewed_present"], 1)
        self.assertEqual(result["stats"]["rounds_written"], 2)

    def test_only_kept_removes_unreviewed(self):
        dataset = sample_dataset()
        decisions = {
            "dataset_signature": dataset_signature(dataset["rounds"]),
            "kept_ids": ["ccc333"],
            "rejected_ids": ["bbb222"],
        }
        result = apply_curation(dataset, decisions, only_kept=True)
        self.assertEqual([row["id"] for row in result["rounds"]], ["ccc333"])
        self.assertEqual(result["curation"]["rounds_after"], 1)

    def test_signature_mismatch_fails_by_default(self):
        dataset = sample_dataset()
        decisions = {
            "dataset_signature": "deadbeef",
            "kept_ids": [],
            "rejected_ids": ["bbb222"],
        }
        with self.assertRaisesRegex(ValueError, "different dataset signature"):
            apply_curation(dataset, decisions)

    def test_signature_mismatch_can_be_overridden(self):
        dataset = sample_dataset()
        decisions = {
            "dataset_signature": "deadbeef",
            "kept_ids": [],
            "rejected_ids": ["bbb222"],
        }
        result = apply_curation(dataset, decisions, allow_signature_mismatch=True)
        self.assertEqual([row["id"] for row in result["rounds"]], ["aaa111", "ccc333"])

    def test_overlap_is_invalid(self):
        dataset = sample_dataset()
        decisions = {"kept_ids": ["aaa111"], "rejected_ids": ["aaa111"]}
        with self.assertRaisesRegex(ValueError, "both kept and rejected"):
            apply_curation(dataset, decisions)


if __name__ == "__main__":
    unittest.main()
