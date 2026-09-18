#!/usr/bin/env python3
"""Annotate every round in a generated pack with heuristic curation metadata."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from quality import annotate_dataset


def score_dataset(payload: dict) -> dict:
    result = deepcopy(payload)
    annotate_dataset(result)
    result["scored_at"] = datetime.now(timezone.utc).isoformat()
    result["analysis_version"] = 1
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, help="Defaults to overwriting the input dataset")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print output JSON")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = json.loads(args.dataset.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("dataset root must be a JSON object")
    try:
        result = score_dataset(payload)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    output = args.output or args.dataset
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.pretty:
        text = json.dumps(result, ensure_ascii=False, indent=2)
    else:
        text = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    output.write_text(text, encoding="utf-8")
    print(f"Annotated {len(result.get('rounds', [])):,} rounds in {output}")


if __name__ == "__main__":
    main()
