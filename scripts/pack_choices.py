#!/usr/bin/env python3
"""Pack-level answer-choice reranking.

The streaming dataset builder already selects plausible distractors from a large
metadata reservoir. This module reuses those candidate titles across all rounds
in the same category, then picks the three titles most textually related to each
correct product. That preserves the streaming/bounded-memory design while
avoiding the easy choices caused by randomly sampling a broad top-candidate
window.
"""

from __future__ import annotations

import math
import random
import re
from collections import defaultdict
from typing import Any, Iterable

WORD_RE = re.compile(r"[a-z0-9]+")
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is",
    "it", "of", "on", "or", "the", "this", "to", "with", "your", "you", "my", "our",
    "pack", "set", "new", "size", "inch", "inches", "black", "white", "small", "large",
}


def title_tokens(value: str) -> set[str]:
    return {
        token
        for token in WORD_RE.findall((value or "").casefold())
        if len(token) > 2 and token not in STOPWORDS
    }


def title_metrics(left: str, right: str) -> tuple[float, float, int]:
    """Return Jaccard, binary-token cosine, and shared-token count."""
    a = title_tokens(left)
    b = title_tokens(right)
    if not a or not b:
        return 0.0, 0.0, 0
    shared = len(a & b)
    jaccard = shared / len(a | b)
    cosine = shared / math.sqrt(len(a) * len(b))
    return jaccard, cosine, shared


def candidate_banks(rounds: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    """Collect unique existing choice titles by source category."""
    banks: dict[str, list[str]] = defaultdict(list)
    seen: dict[str, set[str]] = defaultdict(set)

    for round_data in rounds:
        if not isinstance(round_data, dict):
            continue
        category = str(round_data.get("source_category") or "Other")
        product = round_data.get("product") if isinstance(round_data.get("product"), dict) else {}
        candidates: list[Any] = []
        choices = round_data.get("choices")
        if isinstance(choices, list):
            candidates.extend(choices)
        candidates.append(product.get("title"))

        for title in candidates:
            if not isinstance(title, str) or not title.strip():
                continue
            cleaned = " ".join(title.split())
            key = cleaned.casefold()
            if key in seen[category]:
                continue
            seen[category].add(key)
            banks[category].append(cleaned)

    return dict(banks)


def rank_candidate(correct: str, candidate: str, jitter: float = 0.0) -> tuple[float, float]:
    jaccard, cosine, shared = title_metrics(correct, candidate)
    # Jaccard is aligned with the quality audit. Cosine and a small shared-token
    # bonus help long Amazon listing titles that contain the same product noun.
    score = jaccard * 14.0 + cosine * 4.0 + min(shared, 4) * 0.2 + jitter
    return score, jaccard


def choose_distractors(
    correct: str,
    candidates: Iterable[str],
    *,
    rng: random.Random,
    count: int = 3,
    near_duplicate_cutoff: float = 0.62,
) -> list[str]:
    correct_key = correct.casefold().strip()
    ranked: list[tuple[float, str]] = []
    seen: set[str] = {correct_key}

    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        title = " ".join(candidate.split())
        key = title.casefold()
        if not title or key in seen:
            continue
        seen.add(key)
        score, jaccard = rank_candidate(correct, title, rng.random() * 0.03)
        # Very similar listing titles can describe the same model/variant and
        # make the intended answer ambiguous.
        if jaccard >= near_duplicate_cutoff:
            continue
        ranked.append((score, title))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [title for _, title in ranked[:count]]


def rerank_pack_choices(
    rounds: list[dict[str, Any]],
    *,
    seed: int,
    banks: dict[str, list[str]] | None = None,
) -> dict[str, int]:
    """Rewrite choices in place and return simple reranking statistics."""
    if banks is None:
        banks = candidate_banks(rounds)

    all_candidates: list[str] = []
    global_seen: set[str] = set()
    for titles in banks.values():
        for title in titles:
            key = title.casefold()
            if key not in global_seen:
                global_seen.add(key)
                all_candidates.append(title)

    changed = 0
    fallback = 0
    for round_data in rounds:
        if not isinstance(round_data, dict):
            continue
        product = round_data.get("product") if isinstance(round_data.get("product"), dict) else {}
        correct = product.get("title")
        if not isinstance(correct, str) or not correct:
            fallback += 1
            continue

        category = str(round_data.get("source_category") or "Other")
        category_candidates = banks.get(category) or []
        rng = random.Random(f"{seed}|{round_data.get('id', '')}|pack-choices-v2")
        distractors = choose_distractors(correct, category_candidates, rng=rng)
        if len(distractors) < 3:
            distractors = choose_distractors(correct, all_candidates, rng=rng)
        if len(distractors) < 3:
            fallback += 1
            continue

        choices = distractors[:3] + [correct]
        rng.shuffle(choices)
        if choices != round_data.get("choices"):
            changed += 1
        round_data["choices"] = choices

    return {"rounds_reranked": changed, "rounds_fallback": fallback}
