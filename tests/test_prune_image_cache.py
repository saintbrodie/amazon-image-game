import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from prune_image_cache import maintenance_report, referenced_cache_paths  # noqa: E402


class PruneImageCacheTests(unittest.TestCase):
    def write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_dry_run_reports_orphans_and_missing_without_deleting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "assets" / "review-cache"
            cache.mkdir(parents=True)
            (cache / "keep.jpg").write_bytes(b"keep")
            (cache / "orphan.png").write_bytes(b"orphan-data")

            dataset = root / "rounds.json"
            self.write_json(dataset, {
                "rounds": [
                    {"id": "a", "review_image": "assets/review-cache/keep.jpg"},
                    {"id": "b", "review_image": "assets/review-cache/missing.webp"},
                    {"id": "c", "review_image": "https://example.test/remote.jpg"},
                ]
            })

            report = maintenance_report(
                sources=[dataset],
                asset_dir=cache,
                public_prefix="assets/review-cache",
            )
            self.assertTrue(report["dry_run"])
            self.assertEqual(report["rounds_scanned"], 3)
            self.assertEqual(report["external_or_noncache_rounds"], 1)
            self.assertEqual(report["cache_files"], 2)
            self.assertEqual(report["referenced_existing_files"], 1)
            self.assertEqual(report["referenced_missing_files"], 1)
            self.assertEqual(report["missing_references"], ["missing.webp"])
            self.assertEqual(report["orphan_files"], 1)
            self.assertEqual(report["orphan_paths"], ["orphan.png"])
            self.assertEqual(report["orphan_bytes"], len(b"orphan-data"))
            self.assertTrue((cache / "orphan.png").exists())

    def test_delete_removes_only_orphans_and_empty_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            (cache / "nested").mkdir(parents=True)
            (cache / "keep.jpg").write_bytes(b"keep")
            (cache / "nested" / "old.jpg").write_bytes(b"old")
            dataset = root / "rounds.json"
            self.write_json(dataset, {"rounds": [{"id": "a", "review_image": "cache/keep.jpg"}]})

            report = maintenance_report(
                sources=[dataset],
                asset_dir=cache,
                public_prefix="cache",
                delete=True,
            )
            self.assertFalse(report["dry_run"])
            self.assertEqual(report["deleted_files"], 1)
            self.assertEqual(report["deleted_bytes"], 3)
            self.assertTrue((cache / "keep.jpg").exists())
            self.assertFalse((cache / "nested" / "old.jpg").exists())
            self.assertFalse((cache / "nested").exists())

    def test_multiple_sources_union_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            cache.mkdir()
            (cache / "a.jpg").write_bytes(b"a")
            (cache / "b.jpg").write_bytes(b"b")
            one = root / "one.json"
            two = root / "two.json"
            self.write_json(one, {"rounds": [{"id": "a", "review_image": "cache/a.jpg"}]})
            self.write_json(two, {"rounds": [{"id": "b", "review_image": "cache/b.jpg"}]})

            report = maintenance_report(sources=[one, two], asset_dir=cache, public_prefix="cache")
            self.assertEqual(report["referenced_existing_files"], 2)
            self.assertEqual(report["orphan_files"], 0)

    def test_sharded_manifest_collects_round_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            cache = root / "assets" / "review-cache"
            cache.mkdir(parents=True)
            (cache / "a.jpg").write_bytes(b"a")
            (cache / "b.jpg").write_bytes(b"b")

            self.write_json(data / "shards" / "rounds-0001.json", {
                "format": "amazon-image-game-shard",
                "rounds": [{"id": "a", "review_image": "assets/review-cache/a.jpg"}],
            })
            self.write_json(data / "shards" / "rounds-0002.json", {
                "format": "amazon-image-game-shard",
                "rounds": [{"id": "b", "review_image": "assets/review-cache/b.jpg"}],
            })
            manifest = data / "rounds.manifest.json"
            self.write_json(manifest, {
                "format": "amazon-image-game-sharded-pack",
                "shards": [
                    {"id": "0001", "path": "shards/rounds-0001.json"},
                    {"id": "0002", "path": "shards/rounds-0002.json"},
                ],
            })

            report = maintenance_report(
                sources=[manifest],
                asset_dir=cache,
                public_prefix="assets/review-cache",
            )
            self.assertEqual(report["rounds_scanned"], 2)
            self.assertEqual(report["referenced_existing_files"], 2)
            self.assertEqual(report["orphan_files"], 0)

    def test_manifest_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "data" / "rounds.manifest.json"
            self.write_json(manifest, {
                "format": "amazon-image-game-sharded-pack",
                "shards": [{"id": "0001", "path": "../secret.json"}],
            })
            with self.assertRaisesRegex(ValueError, "unsafe relative path"):
                referenced_cache_paths([manifest], "assets/review-cache")

    def test_unsafe_review_image_is_not_treated_as_cache_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "rounds.json"
            self.write_json(dataset, {
                "rounds": [{"id": "a", "review_image": "assets/review-cache/../../outside.jpg"}]
            })
            references, rounds, other = referenced_cache_paths([dataset], "assets/review-cache")
            self.assertEqual(references, set())
            self.assertEqual(rounds, 1)
            self.assertEqual(other, 1)


if __name__ == "__main__":
    unittest.main()
