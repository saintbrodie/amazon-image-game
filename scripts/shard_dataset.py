#!/usr/bin/env python3
"""Split a browser-ready round pack into deterministic static shards.

The manifest keeps only the lightweight information needed to choose rounds:
round ID, source category, and shard ID. Full review text, image URLs, product
metadata, and choices remain in shard files. A static browser can therefore
select rounds first and fetch only the shard files that contain them.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def round_category(round_data: dict[str, Any]) -> str:
    category = round_data.get("source_category")
    if isinstance(category, str) and category.strip():
        return category.strip()
    product = round_data.get("product") if isinstance(round_data.get("product"), dict) else {}
    fallback = product.get("category")
    return fallback.strip() if isinstance(fallback, str) and fallback.strip() else "Other"


def game_core_hash(value: str) -> int:
    """Match GameCore.hashString's FNV-1a over JavaScript UTF-16 code units."""
    hash_value = 2166136261
    encoded = str(value).encode("utf-16-le", errors="surrogatepass")
    for offset in range(0, len(encoded), 2):
        code_unit = encoded[offset] | (encoded[offset + 1] << 8)
        hash_value ^= code_unit
        hash_value = (hash_value * 16777619) & 0xFFFFFFFF
    return hash_value


def dataset_signature(rounds: list[dict[str, Any]]) -> str:
    ids = sorted(str(round_data.get("id", "")) for round_data in rounds)
    return format(game_core_hash("|".join(ids)), "x")


def deterministic_round_order(rounds: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    def key(round_data: dict[str, Any]) -> tuple[str, str]:
        round_id = str(round_data.get("id", ""))
        digest = hashlib.sha256(f"{seed}|{round_id}".encode("utf-8")).hexdigest()
        return digest, round_id

    return sorted(rounds, key=key)


def safe_shard_prefix(value: str) -> PurePosixPath:
    raw = str(value).strip()
    path = PurePosixPath(raw)
    if (
        not raw
        or raw.startswith("/")
        or "\\" in raw
        or path.is_absolute()
        or ".." in path.parts
        or path.name in {"", ".", ".."}
    ):
        raise ValueError("shard_prefix must be a safe manifest-relative path")
    return path


def shard_dataset(
    payload: dict[str, Any],
    *,
    shard_size: int = 250,
    seed: int | None = None,
    shard_prefix: str = "shards/rounds",
) -> tuple[dict[str, Any], list[tuple[str, dict[str, Any]]]]:
    rounds = payload.get("rounds")
    if not isinstance(rounds, list):
        raise ValueError("dataset must contain a rounds array")
    if shard_size < 1:
        raise ValueError("shard_size must be at least 1")
    if not rounds:
        raise ValueError("dataset must contain at least one round")
    if any(not isinstance(round_data, dict) or not round_data.get("id") for round_data in rounds):
        raise ValueError("every round must be an object with an id")

    ids = [str(round_data["id"]) for round_data in rounds]
    if len(set(ids)) != len(ids):
        raise ValueError("round IDs must be unique before sharding")

    actual_seed = int(payload.get("seed", 0) if seed is None else seed)
    signature = dataset_signature(rounds)
    ordered = deterministic_round_order(rounds, actual_seed)
    category_counts = Counter(round_category(round_data) for round_data in rounds)

    shards: list[tuple[str, dict[str, Any]]] = []
    shard_manifest: list[dict[str, Any]] = []
    index: list[dict[str, str]] = []
    shard_prefix_path = safe_shard_prefix(shard_prefix)

    total_shards = (len(ordered) + shard_size - 1) // shard_size
    width = max(4, len(str(total_shards)))

    for shard_index, start in enumerate(range(0, len(ordered), shard_size), start=1):
        chunk = ordered[start : start + shard_size]
        shard_id = f"{shard_index:0{width}d}"
        relative_path = str(shard_prefix_path.parent / f"{shard_prefix_path.name}-{shard_id}.json")
        chunk_categories = Counter(round_category(round_data) for round_data in chunk)

        shard_payload = {
            "version": payload.get("version", 2),
            "format": "amazon-image-game-shard",
            "name": payload.get("name", "Sharded round pack"),
            "source": payload.get("source"),
            "seed": actual_seed,
            "dataset_signature": signature,
            "shard": {
                "id": shard_id,
                "index": shard_index,
                "count": total_shards,
            },
            "rounds": copy.deepcopy(chunk),
        }
        shard_bytes = canonical_json(shard_payload)
        shard_sha = hashlib.sha256(shard_bytes).hexdigest()
        shards.append((relative_path, shard_payload))
        shard_manifest.append(
            {
                "id": shard_id,
                "path": relative_path,
                "round_count": len(chunk),
                "sha256": shard_sha,
                "categories": dict(sorted(chunk_categories.items())),
            }
        )
        index.extend(
            {
                "id": str(round_data["id"]),
                "category": round_category(round_data),
                "shard": shard_id,
            }
            for round_data in chunk
        )

    manifest = {
        "version": 1,
        "format": "amazon-image-game-sharded-pack",
        "name": payload.get("name", "Sharded round pack"),
        "source": payload.get("source"),
        "seed": actual_seed,
        "dataset_signature": signature,
        "round_count": len(rounds),
        "shard_size": shard_size,
        "categories": dict(sorted(category_counts.items())),
        "shards": shard_manifest,
        "index": index,
    }
    return manifest, shards


def write_sharded_dataset(
    payload: dict[str, Any],
    *,
    manifest_path: Path,
    shard_size: int,
    seed: int | None,
    shard_prefix: str,
) -> dict[str, Any]:
    manifest, shards = shard_dataset(
        payload,
        shard_size=shard_size,
        seed=seed,
        shard_prefix=shard_prefix,
    )
    root = manifest_path.parent
    root.mkdir(parents=True, exist_ok=True)

    for relative_path, shard_payload in shards:
        output_path = root / Path(PurePosixPath(relative_path))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(canonical_json(shard_payload))

    manifest_path.write_bytes(canonical_json(manifest))
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, help="Input browser-ready pack JSON")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/rounds.manifest.json"),
        help="Manifest output path",
    )
    parser.add_argument("--shard-size", type=int, default=250)
    parser.add_argument("--seed", type=int, help="Override the input pack seed used for deterministic shard assignment")
    parser.add_argument(
        "--shard-prefix",
        default="shards/rounds",
        help="Manifest-relative path prefix for shard files",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = json.loads(args.dataset.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("dataset root must be a JSON object")
    try:
        manifest = write_sharded_dataset(
            payload,
            manifest_path=args.manifest,
            shard_size=args.shard_size,
            seed=args.seed,
            shard_prefix=args.shard_prefix,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    print(
        f"Wrote {manifest['round_count']:,} rounds across "
        f"{len(manifest['shards']):,} shards to {args.manifest.parent}"
    )
    print(f"Manifest: {args.manifest}")
    print(f"Dataset signature: {manifest['dataset_signature']}")


if __name__ == "__main__":
    main()
