import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_pack import META_BASE, REVIEW_BASE, build_pack, category_label, category_sources  # noqa: E402


def write_gzip_jsonl(path: Path, rows: list[dict]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def make_category(base: Path, category: str, index: int) -> None:
    review_rows = [
        {
            "rating": 5.0,
            "title": f"Review {category}",
            "text": "Works fine.",
            "images": [{"large_image_url": f"https://example.test/{category}.jpg"}],
            "asin": f"A{index}",
            "parent_asin": f"P{index}0",
        }
    ]
    metadata_rows = [
        {
            "parent_asin": f"P{index}0",
            "title": f"Correct Product {category}",
            "main_category": category_label(category),
            "categories": [category_label(category), "Mystery Things"],
        },
        {
            "parent_asin": f"P{index}1",
            "title": f"Alternate One {category}",
            "main_category": category_label(category),
            "categories": [category_label(category), "Mystery Things"],
        },
        {
            "parent_asin": f"P{index}2",
            "title": f"Alternate Two {category}",
            "main_category": category_label(category),
            "categories": [category_label(category), "Mystery Things"],
        },
        {
            "parent_asin": f"P{index}3",
            "title": f"Alternate Three {category}",
            "main_category": category_label(category),
            "categories": [category_label(category), "Mystery Things"],
        },
    ]
    write_gzip_jsonl(base / f"{category}.jsonl.gz", review_rows)
    write_gzip_jsonl(base / f"meta_{category}.jsonl.gz", metadata_rows)


class BuildPackTests(unittest.TestCase):
    def test_category_label(self):
        self.assertEqual(category_label("Patio_Lawn_and_Garden"), "Patio Lawn & Garden")
        self.assertEqual(category_label("Pet_Supplies"), "Pet Supplies")

    def test_remote_sources_use_current_hugging_face_raw_layout(self):
        reviews, metadata = category_sources("All_Beauty", None)
        self.assertEqual(reviews, f"{REVIEW_BASE}/All_Beauty.jsonl")
        self.assertEqual(metadata, f"{META_BASE}/meta_All_Beauty.jsonl")
        self.assertIn("huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/main/raw", reviews)

    def test_local_sources_accept_plain_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            review = base / "All_Beauty.jsonl"
            metadata = base / "meta_All_Beauty.jsonl"
            review.write_text("", encoding="utf-8")
            metadata.write_text("", encoding="utf-8")
            self.assertEqual(category_sources("All_Beauty", base), (str(review), str(metadata)))

    def test_builds_balanced_multi_category_pack_from_local_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            make_category(base, "Pet_Supplies", 1)
            make_category(base, "Automotive", 2)

            result = build_pack(
                ["Pet_Supplies", "Automotive"],
                limit=2,
                seed=7,
                raw_dir=base,
                check_images=False,
                image_workers=2,
                image_timeout=1.0,
                continue_on_error=False,
            )

            self.assertEqual(result["version"], 2)
            self.assertEqual(len(result["rounds"]), 2)
            self.assertEqual(set(result["categories"]), {"Pet_Supplies", "Automotive"})
            self.assertEqual(
                {round_data["source_category"] for round_data in result["rounds"]},
                {"Pet_Supplies", "Automotive"},
            )
            self.assertEqual(result["stats"]["rounds_written"], 2)
            self.assertEqual(result["stats"]["choice_reranking"]["rounds_fallback"], 0)

    def test_continue_on_error_keeps_successful_category(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            make_category(base, "Pet_Supplies", 1)

            result = build_pack(
                ["Pet_Supplies", "Missing_Category"],
                limit=2,
                seed=7,
                raw_dir=base,
                check_images=False,
                image_workers=2,
                image_timeout=1.0,
                continue_on_error=True,
            )

            self.assertEqual(len(result["rounds"]), 1)
            self.assertIn("Missing_Category", result["stats"]["failures"])
            self.assertEqual(result["categories"], ["Pet_Supplies"])


if __name__ == "__main__":
    unittest.main()
