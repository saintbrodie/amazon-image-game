import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from shard_dataset import write_sharded_dataset  # noqa: E402
from validate_shards import validate_sharded_pack  # noqa: E402


def make_payload() -> dict:
    rounds = []
    for index in range(6):
        category = "Beauty" if index % 2 == 0 else "Automotive"
        rounds.append(
            {
                "id": f"r{index}",
                "source_category": category,
                "review_image": f"https://example.test/{index}.jpg",
                "rating": 4,
                "product": {"title": f"Product {index}", "category": category, "parent_asin": f"P{index}"},
                "choices": [f"Product {index}", "A", "B", "C"],
            }
        )
    return {"version": 2, "name": "Fixture", "seed": 44, "rounds": rounds}


class ValidateShardsTests(unittest.TestCase):
    def build_fixture(self, root: Path):
        manifest_path = root / "data" / "rounds.manifest.json"
        manifest = write_sharded_dataset(
            make_payload(),
            manifest_path=manifest_path,
            shard_size=2,
            seed=None,
            shard_prefix="shards/rounds",
        )
        return manifest_path, manifest

    def test_valid_sharded_pack_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path, manifest = self.build_fixture(Path(tmp))
            self.assertEqual(validate_sharded_pack(manifest, root=manifest_path.parent), [])

    def test_missing_shard_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path, manifest = self.build_fixture(Path(tmp))
            first = manifest_path.parent / manifest["shards"][0]["path"]
            first.unlink()
            errors = validate_sharded_pack(manifest, root=manifest_path.parent)
            self.assertTrue(any("missing shard file" in error for error in errors))

    def test_modified_shard_hash_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path, manifest = self.build_fixture(Path(tmp))
            first = manifest_path.parent / manifest["shards"][0]["path"]
            payload = json.loads(first.read_text(encoding="utf-8"))
            payload["rounds"][0]["rating"] = 1
            first.write_text(json.dumps(payload), encoding="utf-8")
            errors = validate_sharded_pack(manifest, root=manifest_path.parent)
            self.assertTrue(any("sha256 mismatch" in error for error in errors))

    def test_unsafe_manifest_path_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path, manifest = self.build_fixture(Path(tmp))
            manifest["shards"][0]["path"] = "../escape.json"
            errors = validate_sharded_pack(manifest, root=manifest_path.parent)
            self.assertTrue(any("unsafe shard path" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
