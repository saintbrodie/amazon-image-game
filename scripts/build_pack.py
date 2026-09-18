#!/usr/bin/env python3
"""Build one game pack from multiple Amazon Reviews 2023 categories.

By default this streams the official UCSD .jsonl.gz files directly over HTTP,
so it does not require keeping multi-gigabyte raw datasets on disk. Pass
--raw-dir to use already-downloaded category files instead.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from build_dataset import build_game_data

REVIEW_BASE = "https://datarepo.eng.ucsd.edu/mcauley_group/data/amazon_2023/raw/review_categories"
META_BASE = "https://datarepo.eng.ucsd.edu/mcauley_group/data/amazon_2023/raw/meta_categories"
DEFAULT_CATEGORIES = [
    "Pet_Supplies",
    "Patio_Lawn_and_Garden",
    "Tools_and_Home_Improvement",
    "Automotive",
    "Home_and_Kitchen",
]


def category_label(category: str) -> str:
    return category.replace("_and_", " & ").replace("_", " ")


def category_sources(category: str, raw_dir: Path | None) -> tuple[str, str]:
    if raw_dir is None:
        return (
            f"{REVIEW_BASE}/{category}.jsonl.gz",
            f"{META_BASE}/meta_{category}.jsonl.gz",
        )

    review = raw_dir / f"{category}.jsonl.gz"
    metadata = raw_dir / f"meta_{category}.jsonl.gz"
    missing = [str(path) for path in (review, metadata) if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing local dataset file(s): " + ", ".join(missing))
    return str(review), str(metadata)


def image_is_live(url: str, timeout: float) -> bool:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 amazon-image-game-image-check/1.0",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Range": "bytes=0-2047",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            prefix = response.read(32)
            return response.status < 400 and bool(prefix) and content_type.startswith("image/")
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return False


def filter_live_images(
    rounds: list[dict[str, Any]],
    *,
    workers: int = 16,
    timeout: float = 10.0,
) -> tuple[list[dict[str, Any]], int]:
    if not rounds:
        return [], 0

    live_ids: set[str] = set()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(image_is_live, round_data["review_image"], timeout): round_data["id"]
            for round_data in rounds
        }
        for future in as_completed(futures):
            round_id = futures[future]
            try:
                if future.result():
                    live_ids.add(round_id)
            except Exception:
                pass

    filtered = [round_data for round_data in rounds if round_data["id"] in live_ids]
    return filtered, len(rounds) - len(filtered)


def build_pack(
    categories: list[str],
    *,
    limit: int,
    seed: int,
    raw_dir: Path | None,
    check_images: bool,
    image_workers: int,
    image_timeout: float,
    continue_on_error: bool,
) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if not categories:
        raise ValueError("at least one category is required")

    rng = random.Random(seed)
    desired_per_category = math.ceil(limit / len(categories))
    # Oversample because dead image URLs and cross-category final trimming can remove rounds.
    build_target = max(desired_per_category + 20, math.ceil(desired_per_category * 1.35))

    combined: list[dict[str, Any]] = []
    category_stats: dict[str, Any] = {}
    failures: dict[str, str] = {}

    for index, category in enumerate(categories):
        label = category_label(category)
        print(f"\n[{index + 1}/{len(categories)}] Building {label}…", flush=True)
        try:
            reviews, metadata = category_sources(category, raw_dir)
            payload = build_game_data(
                reviews,
                metadata,
                limit=build_target,
                seed=seed + index * 1009,
                name=label,
                source_category=category,
            )
            rounds = payload["rounds"]
            dead = 0
            if check_images:
                print(f"Checking {len(rounds):,} review image URLs…", flush=True)
                rounds, dead = filter_live_images(
                    rounds,
                    workers=image_workers,
                    timeout=image_timeout,
                )
            rng.shuffle(rounds)
            rounds = rounds[:desired_per_category]
            combined.extend(rounds)
            category_stats[category] = {
                **payload["stats"],
                "dead_images_removed": dead,
                "rounds_kept": len(rounds),
            }
            print(f"Kept {len(rounds):,} {label} rounds.", flush=True)
        except Exception as exc:
            failures[category] = f"{type(exc).__name__}: {exc}"
            if not continue_on_error:
                raise
            print(f"WARNING: {label} failed: {exc}", flush=True)

    # A product may occasionally occur across Amazon category exports. Keep one round per product/image.
    unique: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_products: set[str] = set()
    for round_data in combined:
        round_id = round_data["id"]
        parent_asin = round_data.get("product", {}).get("parent_asin")
        if round_id in seen_ids or (parent_asin and parent_asin in seen_products):
            continue
        seen_ids.add(round_id)
        if parent_asin:
            seen_products.add(parent_asin)
        unique.append(round_data)

    rng.shuffle(unique)
    unique = unique[:limit]
    successful_categories = [category for category in categories if category in category_stats]

    return {
        "version": 2,
        "name": "Amazon Review Mystery Pack",
        "source": "McAuley Lab Amazon Reviews 2023",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "categories": successful_categories,
        "stats": {
            "rounds_written": len(unique),
            "requested_rounds": limit,
            "image_health_check": check_images,
            "category_stats": category_stats,
            "failures": failures,
        },
        "rounds": unique,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--categories",
        nargs="+",
        default=DEFAULT_CATEGORIES,
        help="Dataset category keys, e.g. Pet_Supplies Automotive",
    )
    parser.add_argument("--limit", type=int, default=2000, help="Maximum total rounds in the pack")
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--output", type=Path, default=Path("data/rounds.json"))
    parser.add_argument(
        "--raw-dir",
        type=Path,
        help="Use local CATEGORY.jsonl.gz and meta_CATEGORY.jsonl.gz files instead of streaming UCSD",
    )
    parser.add_argument(
        "--check-images",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Verify chosen review image URLs before writing the pack (default: true)",
    )
    parser.add_argument("--image-workers", type=int, default=16)
    parser.add_argument("--image-timeout", type=float, default=10.0)
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Keep successful categories if another category fails",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_pack(
        args.categories,
        limit=args.limit,
        seed=args.seed,
        raw_dir=args.raw_dir,
        check_images=args.check_images,
        image_workers=args.image_workers,
        image_timeout=args.image_timeout,
        continue_on_error=args.continue_on_error,
    )
    if not payload["rounds"]:
        raise SystemExit("No playable rounds were produced.")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"\nWrote {len(payload['rounds']):,} rounds to {args.output}")
    if payload["stats"]["failures"]:
        print("Failures:")
        print(json.dumps(payload["stats"]["failures"], indent=2))


if __name__ == "__main__":
    main()
