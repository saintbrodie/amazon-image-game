#!/usr/bin/env python3
"""Apply exported Round Curator decisions to a game dataset."""

from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def fnv1a_ascii(value: str) -> int:
    """Match game-core.js hashString for ASCII round IDs/signature input."""
    value_bytes = value.encode("ascii")
    hash_value = 2166136261
    for byte in value_bytes:
        hash_value ^= byte
        hash_value = (hash_value * 16777619) & 0xFFFFFFFF
    return hash_value


def dataset_signature(rounds: list[dict[str, Any]]) -> str:
    ids = sorted(str(round_data.get("id", "")) for round_data in rounds)
    return format(fnv1a_ascii("|".join(ids)), "x")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_decisions(payload: Any) -> tuple[set[str], set[str], str | None]:
    if not isinstance(payload, dict):
        raise ValueError("decisions root must be an object")

    kept = payload.get("kept_ids")
    rejected = payload.get("rejected_ids")
    if not isinstance(kept, list) or not isinstance(rejected, list):
        raise ValueError("decisions file must contain kept_ids and rejected_ids arrays")
    if any(not isinstance(value, str) or not value for value in kept + rejected):
        raise ValueError("decision IDs must be non-empty strings")

    kept_set = set(kept)
    rejected_set = set(rejected)
    overlap = kept_set & rejected_set
    if overlap:
        sample = sorted(overlap)[0]
        raise ValueError(f"round {sample!r} is both kept and rejected")

    signature = payload.get("dataset_signature")
    if signature is not None and not isinstance(signature, str):
        raise ValueError("dataset_signature must be a string when present")
    return kept_set, rejected_set, signature


def apply_curation(
    dataset: dict[str, Any],
    decisions: dict[str, Any],
    *,
    only_kept: bool = False,
    allow_signature_mismatch: bool = False,
) -> dict[str, Any]:
    rounds = dataset.get("rounds")
    if not isinstance(rounds, list):
        raise ValueError("dataset must contain a rounds array")

    kept_ids, rejected_ids, exported_signature = normalize_decisions(decisions)
    actual_signature = dataset_signature(rounds)
    if exported_signature and exported_signature != actual_signature and not allow_signature_mismatch:
        raise ValueError(
            "curation decisions were exported for a different dataset signature "
            f"({exported_signature} != {actual_signature})"
        )

    available_ids = {str(round_data.get("id", "")) for round_data in rounds if isinstance(round_data, dict)}
    unknown_kept = kept_ids - available_ids
    unknown_rejected = rejected_ids - available_ids

    output_rounds: list[dict[str, Any]] = []
    kept_present = 0
    rejected_present = 0
    unreviewed_present = 0

    for round_data in rounds:
        if not isinstance(round_data, dict):
            continue
        round_id = str(round_data.get("id", ""))
        if round_id in rejected_ids:
            rejected_present += 1
            continue
        if round_id in kept_ids:
            kept_present += 1
            output_rounds.append(round_data)
            continue
        unreviewed_present += 1
        if not only_kept:
            output_rounds.append(round_data)

    result = copy.deepcopy(dataset)
    result["rounds"] = output_rounds
    result["curated_at"] = datetime.now(timezone.utc).isoformat()
    result["curation"] = {
        "source_dataset_signature": actual_signature,
        "only_kept": only_kept,
        "kept_present": kept_present,
        "rejected_present": rejected_present,
        "unreviewed_present": unreviewed_present,
        "unknown_kept_ids": len(unknown_kept),
        "unknown_rejected_ids": len(unknown_rejected),
        "rounds_before": len(rounds),
        "rounds_after": len(output_rounds),
    }

    stats = result.get("stats")
    if not isinstance(stats, dict):
        stats = {}
        result["stats"] = stats
    stats["rounds_written"] = len(output_rounds)
    stats["curation"] = copy.deepcopy(result["curation"])
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True, help="Input rounds JSON")
    parser.add_argument("--decisions", type=Path, required=True, help="Exported curator decisions JSON")
    parser.add_argument("--output", type=Path, default=Path("data/rounds.curated.json"))
    parser.add_argument(
        "--only-kept",
        action="store_true",
        help="Drop unreviewed rounds too; otherwise only explicitly rejected rounds are removed",
    )
    parser.add_argument(
        "--allow-signature-mismatch",
        action="store_true",
        help="Apply matching round IDs even if the decisions file came from a different dataset signature",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset = load_json(args.dataset)
    decisions = load_json(args.decisions)
    if not isinstance(dataset, dict) or not isinstance(decisions, dict):
        raise SystemExit("dataset and decisions must both be JSON objects")

    try:
        curated = apply_curation(
            dataset,
            decisions,
            only_kept=args.only_kept,
            allow_signature_mismatch=args.allow_signature_mismatch,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(curated, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    summary = curated["curation"]
    print(
        f"Wrote {summary['rounds_after']:,} of {summary['rounds_before']:,} rounds to {args.output} "
        f"({summary['rejected_present']:,} rejected, {summary['kept_present']:,} kept decisions applied)"
    )
    if summary["unknown_kept_ids"] or summary["unknown_rejected_ids"]:
        print(
            "Warning: decisions referenced round IDs not present in this dataset: "
            f"{summary['unknown_kept_ids']} kept, {summary['unknown_rejected_ids']} rejected"
        )


if __name__ == "__main__":
    main()
