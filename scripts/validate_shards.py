#!/usr/bin/env python3
"""Validate a static sharded game pack against its manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

from shard_dataset import dataset_signature, round_category


def safe_manifest_path(root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe shard path: {relative}")
    return root / Path(path)


def validate_sharded_pack(manifest: dict[str, Any], *, root: Path) -> list[str]:
    errors: list[str] = []
    if manifest.get("format") != "amazon-image-game-sharded-pack":
        errors.append("manifest format must be amazon-image-game-sharded-pack")

    shard_rows = manifest.get("shards")
    index_rows = manifest.get("index")
    if not isinstance(shard_rows, list) or not shard_rows:
        errors.append("manifest must contain a non-empty shards array")
        return errors
    if not isinstance(index_rows, list):
        errors.append("manifest must contain an index array")
        return errors

    expected_shards: dict[str, dict[str, Any]] = {}
    for row in shard_rows:
        if not isinstance(row, dict):
            errors.append("shard manifest entries must be objects")
            continue
        shard_id = str(row.get("id") or "")
        if not shard_id:
            errors.append("shard entry missing id")
            continue
        if shard_id in expected_shards:
            errors.append(f"duplicate shard id: {shard_id}")
        expected_shards[shard_id] = row

    indexed_ids: list[str] = []
    index_by_id: dict[str, dict[str, Any]] = {}
    for row in index_rows:
        if not isinstance(row, dict):
            errors.append("index entries must be objects")
            continue
        round_id = str(row.get("id") or "")
        shard_id = str(row.get("shard") or "")
        if not round_id:
            errors.append("index entry missing round id")
            continue
        if round_id in index_by_id:
            errors.append(f"duplicate round id in index: {round_id}")
        index_by_id[round_id] = row
        indexed_ids.append(round_id)
        if shard_id not in expected_shards:
            errors.append(f"round {round_id} references unknown shard {shard_id}")

    seen_rounds: dict[str, dict[str, Any]] = {}
    category_counts: Counter[str] = Counter()
    for shard_id, row in expected_shards.items():
        relative = row.get("path")
        if not isinstance(relative, str) or not relative:
            errors.append(f"shard {shard_id} missing path")
            continue
        try:
            shard_path = safe_manifest_path(root, relative)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if not shard_path.is_file():
            errors.append(f"missing shard file: {relative}")
            continue

        raw = shard_path.read_bytes()
        expected_hash = row.get("sha256")
        actual_hash = hashlib.sha256(raw).hexdigest()
        if expected_hash != actual_hash:
            errors.append(f"sha256 mismatch for shard {shard_id}")

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"invalid JSON in shard {shard_id}: {exc}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"shard {shard_id} root must be an object")
            continue
        if payload.get("dataset_signature") != manifest.get("dataset_signature"):
            errors.append(f"dataset signature mismatch in shard {shard_id}")
        if payload.get("shard", {}).get("id") != shard_id:
            errors.append(f"embedded shard id mismatch in shard {shard_id}")

        rounds = payload.get("rounds")
        if not isinstance(rounds, list):
            errors.append(f"shard {shard_id} must contain a rounds array")
            continue
        if len(rounds) != row.get("round_count"):
            errors.append(f"round count mismatch for shard {shard_id}")

        local_categories: Counter[str] = Counter()
        for round_data in rounds:
            if not isinstance(round_data, dict) or not round_data.get("id"):
                errors.append(f"invalid round in shard {shard_id}")
                continue
            round_id = str(round_data["id"])
            if round_id in seen_rounds:
                errors.append(f"round appears in multiple shards: {round_id}")
                continue
            seen_rounds[round_id] = round_data
            category = round_category(round_data)
            category_counts[category] += 1
            local_categories[category] += 1
            index_row = index_by_id.get(round_id)
            if not index_row:
                errors.append(f"round missing from manifest index: {round_id}")
            else:
                if str(index_row.get("shard")) != shard_id:
                    errors.append(f"index shard mismatch for round {round_id}")
                if index_row.get("category") != category:
                    errors.append(f"index category mismatch for round {round_id}")

        if dict(sorted(local_categories.items())) != row.get("categories"):
            errors.append(f"category counts mismatch for shard {shard_id}")

    seen_ids = set(seen_rounds)
    indexed_set = set(indexed_ids)
    if seen_ids != indexed_set:
        missing = sorted(indexed_set - seen_ids)
        extra = sorted(seen_ids - indexed_set)
        if missing:
            errors.append(f"indexed rounds missing from shards: {', '.join(missing[:8])}")
        if extra:
            errors.append(f"shard rounds missing from index: {', '.join(extra[:8])}")

    if len(seen_rounds) != manifest.get("round_count"):
        errors.append("manifest round_count does not match loaded shards")
    if dict(sorted(category_counts.items())) != manifest.get("categories"):
        errors.append("manifest category totals do not match loaded shards")
    if seen_rounds and dataset_signature(list(seen_rounds.values())) != manifest.get("dataset_signature"):
        errors.append("manifest dataset_signature does not match shard round IDs")

    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise SystemExit("manifest root must be a JSON object")
    errors = validate_sharded_pack(manifest, root=args.manifest.parent)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    print(
        f"{args.manifest}: OK ({manifest['round_count']:,} rounds, "
        f"{len(manifest['shards']):,} shards)"
    )


if __name__ == "__main__":
    main()
