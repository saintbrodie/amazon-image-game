import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from shard_dataset import dataset_signature, game_core_hash, shard_dataset, write_sharded_dataset  # noqa: E402


def make_round(index: int, category: str) -> dict:
    return {
        "id": f"round-{index:03d}",
        "source_category": category,
        "review_image": f"https://example.test/{index}.jpg",
        "rating": 5,
        "product": {
            "title": f"Product {index}",
            "category": category,
            "parent_asin": f"P{index:03d}",
        },
        "choices": [f"Product {index}", "Wrong A", "Wrong B", "Wrong C"],
    }


class ShardDatasetTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "version": 2,
            "name": "Test Pack",
            "source": "fixture",
            "seed": 99,
            "rounds": [
                make_round(1, "Beauty"),
                make_round(2, "Beauty"),
                make_round(3, "Automotive"),
                make_round(4, "Beauty"),
                make_round(5, "Automotive"),
                make_round(6, "Beauty"),
                make_round(7, "Automotive"),
            ],
        }

    def test_game_core_hash_matches_fnv_reference(self):
        self.assertEqual(game_core_hash("hello"), 0x4F9F2CAB)

    def test_shards_have_no_loss_or_duplicate_rounds(self):
        manifest, shards = shard_dataset(self.payload, shard_size=3)
        self.assertEqual(manifest["round_count"], 7)
        self.assertEqual(len(shards), 3)
        self.assertEqual([row["round_count"] for row in manifest["shards"]], [3, 3, 1])

        ids = [round_data["id"] for _, shard in shards for round_data in shard["rounds"]]
        self.assertEqual(len(ids), 7)
        self.assertEqual(set(ids), {round_data["id"] for round_data in self.payload["rounds"]})
        self.assertEqual(len(ids), len(set(ids)))

    def test_manifest_index_points_to_existing_shards(self):
        manifest, _ = shard_dataset(self.payload, shard_size=2)
        shard_ids = {shard["id"] for shard in manifest["shards"]}
        self.assertEqual(len(manifest["index"]), 7)
        self.assertTrue(all(row["shard"] in shard_ids for row in manifest["index"]))
        self.assertEqual(manifest["categories"], {"Automotive": 3, "Beauty": 4})

    def test_sharding_is_deterministic_across_input_order(self):
        forward, _ = shard_dataset(self.payload, shard_size=3)
        reversed_payload = {**self.payload, "rounds": list(reversed(self.payload["rounds"]))}
        reverse, _ = shard_dataset(reversed_payload, shard_size=3)
        self.assertEqual(forward, reverse)
        self.assertEqual(
            dataset_signature(self.payload["rounds"]),
            dataset_signature(reversed_payload["rounds"]),
        )

    def test_seed_changes_assignment_but_not_signature(self):
        one, _ = shard_dataset(self.payload, shard_size=3, seed=1)
        two, _ = shard_dataset(self.payload, shard_size=3, seed=2)
        self.assertNotEqual(one["index"], two["index"])
        self.assertEqual(one["dataset_signature"], two["dataset_signature"])

    def test_written_paths_match_manifest_and_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "data" / "rounds.manifest.json"
            manifest = write_sharded_dataset(
                self.payload,
                manifest_path=manifest_path,
                shard_size=3,
                seed=None,
                shard_prefix="shards/rounds",
            )
            self.assertTrue(manifest_path.is_file())
            loaded_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded_manifest, manifest)
            for shard in manifest["shards"]:
                shard_path = manifest_path.parent / shard["path"]
                self.assertTrue(shard_path.is_file())
                import hashlib

                self.assertEqual(hashlib.sha256(shard_path.read_bytes()).hexdigest(), shard["sha256"])

    def test_invalid_inputs_fail(self):
        with self.assertRaises(ValueError):
            shard_dataset({"rounds": []}, shard_size=10)
        with self.assertRaises(ValueError):
            shard_dataset(self.payload, shard_size=0)
        duplicate = {**self.payload, "rounds": self.payload["rounds"] + [self.payload["rounds"][0]]}
        with self.assertRaises(ValueError):
            shard_dataset(duplicate, shard_size=3)
        for unsafe in ("../escape/rounds", "/absolute/rounds", r"..\escape\rounds"):
            with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                shard_dataset(self.payload, shard_size=3, shard_prefix=unsafe)


if __name__ == "__main__":
    unittest.main()
