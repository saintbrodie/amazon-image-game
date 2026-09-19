#!/usr/bin/env python3
"""Report or prune unreferenced files from the local review-image cache.

The command is dry-run by default. Pass --delete to remove orphaned files.
References can come from ordinary dataset JSON files or local sharded-pack
manifests. Multiple sources are unioned so one shared cache can safely serve
several packs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


def safe_relative_path(value: str) -> PurePosixPath:
    raw = str(value).strip()
    path = PurePosixPath(raw)
    if (
        not raw
        or raw.startswith("/")
        or "\\" in raw
        or path.is_absolute()
        or ".." in path.parts
    ):
        raise ValueError(f"unsafe relative path: {value}")
    return path


def safe_child(root: Path, relative: str) -> Path:
    path = safe_relative_path(relative)
    root_resolved = root.resolve()
    candidate = (root_resolved / Path(path)).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"path escapes root: {relative}") from exc
    return candidate


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: JSON root must be an object")
    return payload


def rounds_from_source(path: Path) -> Iterable[dict[str, Any]]:
    payload = load_json(path)
    if payload.get("format") == "amazon-image-game-sharded-pack":
        shards = payload.get("shards")
        if not isinstance(shards, list) or not shards:
            raise ValueError(f"{path}: sharded manifest must contain shards")
        for descriptor in shards:
            if not isinstance(descriptor, dict):
                raise ValueError(f"{path}: shard descriptors must be objects")
            relative = descriptor.get("path")
            if not isinstance(relative, str) or not relative:
                raise ValueError(f"{path}: shard descriptor missing path")
            shard_path = safe_child(path.parent, relative)
            if not shard_path.is_file():
                raise ValueError(f"{path}: missing shard file {relative}")
            shard = load_json(shard_path)
            if shard.get("format") != "amazon-image-game-shard":
                raise ValueError(f"{shard_path}: invalid shard format")
            rounds = shard.get("rounds")
            if not isinstance(rounds, list):
                raise ValueError(f"{shard_path}: shard must contain rounds")
            for round_data in rounds:
                if isinstance(round_data, dict):
                    yield round_data
        return

    rounds = payload.get("rounds")
    if not isinstance(rounds, list):
        raise ValueError(f"{path}: dataset must contain rounds")
    for round_data in rounds:
        if isinstance(round_data, dict):
            yield round_data


def normalize_public_prefix(value: str) -> PurePosixPath:
    raw = str(value).strip().strip("/")
    if not raw:
        raise ValueError("public_prefix must not be empty")
    return safe_relative_path(raw)


def referenced_cache_paths(sources: list[Path], public_prefix: str) -> tuple[set[PurePosixPath], int, int]:
    prefix = normalize_public_prefix(public_prefix)
    referenced: set[PurePosixPath] = set()
    round_count = 0
    external_or_other = 0

    for source in sources:
        for round_data in rounds_from_source(source):
            round_count += 1
            image = round_data.get("review_image")
            if not isinstance(image, str) or not image.strip():
                external_or_other += 1
                continue
            raw = image.strip()
            if "://" in raw or raw.startswith("//"):
                external_or_other += 1
                continue
            try:
                path = safe_relative_path(raw)
            except ValueError:
                external_or_other += 1
                continue
            if path.parts[: len(prefix.parts)] != prefix.parts:
                external_or_other += 1
                continue
            relative_parts = path.parts[len(prefix.parts) :]
            if not relative_parts:
                external_or_other += 1
                continue
            referenced.add(PurePosixPath(*relative_parts))

    return referenced, round_count, external_or_other


def scan_cache(asset_dir: Path) -> tuple[dict[PurePosixPath, Path], list[str]]:
    if not asset_dir.exists():
        return {}, []
    if not asset_dir.is_dir():
        raise ValueError(f"asset_dir is not a directory: {asset_dir}")

    root = asset_dir.resolve()
    files: dict[PurePosixPath, Path] = {}
    skipped: list[str] = []
    for path in asset_dir.rglob("*"):
        if path.is_symlink():
            skipped.append(str(path))
            continue
        if not path.is_file():
            continue
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError:
            skipped.append(str(path))
            continue
        files[PurePosixPath(relative.as_posix())] = resolved
    return files, skipped


def maintenance_report(
    *,
    sources: list[Path],
    asset_dir: Path,
    public_prefix: str,
    delete: bool = False,
) -> dict[str, Any]:
    if not sources:
        raise ValueError("at least one dataset or manifest source is required")
    for source in sources:
        if not source.is_file():
            raise ValueError(f"source does not exist: {source}")

    referenced, rounds_scanned, external_or_other = referenced_cache_paths(sources, public_prefix)
    cache_files, skipped = scan_cache(asset_dir)

    existing_referenced = sorted(set(cache_files) & referenced, key=str)
    missing_referenced = sorted(referenced - set(cache_files), key=str)
    orphaned = sorted(set(cache_files) - referenced, key=str)

    cache_bytes = sum(path.stat().st_size for path in cache_files.values())
    referenced_bytes = sum(cache_files[path].stat().st_size for path in existing_referenced)
    orphan_bytes = sum(cache_files[path].stat().st_size for path in orphaned)

    deleted_files = 0
    deleted_bytes = 0
    if delete:
        for relative in orphaned:
            path = cache_files[relative]
            size = path.stat().st_size
            path.unlink()
            deleted_files += 1
            deleted_bytes += size

        root = asset_dir.resolve()
        directories = sorted(
            (path for path in asset_dir.rglob("*") if path.is_dir() and not path.is_symlink()),
            key=lambda value: len(value.parts),
            reverse=True,
        )
        for directory in directories:
            resolved = directory.resolve()
            try:
                resolved.relative_to(root)
            except ValueError:
                continue
            try:
                directory.rmdir()
            except OSError:
                pass

    return {
        "dry_run": not delete,
        "sources": [str(path) for path in sources],
        "source_count": len(sources),
        "rounds_scanned": rounds_scanned,
        "external_or_noncache_rounds": external_or_other,
        "public_prefix": str(normalize_public_prefix(public_prefix)),
        "asset_dir": str(asset_dir),
        "cache_files": len(cache_files),
        "cache_bytes": cache_bytes,
        "referenced_paths": len(referenced),
        "referenced_existing_files": len(existing_referenced),
        "referenced_bytes": referenced_bytes,
        "referenced_missing_files": len(missing_referenced),
        "missing_references": [str(path) for path in missing_referenced],
        "orphan_files": len(orphaned),
        "orphan_bytes": orphan_bytes,
        "orphan_paths": [str(path) for path in orphaned],
        "skipped_symlinks_or_unsafe": skipped,
        "deleted_files": deleted_files,
        "deleted_bytes": deleted_bytes,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="+", type=Path, help="Dataset JSON file(s) or local sharded manifest(s)")
    parser.add_argument("--asset-dir", type=Path, default=Path("assets/review-cache"))
    parser.add_argument("--public-prefix", default="assets/review-cache")
    parser.add_argument("--delete", action="store_true", help="Delete orphaned files; default is report-only dry run")
    parser.add_argument("--report", type=Path, help="Optional JSON report output")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        report = maintenance_report(
            sources=args.sources,
            asset_dir=args.asset_dir,
            public_prefix=args.public_prefix,
            delete=args.delete,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")

    mode = "PRUNED" if args.delete else "DRY RUN"
    print(
        f"{mode}: {report['cache_files']:,} cache files, "
        f"{report['referenced_existing_files']:,} referenced, "
        f"{report['orphan_files']:,} orphaned"
    )
    print(
        f"Cache size {report['cache_bytes'] / 1024 / 1024:.1f} MiB; "
        f"reclaimable {report['orphan_bytes'] / 1024 / 1024:.1f} MiB"
    )
    if report["referenced_missing_files"]:
        print(f"Warning: {report['referenced_missing_files']:,} referenced cache files are missing")
    if args.delete:
        print(
            f"Deleted {report['deleted_files']:,} files "
            f"({report['deleted_bytes'] / 1024 / 1024:.1f} MiB)"
        )
    else:
        print("No files deleted. Re-run with --delete after reviewing the report.")


if __name__ == "__main__":
    main()
