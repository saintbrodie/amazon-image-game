#!/usr/bin/env python3
"""Optional local image-classification adapter for review-media screening.

This module deliberately keeps heavyweight ML imports lazy. Normal dataset
screening and CI can import the helper without installing Transformers or
PyTorch. When enabled, a Hugging Face image-classification model contributes
structured review flags and score metadata to screen_dataset.py.

The built-in defaults target Falconsai/nsfw_image_detection, whose labels are
"normal" and "nsfw". Other binary/multi-label image classifiers can be used by
supplying the positive label names explicitly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable

DEFAULT_MODEL_ID = "Falconsai/nsfw_image_detection"
DEFAULT_POSITIVE_LABELS = ("nsfw",)
DEFAULT_REVIEW_THRESHOLD = 0.60
DEFAULT_HIGH_THRESHOLD = 0.95


def normalize_label(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").replace("-", " ").split())


def validate_thresholds(review_threshold: float, high_threshold: float) -> tuple[float, float]:
    review = float(review_threshold)
    high = float(high_threshold)
    if not 0 <= review <= 1:
        raise ValueError("safety review threshold must be between 0 and 1")
    if not 0 <= high <= 1:
        raise ValueError("safety high threshold must be between 0 and 1")
    if review > high:
        raise ValueError("safety review threshold must be <= high threshold")
    return review, high


def normalize_scores(output: Any) -> dict[str, float]:
    """Normalize a Transformers image-classification result into label scores."""
    rows = output
    if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], list):
        rows = rows[0]
    if not isinstance(rows, list):
        raise ValueError("image safety model returned an unexpected result")

    scores: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = normalize_label(row.get("label"))
        score = row.get("score")
        if not label or isinstance(score, bool) or not isinstance(score, (int, float)):
            continue
        numeric = float(score)
        if numeric < 0 or numeric > 1:
            continue
        scores[label] = max(scores.get(label, 0.0), numeric)
    if not scores:
        raise ValueError("image safety model returned no usable label scores")
    return scores


def evaluate_scores(
    output: Any,
    *,
    model_id: str,
    positive_labels: Iterable[str] = DEFAULT_POSITIVE_LABELS,
    review_threshold: float = DEFAULT_REVIEW_THRESHOLD,
    high_threshold: float = DEFAULT_HIGH_THRESHOLD,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Convert classifier output into the project's screening flag schema."""
    review, high = validate_thresholds(review_threshold, high_threshold)
    positives = {normalize_label(label) for label in positive_labels if normalize_label(label)}
    if not positives:
        raise ValueError("at least one safety positive label is required")

    scores = normalize_scores(output)
    matched = {label: score for label, score in scores.items() if label in positives}
    positive_score = max(matched.values(), default=0.0)

    severity = None
    if positive_score >= high:
        severity = "high"
    elif positive_score >= review:
        severity = "medium"

    flags: list[dict[str, str]] = []
    if severity:
        flags.append({
            "name": "model_nsfw_content",
            "severity": severity,
            "source": "image_model",
        })

    details = {
        "model": str(model_id),
        "positive_labels": sorted(positives),
        "positive_score": round(positive_score, 6),
        "review_threshold": review,
        "high_threshold": high,
        "scores": {label: round(score, 6) for label, score in sorted(scores.items())},
    }
    return flags, details


def parse_device(value: str | None) -> int | str | None:
    if value is None or not str(value).strip() or str(value).strip().lower() == "auto":
        return None
    normalized = str(value).strip().lower()
    if normalized == "cpu":
        return -1
    try:
        return int(normalized)
    except ValueError:
        return value


class TransformerImageSafetyClassifier:
    """Lazy Hugging Face image-classification wrapper with per-path caching."""

    def __init__(
        self,
        *,
        model_id: str = DEFAULT_MODEL_ID,
        revision: str | None = None,
        positive_labels: Iterable[str] = DEFAULT_POSITIVE_LABELS,
        review_threshold: float = DEFAULT_REVIEW_THRESHOLD,
        high_threshold: float = DEFAULT_HIGH_THRESHOLD,
        device: str | None = None,
        pipeline_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.model_id = str(model_id).strip()
        if not self.model_id:
            raise ValueError("safety model ID cannot be empty")
        self.revision = str(revision).strip() if revision else None
        self.positive_labels = tuple(
            label for label in (normalize_label(value) for value in positive_labels) if label
        )
        if not self.positive_labels:
            raise ValueError("at least one safety positive label is required")
        self.review_threshold, self.high_threshold = validate_thresholds(review_threshold, high_threshold)
        self.device = device
        self.pipeline_factory = pipeline_factory
        self._pipeline: Any = None
        self._cache: dict[str, tuple[list[dict[str, str]], dict[str, Any]]] = {}

    def describe(self) -> dict[str, Any]:
        return {
            "type": "transformers_image_classification",
            "model": self.model_id,
            "revision": self.revision,
            "positive_labels": list(self.positive_labels),
            "review_threshold": self.review_threshold,
            "high_threshold": self.high_threshold,
            "device": self.device or "auto",
        }

    def _build_pipeline(self) -> Any:
        factory = self.pipeline_factory
        if factory is None:
            try:
                from transformers import pipeline
            except ImportError as exc:
                raise RuntimeError(
                    "Image safety model screening requires Transformers and PyTorch. "
                    "Install requirements-screening-model.txt and a compatible PyTorch build."
                ) from exc
            factory = pipeline

        kwargs: dict[str, Any] = {
            "task": "image-classification",
            "model": self.model_id,
        }
        if self.revision:
            kwargs["revision"] = self.revision
        parsed_device = parse_device(self.device)
        if parsed_device is not None:
            kwargs["device"] = parsed_device
        return factory(**kwargs)

    def _get_pipeline(self) -> Any:
        if self._pipeline is None:
            self._pipeline = self._build_pipeline()
        return self._pipeline

    def classify(self, path: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
        key = str(path.resolve())
        cached = self._cache.get(key)
        if cached is not None:
            flags, details = cached
            return [dict(flag) for flag in flags], dict(details)

        try:
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError("Image safety model screening requires Pillow") from exc

        try:
            with Image.open(path) as image:
                prepared = image.convert("RGB")
                output = self._get_pipeline()(prepared, top_k=None)
        except (OSError, ValueError) as exc:
            raise ValueError(f"image safety model could not classify {path}: {exc}") from exc

        flags, details = evaluate_scores(
            output,
            model_id=self.model_id,
            positive_labels=self.positive_labels,
            review_threshold=self.review_threshold,
            high_threshold=self.high_threshold,
        )
        self._cache[key] = ([dict(flag) for flag in flags], dict(details))
        return flags, details
