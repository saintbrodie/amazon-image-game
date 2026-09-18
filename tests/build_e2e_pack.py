#!/usr/bin/env python3
"""Build a deterministic larger fixture from the bundled demo for browser e2e tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "demo.json"
OUTPUT = ROOT / "data" / "e2e-pack.json"
TARGET_ROUNDS = 40


def main() -> None:
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    source_rounds = payload["rounds"]
    rounds = []
    for index in range(TARGET_ROUNDS):
        original = source_rounds[index % len(source_rounds)]
        round_data = copy.deepcopy(original)
        round_data["id"] = f"e2e-{index:03d}-{original['id']}"
        round_data["source_category"] = original.get("source_category") or original.get("product", {}).get("category") or "Other"
        product = round_data.setdefault("product", {})
        product["parent_asin"] = f"E2EP{index:05d}"
        product["asin"] = f"E2EA{index:05d}"
        rounds.append(round_data)

    output = {
        "version": 2,
        "name": "Browser E2E Sharded Fixture",
        "source": "bundled demo expansion",
        "seed": 20260918,
        "rounds": rounds,
    }
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {len(rounds)} rounds to {OUTPUT}")


if __name__ == "__main__":
    main()
