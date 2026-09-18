#!/usr/bin/env python3
"""Cache review images locally and optionally remove image-level duplicates.

Exact byte deduplication uses only the Python standard library. Optional
perceptual near-duplicate detection uses Pillow when --perceptual-threshold is
provided. Downloads are written to a content-addressed cache as they complete,
so image bytes are not accumulated in memory across the whole pack.

This tool copies third-party images. Use it only where you have an appropriate
right or permission to host those files.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import mimetypes
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

CONTENT_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
    "image/bmp": ".bmp",
    "image/tiff": ".tif",
    "image/svg+xml": ".svg",
}
ALLOWED_SUFFIXES = set(CONTENT_EXTENSIONS.values()) | {".jpeg", ".tiff"}


def is_remote(value: str) -> bool:
    return urlparse(value).scheme in {"http", "https"}


def extension_for(source: str, content_type: str | None, data: bytes | None = None) -> str:
    if data:
        if data.startswith(b"\xff\xd8\xff"):
            return ".jpg"
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return ".png"
        if data.startswith((b"GIF87a", b"GIF89a")):
            return ".gif"
        if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return ".webp"
        if data.startswith(b"BM"):
            return ".bmp"
        if data.startswith((b"II*\x00", b"MM\x00*")):
            return ".tif"
        if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in {b"avif", b"avis"}:
            return ".avif"
        prefix = data[:1024].lstrip().lower()
        if prefix.startswith(b"<svg") or (prefix.startswith(b"<?xml") and b"<svg" in prefix):
            return ".svg"

    normalized = (content_type or "").split(";", 1)[0].strip().casefold()
    if normalized in CONTENT_EXTENSIONS:
        return CONTENT_EXTENSIONS[normalized]
    suffix = Path(urlparse(source).path).suffix.casefold()
    if suffix in ALLOWED_SUFFIXES:
        return ".jpg" if suffix == ".jpeg" else ".tif" if suffix == ".tiff" else suffix
    guessed = mimetypes.guess_type(source)[0]
    if guessed in CONTENT_EXTENSIONS:
        return CONTENT_EXTENSIONS[guessed]
    return ".img"


def read_limited(handle: Any, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        remaining = max_bytes + 1 - total
        if remaining <= 0:
            raise ValueError(f"image exceeds maximum size of {max_bytes:,} bytes")
        chunk = handle.read(min(1024 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(f"image exceeds maximum size of {max_bytes:,} bytes")
    data = b"".join(chunks)
    if not data:
        raise ValueError("image response was empty")
    return data


def fetch_image(source: str, *, web_root: Path, timeout: float, max_bytes: int) -> tuple[bytes, str | None]:
    if is_remote(source):
        request = urllib.request.Request(
            source,
            headers={
                "User-Agent": "Mozilla/5.0 amazon-image-game-cache/1.0",
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status >= 400:
                raise ValueError(f"HTTP {status}")
            return read_limited(response, max_bytes), response.headers.get("Content-Type")

    local_path = (web_root / source).resolve()
    root_resolved = web_root.resolve()
    try:
        local_path.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"local image path escapes web root: {source}") from exc
    if not local_path.is_file():
        raise FileNotFoundError(local_path)
    if local_path.stat().st_size > max_bytes:
        raise ValueError(f"image exceeds maximum size of {max_bytes:,} bytes")
    return local_path.read_bytes(), mimetypes.guess_type(local_path.name)[0]


def dhash64(data: bytes) -> int:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise RuntimeError(
            "Perceptual deduplication requires Pillow. Install it with: python -m pip install Pillow"
        ) from exc

    with Image.open(io.BytesIO(data)) as image:
        image = ImageOps.exif_transpose(image).convert("L").resize((9, 8), Image.Resampling.LANCZOS)
        pixels = list(image.getdata())
    value = 0
    bit = 0
    for row in range(8):
        offset = row * 9
        for column in range(8):
            if pixels[offset + column] > pixels[offset + column + 1]:
                value |= 1 << bit
            bit += 1
    return value


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


class PerceptualIndex:
    """Hamming-distance index using the pigeonhole principle."""

    def __init__(self, threshold: int):
        if threshold < 0 or threshold > 16:
            raise ValueError("perceptual threshold must be between 0 and 16")
        self.threshold = threshold
        self.parts = threshold + 1
        self.hashes: list[int] = []
        self.buckets: dict[tuple[int, int], set[int]] = {}

    def _segments(self, value: int):
        base = 64 // self.parts
        extra = 64 % self.parts
        shift = 0
        for part in range(self.parts):
            width = base + (1 if part < extra else 0)
            mask = (1 << width) - 1
            yield part, (value >> shift) & mask
            shift += width

    def find(self, value: int) -> int | None:
        candidates: set[int] = set()
        for key in self._segments(value):
            candidates.update(self.buckets.get(key, ()))
        for index in candidates:
            if hamming_distance(value, self.hashes[index]) <= self.threshold:
                return index
        return None

    def add(self, value: int) -> int:
        index = len(self.hashes)
        self.hashes.append(value)
        for key in self._segments(value):
            self.buckets.setdefault(key, set()).add(index)
        return index


def public_asset_path(public_prefix: str, filename: str) -> str:
    prefix = public_prefix.strip().strip("/")
    return str(PurePosixPath(prefix) / filename) if prefix else filename


def cache_dataset(
    payload: dict[str, Any],
    *,
    asset_dir: Path,
    public_prefix: str,
    web_root: Path = Path("."),
    workers: int = 12,
    timeout: float = 20.0,
    max_bytes: int = 20 * 1024 * 1024,
    keep_failed: bool = False,
    keep_exact_duplicates: bool = False,
    perceptual_threshold: int | None = None,
) -> dict[str, Any]:
    rounds = payload.get("rounds")
    if not isinstance(rounds, list):
        raise ValueError("dataset must contain a rounds array")
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")
    if workers < 1:
        raise ValueError("workers must be positive")
    if perceptual_threshold is not None:
        PerceptualIndex(perceptual_threshold)
        try:
            import PIL  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "Perceptual deduplication requires Pillow. Install it with: python -m pip install Pillow"
            ) from exc

    sources = sorted({
        round_data.get("review_image")
        for round_data in rounds
        if isinstance(round_data, dict) and isinstance(round_data.get("review_image"), str)
    })
    source_results: dict[str, dict[str, Any]] = {}
    asset_dir.mkdir(parents=True, exist_ok=True)

    def process(source: str) -> tuple[str, dict[str, Any]]:
        try:
            data, content_type = fetch_image(source, web_root=web_root, timeout=timeout, max_bytes=max_bytes)
            digest = hashlib.sha256(data).hexdigest()
            extension = extension_for(source, content_type, data)
            filename = f"{digest[:24]}{extension}"
            output_path = asset_dir / filename
            written = 0
            try:
                with output_path.open("xb") as handle:
                    handle.write(data)
                written = len(data)
            except FileExistsError:
                pass
            perceptual = dhash64(data) if perceptual_threshold is not None else None
            return source, {
                "ok": True,
                "sha256": digest,
                "filename": filename,
                "perceptual": perceptual,
                "written_bytes": written,
            }
        except Exception as exc:
            return source, {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(process, source) for source in sources]
        for future in as_completed(futures):
            source, result = future.result()
            source_results[source] = result

    accepted_sha: set[str] = set()
    unique_file_sha: set[str] = set()
    perceptual_index = PerceptualIndex(perceptual_threshold) if perceptual_threshold is not None else None
    output_rounds: list[dict[str, Any]] = []
    failed = 0
    exact_duplicates = 0
    perceptual_duplicates = 0
    bytes_written = sum(int(result.get("written_bytes", 0)) for result in source_results.values())

    for round_data in rounds:
        if not isinstance(round_data, dict):
            continue
        source = round_data.get("review_image")
        result = source_results.get(source) if isinstance(source, str) else None
        if not result or not result.get("ok"):
            failed += 1
            if keep_failed:
                output_rounds.append(copy.deepcopy(round_data))
            continue

        digest = result["sha256"]
        if digest in accepted_sha and not keep_exact_duplicates:
            exact_duplicates += 1
            continue

        if perceptual_index is not None:
            value = result["perceptual"]
            if perceptual_index.find(value) is not None:
                perceptual_duplicates += 1
                continue
            perceptual_index.add(value)

        updated = copy.deepcopy(round_data)
        updated["review_image_original"] = source
        updated["review_image"] = public_asset_path(public_prefix, result["filename"])
        updated["review_image_sha256"] = digest
        if result.get("perceptual") is not None:
            updated["review_image_dhash"] = f"{result['perceptual']:016x}"
        output_rounds.append(updated)
        accepted_sha.add(digest)
        unique_file_sha.add(digest)

    output = copy.deepcopy(payload)
    output["rounds"] = output_rounds
    output["image_cache"] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "asset_prefix": public_prefix,
        "source_images": len(sources),
        "rounds_before": len(rounds),
        "rounds_after": len(output_rounds),
        "failed_rounds": failed,
        "exact_duplicate_rounds_removed": exact_duplicates,
        "perceptual_duplicate_rounds_removed": perceptual_duplicates,
        "perceptual_threshold": perceptual_threshold,
        "unique_files_referenced": len(unique_file_sha),
        "bytes_written_this_run": bytes_written,
    }
    stats = output.get("stats")
    if not isinstance(stats, dict):
        stats = {}
        output["stats"] = stats
    stats["rounds_written"] = len(output_rounds)
    stats["image_cache"] = copy.deepcopy(output["image_cache"])
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/rounds.cached.json"))
    parser.add_argument("--asset-dir", type=Path, default=Path("assets/review-cache"))
    parser.add_argument(
        "--public-prefix",
        default="assets/review-cache",
        help="Browser path stored in review_image for files written to --asset-dir",
    )
    parser.add_argument("--web-root", type=Path, default=Path("."), help="Root used to resolve existing local image paths")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--max-mb", type=float, default=20.0, help="Maximum bytes downloaded per image")
    parser.add_argument("--keep-failed", action="store_true", help="Keep rounds whose images could not be cached")
    parser.add_argument("--keep-exact-duplicates", action="store_true")
    parser.add_argument(
        "--perceptual-threshold",
        type=int,
        help="Enable Pillow-based dHash dedupe; 4 is a conservative starting point",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = json.loads(args.dataset.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("dataset root must be a JSON object")
    try:
        result = cache_dataset(
            payload,
            asset_dir=args.asset_dir,
            public_prefix=args.public_prefix,
            web_root=args.web_root,
            workers=args.workers,
            timeout=args.timeout,
            max_bytes=max(1, int(args.max_mb * 1024 * 1024)),
            keep_failed=args.keep_failed,
            keep_exact_duplicates=args.keep_exact_duplicates,
            perceptual_threshold=args.perceptual_threshold,
        )
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    summary = result["image_cache"]
    print(f"Wrote {summary['rounds_after']:,} rounds to {args.output}")
    print(f"Cached {summary['unique_files_referenced']:,} unique referenced files ({summary['bytes_written_this_run'] / 1024 / 1024:.1f} MiB written this run)")
    print(f"Dropped {summary['failed_rounds']:,} failed, {summary['exact_duplicate_rounds_removed']:,} exact duplicates, and {summary['perceptual_duplicate_rounds_removed']:,} perceptual duplicates")


if __name__ == "__main__":
    main()
