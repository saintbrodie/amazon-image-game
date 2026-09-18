#!/usr/bin/env python3
"""Validate a browser-ready game dataset and report common data quality problems."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def image_reference_is_valid(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    if value.startswith(("assets/", "./", "../")):
        return True
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate_payload(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["dataset root must be an object"]
    rounds = payload.get("rounds")
    if not isinstance(rounds, list) or not rounds:
        return ["dataset must contain a non-empty rounds array"]

    seen_ids: set[str] = set()
    seen_parent_asins: set[str] = set()

    for index, round_data in enumerate(rounds):
        prefix = f"rounds[{index}]"
        if not isinstance(round_data, dict):
            errors.append(f"{prefix} must be an object")
            continue

        round_id = round_data.get("id")
        if not isinstance(round_id, str) or not round_id:
            errors.append(f"{prefix}.id must be a non-empty string")
        elif round_id in seen_ids:
            errors.append(f"{prefix}.id duplicates {round_id!r}")
        else:
            seen_ids.add(round_id)

        if not image_reference_is_valid(round_data.get("review_image")):
            errors.append(f"{prefix}.review_image must be an HTTP(S) URL or local asset path")

        product = round_data.get("product")
        if not isinstance(product, dict):
            errors.append(f"{prefix}.product must be an object")
            continue

        title = product.get("title")
        if not isinstance(title, str) or not title.strip():
            errors.append(f"{prefix}.product.title must be a non-empty string")

        choices = round_data.get("choices")
        if not isinstance(choices, list) or len(choices) != 4:
            errors.append(f"{prefix}.choices must contain exactly four entries")
        else:
            if any(not isinstance(choice, str) or not choice.strip() for choice in choices):
                errors.append(f"{prefix}.choices entries must be non-empty strings")
            if len({choice.casefold() for choice in choices if isinstance(choice, str)}) != len(choices):
                errors.append(f"{prefix}.choices contains duplicate answers")
            if isinstance(title, str) and title not in choices:
                errors.append(f"{prefix}.choices does not include the correct product title")

        parent_asin = product.get("parent_asin")
        if isinstance(parent_asin, str) and parent_asin:
            if parent_asin in seen_parent_asins:
                errors.append(f"{prefix}.product.parent_asin duplicates {parent_asin!r}")
            else:
                seen_parent_asins.add(parent_asin)

        rating = round_data.get("rating")
        if rating is not None and (not isinstance(rating, (int, float)) or isinstance(rating, bool) or not 1 <= rating <= 5):
            errors.append(f"{prefix}.rating must be between 1 and 5 when present")

    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = json.loads(args.dataset.read_text(encoding="utf-8"))
    errors = validate_payload(payload)
    if errors:
        print(f"{args.dataset}: {len(errors)} validation error(s)")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print(f"{args.dataset}: OK ({len(payload['rounds']):,} rounds)")


if __name__ == "__main__":
    main()
