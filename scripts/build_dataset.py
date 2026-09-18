#!/usr/bin/env python3
"""Build compact game rounds from McAuley Lab Amazon Reviews 2023 files.

The builder accepts local JSONL/JSONL.GZ files or HTTP(S) URLs. It streams the
large inputs, keeps bounded reservoirs in memory, joins reviews to metadata by
parent_asin, and emits only browser-ready game data.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import random
import re
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, TextIO

Source = str | Path
URL_RE = re.compile(r"^https?://", re.IGNORECASE)
WORD_RE = re.compile(r"[a-z0-9]+")
STOPWORDS = {
    "a", "an", "and", "for", "from", "in", "of", "on", "or", "the", "to", "with",
    "pack", "set", "new", "size", "inch", "inches", "black", "white",
}


def is_url(source: Source) -> bool:
    return isinstance(source, str) and bool(URL_RE.match(source))


@contextmanager
def open_jsonl(source: Source) -> Iterator[TextIO]:
    """Open a local or remote JSONL source, transparently handling gzip."""
    source_text = str(source)
    compressed = source_text.lower().endswith(".gz")

    if is_url(source):
        request = urllib.request.Request(
            source_text,
            headers={"User-Agent": "amazon-image-game/1.0 (+https://github.com/saintbrodie/amazon-image-game)"},
        )
        response = urllib.request.urlopen(request, timeout=60)
        binary = gzip.GzipFile(fileobj=response) if compressed else response
        text = io.TextIOWrapper(binary, encoding="utf-8")
        try:
            yield text
        finally:
            text.close()
        return

    path = Path(source)
    if compressed:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            yield handle
    else:
        with path.open("r", encoding="utf-8") as handle:
            yield handle


def iter_jsonl(source: Source, max_records: int | None = None) -> Iterable[dict[str, Any]]:
    with open_jsonl(source) as handle:
        for line_number, line in enumerate(handle, start=1):
            if max_records is not None and line_number > max_records:
                break
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {source} on line {line_number}") from exc
            if isinstance(value, dict):
                yield value


def first_url_from_images(value: Any, keys: tuple[str, ...], prefer_main: bool = False) -> str | None:
    """Read image URLs from either list-of-dicts or dict-of-lists representations."""
    if isinstance(value, list):
        items = [item for item in value if isinstance(item, dict)]
        if prefer_main:
            main = [item for item in items if item.get("variant") == "MAIN"]
            items = main or items
        for item in items:
            for key in keys:
                candidate = item.get(key)
                if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                    return candidate
        return None

    if isinstance(value, dict):
        variants = value.get("variant") if isinstance(value.get("variant"), list) else []
        preferred_indices: list[int] = []
        if prefer_main:
            preferred_indices = [index for index, variant in enumerate(variants) if variant == "MAIN"]

        for key in keys:
            candidates = value.get(key)
            if isinstance(candidates, str):
                candidates = [candidates]
            if not isinstance(candidates, list):
                continue
            indices = preferred_indices + [i for i in range(len(candidates)) if i not in preferred_indices]
            for index in indices:
                if index >= len(candidates):
                    continue
                candidate = candidates[index]
                if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                    return candidate
    return None


def review_image(review: dict[str, Any]) -> str | None:
    return first_url_from_images(
        review.get("images"),
        ("large_image_url", "medium_image_url", "small_image_url"),
    )


def product_image(meta: dict[str, Any]) -> str | None:
    return first_url_from_images(meta.get("images"), ("hi_res", "large", "thumb"), prefer_main=True)


def normalize_title(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    title = " ".join(value.split())
    if len(title) < 3:
        return None
    return title[:220]


def parse_price(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    if isinstance(value, str):
        cleaned = value.strip().replace("$", "").replace(",", "")
        if not cleaned or cleaned.casefold() in {"none", "null", "nan"}:
            return None
        try:
            price = float(cleaned)
        except ValueError:
            return None
        return price if price > 0 else None
    return None


def normalize_categories(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str):
            cleaned = " ".join(item.split())
            if cleaned and cleaned.casefold() not in {entry.casefold() for entry in result}:
                result.append(cleaned[:120])
    return result[:12]


def normalize_product(meta: dict[str, Any]) -> dict[str, Any] | None:
    title = normalize_title(meta.get("title"))
    parent_asin = meta.get("parent_asin")
    if not title or not isinstance(parent_asin, str) or not parent_asin:
        return None

    categories = normalize_categories(meta.get("categories"))
    main_category = meta.get("main_category")
    if not isinstance(main_category, str) or not main_category.strip():
        main_category = categories[0] if categories else "Amazon product"
    main_category = " ".join(main_category.split())[:120]

    return {
        "parent_asin": parent_asin,
        "title": title,
        "category": main_category,
        "category_path": categories,
        "leaf_category": categories[-1] if categories else main_category,
        "price": parse_price(meta.get("price")),
        "product_image": product_image(meta),
        "store": normalize_title(meta.get("store")),
    }


def reservoir_add(reservoir: list[Any], item: Any, seen: int, capacity: int, rng: random.Random) -> None:
    if len(reservoir) < capacity:
        reservoir.append(item)
        return
    position = rng.randrange(seen)
    if position < capacity:
        reservoir[position] = item


def sample_reviews(
    source: Source,
    capacity: int,
    rng: random.Random,
    max_records: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    reservoir: list[dict[str, Any]] = []
    eligible = 0

    for row in iter_jsonl(source, max_records=max_records):
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
            "review_text": " ".join(str(row.get("text") or "").split())[:900],
            "helpful_vote": row.get("helpful_vote") if isinstance(row.get("helpful_vote"), int) else 0,
            "verified_purchase": bool(row.get("verified_purchase", False)),
            "timestamp": row.get("timestamp") if isinstance(row.get("timestamp"), int) else None,
        }
        reservoir_add(reservoir, candidate, eligible, capacity, rng)

    return reservoir, eligible


def collect_metadata(
    source: Source,
    wanted_parent_asins: set[str],
    pool_capacity: int,
    rng: random.Random,
    max_records: int | None = None,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], int]:
    wanted: dict[str, dict[str, Any]] = {}
    pool: list[dict[str, Any]] = []
    eligible = 0

    for row in iter_jsonl(source, max_records=max_records):
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


def title_tokens(title: str) -> set[str]:
    return {word for word in WORD_RE.findall(title.casefold()) if len(word) > 2 and word not in STOPWORDS}


def title_similarity(left: str, right: str) -> float:
    a = title_tokens(left)
    b = title_tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def taxonomy_score(correct: dict[str, Any], candidate: dict[str, Any]) -> int:
    correct_path = [item.casefold() for item in correct.get("category_path", [])]
    candidate_path = [item.casefold() for item in candidate.get("category_path", [])]
    shared = 0
    for left, right in zip(correct_path, candidate_path):
        if left != right:
            break
        shared += 1
    if correct.get("leaf_category", "").casefold() == candidate.get("leaf_category", "").casefold():
        shared += 4
    elif correct.get("category", "").casefold() == candidate.get("category", "").casefold():
        shared += 2
    return shared


def make_choices(correct: dict[str, Any], pool: list[dict[str, Any]], rng: random.Random) -> list[str] | None:
    correct_title = correct["title"]
    correct_key = correct_title.casefold()
    ranked: list[tuple[float, float, str]] = []

    for item in pool:
        title = item["title"]
        if title.casefold() == correct_key:
            continue
        similarity = title_similarity(correct_title, title)
        # Near-duplicate listing titles make the question unfair.
        if similarity >= 0.72:
            continue
        tax = taxonomy_score(correct, item)
        # Light title overlap helps plausibility without requiring near duplicates.
        rank = tax + min(similarity, 0.45) * 2.0 + rng.random() * 0.35
        ranked.append((rank, similarity, title))

    ranked.sort(key=lambda item: item[0], reverse=True)
    candidate_window = ranked[: max(30, min(120, len(ranked)))]
    rng.shuffle(candidate_window)

    distractors: list[str] = []
    seen = {correct_key}
    for _, _, title in candidate_window:
        key = title.casefold()
        if key in seen:
            continue
        distractors.append(title)
        seen.add(key)
        if len(distractors) == 3:
            break

    if len(distractors) < 3:
        for _, _, title in ranked:
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


def source_label(source: Source) -> str:
    text = str(source).rstrip("/")
    name = text.rsplit("/", 1)[-1]
    for suffix in (".jsonl.gz", ".jsonl", ".gz"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name.replace("meta_", "")


def build_game_data(
    reviews_source: Source,
    metadata_source: Source,
    *,
    limit: int = 5000,
    seed: int = 1337,
    name: str | None = None,
    source_category: str | None = None,
    max_review_records: int | None = None,
    max_metadata_records: int | None = None,
) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("limit must be at least 1")

    rng = random.Random(seed)
    candidate_capacity = min(max(limit * 8, limit + 300), 60_000)
    distractor_capacity = min(max(limit * 6, 3_000), 30_000)

    candidates, eligible_reviews = sample_reviews(
        reviews_source, candidate_capacity, rng, max_records=max_review_records
    )
    wanted_ids = {item["parent_asin"] for item in candidates}
    metadata, distractor_pool, eligible_products = collect_metadata(
        metadata_source,
        wanted_ids,
        distractor_capacity,
        rng,
        max_records=max_metadata_records,
    )

    rng.shuffle(candidates)
    rounds: list[dict[str, Any]] = []
    seen_images: set[str] = set()
    seen_products: set[str] = set()

    for candidate in candidates:
        if len(rounds) >= limit:
            break
        image = candidate["image"]
        parent_asin = candidate["parent_asin"]
        if image in seen_images or parent_asin in seen_products:
            continue
        product = metadata.get(parent_asin)
        if not product:
            continue
        choices = make_choices(product, distractor_pool, rng)
        if not choices:
            continue

        asin = candidate.get("asin")
        public_product = {
            "title": product["title"],
            "category": product["category"],
            "category_path": product["category_path"],
            "leaf_category": product["leaf_category"],
            "price": product["price"],
            "product_image": product["product_image"],
            "store": product["store"],
            "asin": asin,
            "parent_asin": parent_asin,
            "source_url": f"https://www.amazon.com/dp/{asin}" if asin else None,
        }
        digest = hashlib.sha1(f"{parent_asin}|{image}".encode("utf-8")).hexdigest()[:14]
        rounds.append(
            {
                "id": digest,
                "source_category": source_category or product["category"],
                "review_image": image,
                "rating": candidate["rating"],
                "review_title": candidate["review_title"],
                "review_text": candidate["review_text"],
                "helpful_vote": candidate["helpful_vote"],
                "verified_purchase": candidate["verified_purchase"],
                "timestamp": candidate["timestamp"],
                "product": public_product,
                "choices": choices,
            }
        )
        seen_images.add(image)
        seen_products.add(parent_asin)

    label = source_category or source_label(metadata_source)
    return {
        "version": 2,
        "name": name or f"Amazon Reviews 2023: {label}",
        "source": "McAuley Lab Amazon Reviews 2023",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "categories": [label],
        "stats": {
            "eligible_image_reviews_seen": eligible_reviews,
            "eligible_metadata_products_seen": eligible_products,
            "sampled_review_candidates": len(candidates),
            "matched_sample_products": len(metadata),
            "distractor_pool_size": len(distractor_pool),
            "rounds_written": len(rounds),
        },
        "rounds": rounds,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviews", required=True, help="Review .jsonl/.jsonl.gz path or URL")
    parser.add_argument("--metadata", required=True, help="Matching metadata path or URL")
    parser.add_argument("--output", type=Path, default=Path("data/rounds.json"))
    parser.add_argument("--limit", type=int, default=5000, help="Maximum playable rounds to emit")
    parser.add_argument("--seed", type=int, default=1337, help="Deterministic sampling seed")
    parser.add_argument("--name", help="Optional dataset label shown in the UI")
    parser.add_argument("--source-category", help="Stable category key stored on every round")
    parser.add_argument("--max-review-records", type=int, help="Optional development cap on review rows scanned")
    parser.add_argument("--max-metadata-records", type=int, help="Optional development cap on metadata rows scanned")
    return parser.parse_args()


def validate_source(source: str) -> None:
    if is_url(source):
        return
    if not Path(source).is_file():
        raise SystemExit(f"Input file not found: {source}")


def main() -> None:
    args = parse_args()
    validate_source(args.reviews)
    validate_source(args.metadata)

    payload = build_game_data(
        args.reviews,
        args.metadata,
        limit=args.limit,
        seed=args.seed,
        name=args.name,
        source_category=args.source_category,
        max_review_records=args.max_review_records,
        max_metadata_records=args.max_metadata_records,
    )
    if not payload["rounds"]:
        raise SystemExit("No playable rounds were produced. Try a larger category or inspect the input schema.")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {len(payload['rounds']):,} rounds to {args.output}")
    print(json.dumps(payload["stats"], indent=2))


if __name__ == "__main__":
    main()
