#!/usr/bin/env python3
"""Print a compact quality audit for a generated game pack."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from quality import audit_dataset


def render_text(report: dict) -> str:
    lines = [
        f"Rounds: {report['rounds']:,}",
        f"Average difficulty: {report['average_difficulty_score']}/100",
        f"Average curation priority: {report['average_curation_priority']}/100",
        f"Verified purchases: {report['verified_purchase_rounds']:,}",
        f"Reviews with helpful votes: {report['reviews_with_helpful_votes']:,}",
        "",
        "Categories:",
    ]
    lines.extend(f"  {name}: {count:,}" for name, count in report["categories"].items())
    lines.extend(["", "Difficulty buckets:"])
    lines.extend(f"  {name}: {count:,}" for name, count in report["difficulty_buckets"].items())
    lines.extend(["", "Curation priority:"])
    lines.extend(f"  {name}: {count:,}" for name, count in report["curation_priority_buckets"].items())
    lines.extend(["", "Quality flags:"])
    if report["quality_flags"]:
        lines.extend(f"  {name}: {count:,}" for name, count in report["quality_flags"].items())
    else:
        lines.append("  none")
    lines.extend(["", "Image hosts:"])
    lines.extend(f"  {name}: {count:,}" for name, count in report["image_hosts"].items())
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument("--output", type=Path, help="Also write the report to a file")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = json.loads(args.dataset.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("dataset root must be a JSON object")
    try:
        report = audit_dataset(payload)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    text = json.dumps(report, indent=2) if args.json else render_text(report)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
