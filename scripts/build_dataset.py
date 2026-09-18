#!/usr/bin/env python3
"""Build compact game rounds from McAuley Lab Amazon Reviews 2023 files.

The script intentionally uses only the Python standard library and streams the
large JSONL inputs. It keeps a bounded reservoir of image-bearing reviews and a
bounded distractor pool instead of loading the full review file into memory.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, TextIO


def open_jsonl(path: Path) -> TextIO:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with open_jsonl(path) as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path} on line {line_number}") from exc
            if isinstance(value, dict):
                yield value


def first_url(value: Any, keys: tuple[str, ...]) -> str | None:
    if not isinstance(value, list):
        return None
    for item in value:
        if not isinstance(item, dict):
            continue
        for key in keys:
            candidate = item.get(key)
            if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                return candidate
    return None


def review_image(review: dict[str, Any]) -> str | None:
    return first_url(review.get("images"), ("large_image_url", "medium_image_url", "small_image_url"))


def product_image(meta: dict[str, Any]) -> str | None:
    images = meta.get("images")
    if not isinstance(images, list):
        return None

    main = [item for item in images if isinstance(item, dict) and item.get("variant") == "MAIN"]
    candidates = main or images
    return first_url(candidates, ("hi_res", "large", "thumb"))


def normalize_title(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    title = " ".join(value.split())
    if len(title) < 3:
        return None
    return title[:180]


def normalize_product(meta: dict[str, Any]) -> dict[str, Any] | None:
    title = normalize_title(meta.get("title"))
    parent_asin = meta.get("parent_asin")
    if not title or not isinstance(parent_asin, str) or not parent_asin:
        return None

    categories = meta.get("categories") if isinstance(meta.get("categories"), list) else []
    category = meta.get("main_category")
    if not isinstance(category, str) or not category.strip():
        category = next((str(item) for item in categories if item), "Amazon product")

    price = meta.get("price")
    if not isinstance(price, (int, float)) or price <= 0:
        price = None

    return {
        "parent_asin": parent_asin,
        "title": title,
        "category": category.strip(),
        "price": price,
        "product_image": product_image(meta),
    }


def reservoir_add(reservoir: list[Any], item: Any, seen: int, capacity: int, rng: random.Random) -> None:
    if len(reservoir) < capacity:
        reservoir.append(item)
        return
    position = rng.randrange(seen)
    if position < capacity:
        reservoir[position] = item


def sample_reviews(path: Path, capacity: int, rng: random.Random) -> tuple[list[dict[str, Any]], int]:
    reservoir: list[dict[str, Any]] = []
    eligible = 0

    for row in iter_jsonl(path):
        image = review_image(row)
        parent_asin = row.get("parent_asin")
        if not image or not isinstance(parent_asin, str) or not parent_asin:
            continue

        eligible += 1
        candidate = {
            "image": image,
            "asin": row.get("asin") if isinstance(row.get("asin"), str) else None,
            "parent_asin": parent_asin,
            "rating": row.get("rating") if isinstance(row.get("rating"), (int, float)) else None,
            "review_title": normalize_title(row.get("title")) or "Customer review",
            "review_text": " ".join(str(row.get("text") or "").split())[:700],
            "helpful_vote": row.get("helpful_vote") if isinstance(row.get("helpful_vote"), int) else 0,
            "verified_purchase": bool(row.get("verified_purchase", False)),
        }
        reservoir_add(reservoir, candidate, eligible, capacity, rng)

    return reservoir, eligible


def collect_metadata(
    path: Path,
    wanted_parent_asins: set[str],
    pool_capacity: int,
    rng: random.Random,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], int]:
    wanted: dict[str, dict[str, Any]] = {}
    pool: list[dict[str, Any]] = []
    eligible = 0

    for row in iter_jsonl(path):
        product = normalize_product(row)
        if not product:
            continue

        eligible += 1
        parent_asin = product["parent_asin"]
        if parent_asin in wanted_parent_asins:
            wanted[parent_asin] = product
        reservoir_add(pool, product, eligible, pool_capacity, rng)

    unique_pool: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for product in pool:
        key = product["title"].casefold()
        if key not in seen_titles:
            seen_titles.add(key)
            unique_pool.append(product)

    return wanted, unique_pool, eligible


def make_choices(correct: dict[str, Any], pool: list[dict[str, Any]], rng: random.Random) -> list[str] | None:
    correct_title = correct["title"]
    correct_key = correct_title.casefold()

    same_category = [
        item["title"]
        for item in pool
        if item["title"].casefold() != correct_key and item["category"] == correct["category"]
    ]
    fallback = [
        item["title"]
        for item in pool
        if item["title"].casefold() != correct_key and item["title"] not in same_category
    ]

    rng.shuffle(same_category)
    rng.shuffle(fallback)
    distractors: list[str] = []
    seen = {correct_key}
    for title in same_category + fallback:
        key = title.casefold()
        if key in seen:
            continue
        distractors.append(title)
        seen.add(key)
        if len(distractors) == 3:
            break

    if len(distractors) < 3:
        return None

    choices = distractors + [correct_title]
    rng.shuffle(choices)
    return choices


def build_game_data(
    reviews_path: Path,
    metadata_path: Path,
    *,
    limit: int = 5000,
    seed: int = 1337,
    name: str | None = None,
) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("limit must be at least 1")

    rng = random.Random(seed)
    candidate_capacity = min(max(limit * 6, limit + 200), 50_000)
    distractor_capacity = min(max(limit * 4, 2_000), 20_000)

    candidates, eligible_reviews = sample_reviews(reviews_path, candidate_capacity, rng)
    wanted_ids = {item["parent_asin"] for item in candidates}
    metadata, distractor_pool, eligible_products = collect_metadata(
        metadata_path, wanted_ids, distractor_capacity, rng
    )

    rng.shuffle(candidates)
    rounds: list[dict[str, Any]] = []
    seen_images: set[str] = set()

    for candidate in candidates:
        if len(rounds) >= limit:
            break
        image = candidate["image"]
        if image in seen_images:
            continue
        product = metadata.get(candidate["parent_asin"])
        if not product:
            continue
        choices = make_choices(product, distractor_pool, rng)
        if not choices:
            continue

        asin = candidate.get("asin")
        public_product = {
            "title": product["title"],
            "category": product["category"],
            "price": product["price"],
            "product_image": product["product_image"],
            "asin": asin,
            "parent_asin": product["parent_asin"],
            "source_url": f"https://www.amazon.com/dp/{asin}" if asin else None,
        }
        digest = hashlib.sha1(f"{product['parent_asin']}|{image}".encode("utf-8")).hexdigest()[:14]
        rounds.append(
            {
                "id": digest,
                "review_image": image,
                "rating": candidate["rating"],
                "review_title": candidate["review_title"],
                "review_text": candidate["review_text"],
                "helpful_vote": candidate["helpful_vote"],
                "verified_purchase": candidate["verified_purchase"],
                "product": public_product,
                "choices": choices,
            }
        )
        seen_images.add(image)

    return {
        "version": 1,
        "name": name or f"Amazon Reviews 2023: {metadata_path.stem.replace('meta_', '').replace('.jsonl', '')}",
        "source": "McAuley Lab Amazon Reviews 2023",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "stats": {
            "eligible_image_reviews_seen": eligible_reviews,
            "eligible_metadata_products_seen": eligible_products,
            "sampled_review_candidates": len(candidates),
            "distractor_pool_size": len(distractor_pool),
            "rounds_written": len(rounds),
        },
        "rounds": rounds,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviews", required=True, type=Path, help="Category review .jsonl or .jsonl.gz")
    parser.add_argument("--metadata", required=True, type=Path, help="Matching metadata .jsonl or .jsonl.gz")
    parser.add_argument("--output", type=Path, default=Path("data/rounds.json"))
    parser.add_argument("--limit", type=int, default=5000, help="Maximum playable rounds to emit")
    parser.add_argument("--seed", type=int, default=1337, help="Deterministic sampling seed")
    parser.add_argument("--name", help="Optional dataset label shown in the UI")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for path in (args.reviews, args.metadata):
        if not path.is_file():
            raise SystemExit(f"Input file not found: {path}")

    payload = build_game_data(
        args.reviews,
        args.metadata,
        limit=args.limit,
        seed=args.seed,
        name=args.name,
    )
    if not payload["rounds"]:
        raise SystemExit("No playable rounds were produced. Try a larger category or inspect the input schema.")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {len(payload['rounds']):,} rounds to {args.output}")
    print(json.dumps(payload["stats"], indent=2))


if __name__ == "__main__":
    main()
