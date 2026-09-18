import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from pack_choices import (  # noqa: E402
    candidate_banks,
    choose_distractors,
    rerank_pack_choices,
    title_metrics,
)


class PackChoiceTests(unittest.TestCase):
    def test_title_metrics_reward_related_product_words(self):
        related = title_metrics("Hydrating Rose Lip Balm", "Vanilla Moisturizing Lip Balm")
        unrelated = title_metrics("Hydrating Rose Lip Balm", "Cordless Impact Driver Kit")
        self.assertGreater(related[0], unrelated[0])
        self.assertGreater(related[1], unrelated[1])
        self.assertGreater(related[2], unrelated[2])

    def test_choose_distractors_prefers_related_titles(self):
        candidates = [
            "Cordless Impact Driver Kit",
            "Vanilla Moisturizing Lip Balm",
            "Tinted Berry Lip Balm Tube",
            "Natural Beeswax Lip Balm",
            "Ergonomic Office Chair",
            "Reflective Dog Leash",
        ]
        selected = choose_distractors(
            "Hydrating Rose Lip Balm",
            candidates,
            rng=random.Random(4),
        )
        self.assertEqual(len(selected), 3)
        self.assertTrue(all("Lip Balm" in title for title in selected))

    def test_near_duplicate_title_is_rejected(self):
        selected = choose_distractors(
            "Automatic Cat Water Fountain Stainless Steel",
            [
                "Stainless Steel Cat Water Fountain Automatic",
                "Ceramic Cat Water Fountain",
                "Filtered Cat Drinking Fountain",
                "Pet Water Dispenser Fountain",
            ],
            rng=random.Random(7),
        )
        self.assertNotIn("Stainless Steel Cat Water Fountain Automatic", selected)

    def test_rerank_uses_category_bank_and_preserves_correct_answer(self):
        rounds = [
            {
                "id": "1",
                "source_category": "Beauty",
                "product": {"title": "Hydrating Rose Lip Balm"},
                "choices": [
                    "Hydrating Rose Lip Balm",
                    "Ergonomic Office Chair",
                    "Vanilla Moisturizing Lip Balm",
                    "Tinted Berry Lip Balm Tube",
                ],
            },
            {
                "id": "2",
                "source_category": "Beauty",
                "product": {"title": "Natural Beeswax Lip Balm"},
                "choices": [
                    "Natural Beeswax Lip Balm",
                    "Reflective Dog Leash",
                    "Mint Lip Balm Stick",
                    "Shea Butter Lip Balm",
                ],
            },
        ]
        banks = candidate_banks(rounds)
        stats = rerank_pack_choices(rounds, seed=10, banks=banks)
        self.assertEqual(stats["rounds_fallback"], 0)
        for round_data in rounds:
            self.assertEqual(len(round_data["choices"]), 4)
            self.assertIn(round_data["product"]["title"], round_data["choices"])
            self.assertEqual(len(set(round_data["choices"])), 4)


if __name__ == "__main__":
    unittest.main()
