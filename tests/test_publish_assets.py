import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from publish_assets import (  # noqa: E402
    build_upload_plan,
    delivery_mapping,
    load_manifest,
    normalize_object_prefix,
    normalize_public_base_url,
    publish_uploads,
    safe_asset_dir,
    safe_manifest_path,
    with_delivery_mapping,
    write_manifest_atomic,
)


class FakeS3Client:
    def __init__(self):
        self.calls = []

    def upload_file(self, local_path, bucket, object_key, ExtraArgs=None):
        self.calls.append((local_path, bucket, object_key, ExtraArgs))


class PublishAssetTests(unittest.TestCase):
    def test_normalizes_public_and_object_prefixes(self):
        self.assertEqual(normalize_object_prefix("/game/reviews/"), "game/reviews")
        self.assertEqual(normalize_object_prefix(""), "")
        self.assertEqual(normalize_public_base_url("https://cdn.example.test/reviews"), "https://cdn.example.test/reviews/")
        with self.assertRaises(ValueError):
            normalize_object_prefix("../escape")
        with self.assertRaises(ValueError):
            normalize_public_base_url("javascript:alert(1)")
        with self.assertRaises(ValueError):
            normalize_public_base_url("https://cdn.example.test/reviews?token=secret")

    def test_site_paths_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site = root / "site"
            site.mkdir()
            self.assertEqual(
                safe_manifest_path(site, None),
                (site / "data" / "rounds.manifest.json").resolve(),
            )
            self.assertEqual(
                safe_asset_dir(site, None),
                (site / "assets" / "review-cache").resolve(),
            )
            with self.assertRaises(ValueError):
                safe_manifest_path(site, root / "outside.json")
            with self.assertRaises(ValueError):
                safe_asset_dir(site, root / "outside-assets")

    def test_build_plan_and_upload_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets = root / "assets"
            (assets / "nested").mkdir(parents=True)
            (assets / "a.jpg").write_bytes(b"jpeg-ish")
            (assets / "nested" / "b.webp").write_bytes(b"webp-ish-data")
            symlink = assets / "skip.jpg"
            try:
                symlink.symlink_to(assets / "a.jpg")
            except OSError:
                pass

            plan = build_upload_plan(assets, "game/reviews")
            self.assertEqual([item.relative_path for item in plan], ["a.jpg", "nested/b.webp"])
            self.assertEqual([item.object_key for item in plan], ["game/reviews/a.jpg", "game/reviews/nested/b.webp"])
            self.assertEqual(plan[0].content_type, "image/jpeg")
            self.assertEqual(plan[1].content_type, "image/webp")

            client = FakeS3Client()
            result = publish_uploads(plan, client=client, bucket="demo-bucket")
            self.assertEqual(result["uploaded_files"], 2)
            self.assertEqual(result["uploaded_bytes"], len(b"jpeg-ish") + len(b"webp-ish-data"))
            self.assertEqual(client.calls[0][1], "demo-bucket")
            self.assertEqual(client.calls[0][2], "game/reviews/a.jpg")
            self.assertEqual(client.calls[0][3]["ContentType"], "image/jpeg")
            self.assertIn("immutable", client.calls[0][3]["CacheControl"])

    def test_delivery_mapping_updates_manifest_without_touching_shards(self):
        manifest = {
            "format": "amazon-image-game-sharded-pack",
            "dataset_signature": "abc123",
            "shards": [{"id": "0001", "path": "shards/rounds-0001.json"}],
            "index": [{"id": "r1", "category": "Other", "shard": "0001"}],
        }
        updated = with_delivery_mapping(
            manifest,
            asset_path_prefix="assets/review-cache/",
            public_base_url="https://cdn.example.test/reviews/",
        )
        self.assertNotIn("asset_delivery", manifest)
        self.assertEqual(updated["shards"], manifest["shards"])
        self.assertEqual(updated["asset_delivery"], {
            "review_images": {
                "path_prefix": "assets/review-cache/",
                "base_url": "https://cdn.example.test/reviews/",
            }
        })
        self.assertEqual(delivery_mapping(
            asset_path_prefix="assets/review-cache",
            public_base_url="https://cdn.example.test/reviews",
        ), updated["asset_delivery"]["review_images"])

    def test_manifest_write_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rounds.manifest.json"
            original = {
                "format": "amazon-image-game-sharded-pack",
                "dataset_signature": "sig",
                "index": [],
                "shards": [],
            }
            path.write_text(json.dumps(original), encoding="utf-8")
            self.assertEqual(load_manifest(path)["dataset_signature"], "sig")
            updated = with_delivery_mapping(
                original,
                asset_path_prefix="assets/review-cache/",
                public_base_url="https://cdn.example.test/",
            )
            write_manifest_atomic(path, updated)
            reloaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(reloaded["asset_delivery"]["review_images"]["base_url"], "https://cdn.example.test/")
            self.assertFalse((Path(tmp) / ".rounds.manifest.json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
