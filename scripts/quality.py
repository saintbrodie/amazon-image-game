#!/usr/bin/env python3
"""Heuristic round-quality analysis used for curation and dataset audits.

These scores are triage aids, not ground truth. They intentionally use only
round text/metadata already present in a generated game pack.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any
from urllib.parse import urlparse

WORD_RE = re.compile(r"[a-z0-9]+")
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is",
    "it", "of", "on", "or", "the", "this", "to", "with", "your", "you", "my", "our",
    "pack", "set", "new", "size", "inch", "inches", "black", "white", "small", "large",
}


def tokens(value: Any) -> set[str]:
    if not isinstance(value, str):
        return set()
    return {
        token
        for token in WORD_RE.findall(value.casefold())
        if len(token) > 2 and token not in STOPWORDS
    }


def jaccard(left: Any, right: Any) -> float:
    a = tokens(left)
    b = tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def image_host(round_data: dict[str, Any]) -> str:
    value = round_data.get("review_image")
    if not isinstance(value, str):
        return "missing"
    parsed = urlparse(value)
    if parsed.netloc:
        return parsed.netloc.casefold()
    if value.startswith(("assets/", "./", "../")):
        return "local"
    return "unknown"


def review_leak_ratio(round_data: dict[str, Any]) -> float:
    product = round_data.get("product") if isinstance(round_data.get("product"), dict) else {}
    title_tokens = tokens(product.get("title"))
    if not title_tokens:
        return 0.0
    clue_tokens = tokens(
        f"{round_data.get('review_title') or ''} {round_data.get('review_text') or ''}"
    )
    return len(title_tokens & clue_tokens) / len(title_tokens)


def choice_similarities(round_data: dict[str, Any]) -> list[float]:
    product = round_data.get("product") if isinstance(round_data.get("product"), dict) else {}
    correct = product.get("title")
    choices = round_data.get("choices")
    if not isinstance(correct, str) or not isinstance(choices, list):
        return []
    return [jaccard(correct, choice) for choice in choices if isinstance(choice, str) and choice != correct]


def analyze_round(round_data: dict[str, Any]) -> dict[str, Any]:
    product = round_data.get("product") if isinstance(round_data.get("product"), dict) else {}
    product_title = product.get("title") if isinstance(product.get("title"), str) else ""
    review_text = round_data.get("review_text") if isinstance(round_data.get("review_text"), str) else ""
    review_title = round_data.get("review_title") if isinstance(round_data.get("review_title"), str) else ""
    similarities = choice_similarities(round_data)
    max_similarity = max(similarities, default=0.0)
    mean_similarity = sum(similarities) / len(similarities) if similarities else 0.0
    leak_ratio = review_leak_ratio(round_data)

    # Higher means the answer choices are textually harder to distinguish.
    difficulty = round(100 * min(1.0, 0.78 * max_similarity + 0.22 * mean_similarity))

    flags: list[str] = []
    priority = 0

    if not review_text.strip():
        flags.append("missing_review_text")
        priority += 8
    elif len(review_text.strip()) < 35:
        flags.append("very_short_review_text")
        priority += 4

    if len(product_title) > 170:
        flags.append("very_long_product_title")
        priority += 10
    elif len(product_title) > 120:
        flags.append("long_product_title")
        priority += 5

    if max_similarity >= 0.65:
        flags.append("near_duplicate_answer_title")
        priority += 30
    elif max_similarity >= 0.45:
        flags.append("high_answer_title_similarity")
        priority += 14

    if similarities and max_similarity <= 0.03:
        flags.append("very_dissimilar_answer_titles")
        priority += 8

    if leak_ratio >= 0.75 and len(tokens(product_title)) >= 2:
        flags.append("review_strongly_reveals_product_title")
        priority += 28
    elif leak_ratio >= 0.5 and len(tokens(product_title)) >= 2:
        flags.append("review_may_reveal_product_title")
        priority += 14

    rating = round_data.get("rating")
    if rating is None:
        flags.append("missing_rating")
        priority += 2

    if not product.get("source_url"):
        flags.append("missing_product_source")
        priority += 2

    if image_host(round_data) in {"missing", "unknown"}:
        flags.append("unusual_image_reference")
        priority += 18

    # Empty or suspiciously repeated choices should already fail validation, but
    # surfacing them here makes audits useful even before validation is run.
    choices = round_data.get("choices") if isinstance(round_data.get("choices"), list) else []
    normalized_choices = [choice.casefold().strip() for choice in choices if isinstance(choice, str)]
    if len(normalized_choices) != 4:
        flags.append("wrong_choice_count")
        priority += 40
    elif len(set(normalized_choices)) != 4:
        flags.append("duplicate_choices")
        priority += 45

    return {
        "difficulty_score": difficulty,
        "curation_priority": min(100, priority),
        "flags": flags,
        "choice_similarity_max": round(max_similarity, 4),
        "choice_similarity_mean": round(mean_similarity, 4),
        "review_title_leak_ratio": round(leak_ratio, 4),
        "image_host": image_host(round_data),
    }


def annotate_dataset(payload: dict[str, Any]) -> dict[str, Any]:
    rounds = payload.get("rounds")
    if not isinstance(rounds, list):
        raise ValueError("dataset must contain a rounds array")
    for round_data in rounds:
        if isinstance(round_data, dict):
            round_data["analysis"] = analyze_round(round_data)
    return payload


def audit_dataset(payload: dict[str, Any]) -> dict[str, Any]:
    rounds = payload.get("rounds")
    if not isinstance(rounds, list):
        raise ValueError("dataset must contain a rounds array")

    categories: Counter[str] = Counter()
    ratings: Counter[str] = Counter()
    flags: Counter[str] = Counter()
    hosts: Counter[str] = Counter()
    difficulty_buckets: Counter[str] = Counter()
    priority_buckets: Counter[str] = Counter()
    verified = 0
    helpful_reviews = 0
    analyzed: list[dict[str, Any]] = []

    for round_data in rounds:
        if not isinstance(round_data, dict):
            continue
        analysis = analyze_round(round_data)
        analyzed.append(analysis)
        category = round_data.get("source_category") or (
            round_data.get("product", {}).get("category")
            if isinstance(round_data.get("product"), dict)
            else None
        ) or "Other"
        categories[str(category)] += 1
        rating = round_data.get("rating")
        ratings[str(int(rating)) if isinstance(rating, (int, float)) else "missing"] += 1
        flags.update(analysis["flags"])
        hosts[analysis["image_host"]] += 1
        difficulty = analysis["difficulty_score"]
        if difficulty < 20:
            difficulty_buckets["very_easy"] += 1
        elif difficulty < 40:
            difficulty_buckets["easy"] += 1
        elif difficulty < 60:
            difficulty_buckets["medium"] += 1
        elif difficulty < 80:
            difficulty_buckets["hard"] += 1
        else:
            difficulty_buckets["very_hard"] += 1
        priority = analysis["curation_priority"]
        if priority >= 40:
            priority_buckets["high"] += 1
        elif priority >= 15:
            priority_buckets["medium"] += 1
        else:
            priority_buckets["low"] += 1
        if round_data.get("verified_purchase") is True:
            verified += 1
        if isinstance(round_data.get("helpful_vote"), int) and round_data["helpful_vote"] > 0:
            helpful_reviews += 1

    total = len(analyzed)
    avg_difficulty = round(sum(row["difficulty_score"] for row in analyzed) / total, 1) if total else 0.0
    avg_priority = round(sum(row["curation_priority"] for row in analyzed) / total, 1) if total else 0.0

    return {
        "rounds": total,
        "categories": dict(categories.most_common()),
        "ratings": dict(sorted(ratings.items())),
        "difficulty_buckets": dict(difficulty_buckets),
        "average_difficulty_score": avg_difficulty,
        "curation_priority_buckets": dict(priority_buckets),
        "average_curation_priority": avg_priority,
        "quality_flags": dict(flags.most_common()),
        "image_hosts": dict(hosts.most_common()),
        "verified_purchase_rounds": verified,
        "reviews_with_helpful_votes": helpful_reviews,
    }
