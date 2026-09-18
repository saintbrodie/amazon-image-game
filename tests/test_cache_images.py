import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from cache_images import (  # noqa: E402
    PerceptualIndex,
    cache_dataset,
    extension_for,
    hamming_distance,
    public_asset_path,
)


class CacheImageTests(unittest.TestCase):
    def test_extension_sniffing_prefers_bytes(self):
        self.assertEqual(extension_for("thing.bin", "application/octet-stream", b"\xff\xd8\xffabc"), ".jpg")
        self.assertEqual(extension_for("thing.bin", None, b"\x89PNG\r\n\x1a\nrest"), ".png")
        self.assertEqual(extension_for("thing.jpeg", None), ".jpg")

    def test_public_asset_path(self):
        self.assertEqual(public_asset_path("assets/review-cache", "abc.jpg"), "assets/review-cache/abc.jpg")
        self.assertEqual(public_asset_path("", "abc.jpg"), "abc.jpg")

    def test_hamming_index_finds_near_hashes(self):
        index = PerceptualIndex(2)
        original = 0x1234567890ABCDEF
        index.add(original)
        self.assertEqual(index.find(original ^ 0b11), 0)
        self.assertIsNone(index.find(original ^ 0b111111))
        self.assertEqual(hamming_distance(original, original ^ 0b10101), 3)

    def test_local_cache_drops_failed_and_exact_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "input"
            source_dir.mkdir()
            (source_dir / "one.jpg").write_bytes(b"same-image-content")
            (source_dir / "two.jpg").write_bytes(b"same-image-content")
            (source_dir / "three.png").write_bytes(b"different-image-content")
            asset_dir = root / "assets" / "cache"

            payload = {
                "stats": {"rounds_written": 4},
                "rounds": [
                    {"id": "r1", "review_image": "input/one.jpg"},
                    {"id": "r2", "review_image": "input/two.jpg"},
                    {"id": "r3", "review_image": "input/three.png"},
                    {"id": "r4", "review_image": "input/missing.jpg"},
                ],
            }
            result = cache_dataset(
                payload,
                asset_dir=asset_dir,
                public_prefix="assets/cache",
                web_root=root,
                workers=2,
            )

            self.assertEqual([row["id"] for row in result["rounds"]], ["r1", "r3"])
            self.assertEqual(result["image_cache"]["failed_rounds"], 1)
            self.assertEqual(result["image_cache"]["exact_duplicate_rounds_removed"], 1)
            self.assertEqual(result["image_cache"]["rounds_after"], 2)
            self.assertEqual(result["stats"]["rounds_written"], 2)
            for row in result["rounds"]:
                self.assertTrue(row["review_image"].startswith("assets/cache/"))
                self.assertIn("review_image_original", row)
                self.assertIn("review_image_sha256", row)
                cached_file = root / row["review_image"]
                self.assertTrue(cached_file.is_file())

    def test_keep_exact_duplicates_reuses_same_cached_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.jpg").write_bytes(b"same")
            (root / "b.jpg").write_bytes(b"same")
            payload = {
                "rounds": [
                    {"id": "a", "review_image": "a.jpg"},
                    {"id": "b", "review_image": "b.jpg"},
                ]
            }
            result = cache_dataset(
                payload,
                asset_dir=root / "cache",
                public_prefix="cache",
                web_root=root,
                keep_exact_duplicates=True,
            )
            self.assertEqual(len(result["rounds"]), 2)
            self.assertEqual(result["rounds"][0]["review_image"], result["rounds"][1]["review_image"])

    def test_local_path_cannot_escape_web_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {"rounds": [{"id": "x", "review_image": "../outside.jpg"}]}
            result = cache_dataset(
                payload,
                asset_dir=root / "cache",
                public_prefix="cache",
                web_root=root,
            )
            self.assertEqual(result["rounds"], [])
            self.assertEqual(result["image_cache"]["failed_rounds"], 1)


if __name__ == "__main__":
    unittest.main()
