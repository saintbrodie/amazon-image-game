#!/usr/bin/env python3
"""Publish cached review images to S3-compatible object storage.

The command is dry-run by default. With --apply it uploads every ordinary file
under the configured review-image cache to an S3-compatible bucket, then writes
an asset-delivery mapping into the sharded dataset manifest. The browser uses
that small manifest mapping to resolve cached review-image paths to the public
object-storage/CDN base URL, so shard files do not need to be rewritten.

AWS S3, Cloudflare R2, MinIO, Wasabi, Backblaze B2 S3, and similar services can
all be targeted through boto3's S3 client and an optional endpoint URL.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

DEFAULT_ASSET_PREFIX = "assets/review-cache/"
DEFAULT_CACHE_CONTROL = "public,max-age=31536000,immutable"
REPORT_SAMPLE_LIMIT = 100


@dataclass(frozen=True)
class AssetUpload:
    local_path: Path
    relative_path: str
    object_key: str
    size: int
    content_type: str


def normalize_relative_prefix(value: str, *, field: str, trailing_slash: bool) -> str:
    raw = str(value or "").strip().replace("\\", "/").strip("/")
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or ".." in path.parts or any(part in {"", "."} for part in path.parts):
        raise ValueError(f"{field} must be a safe relative path prefix")
    normalized = str(path)
    return f"{normalized}/" if trailing_slash else normalized


def normalize_object_prefix(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return normalize_relative_prefix(raw, field="object_prefix", trailing_slash=False)


def normalize_public_base_url(value: str) -> str:
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("public_base_url must be an absolute http(s) URL")
    if parsed.query or parsed.fragment:
        raise ValueError("public_base_url must not include a query string or fragment")
    return f"{raw.rstrip('/')}/"


def contained_site_path(site_dir: Path, selected: Path, *, field: str) -> Path:
    root = site_dir.resolve()
    candidate = selected if selected.is_absolute() else root / selected
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{field} must remain inside site_dir") from exc
    return candidate


def safe_manifest_path(site_dir: Path, manifest: Path | None) -> Path:
    selected = manifest if manifest is not None else Path("data/rounds.manifest.json")
    return contained_site_path(site_dir, selected, field="manifest path")


def safe_asset_dir(site_dir: Path, asset_dir: Path | None) -> Path:
    selected = asset_dir if asset_dir is not None else Path("assets/review-cache")
    return contained_site_path(site_dir, selected, field="asset_dir")


def load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("format") != "amazon-image-game-sharded-pack":
        raise ValueError("manifest must be an amazon-image-game-sharded-pack")
    if not payload.get("dataset_signature"):
        raise ValueError("manifest is missing dataset_signature")
    return payload


def content_type_for(path: Path) -> str:
    guessed = mimetypes.guess_type(path.name)[0]
    return guessed if guessed and guessed.startswith("image/") else "application/octet-stream"


def build_upload_plan(asset_dir: Path, object_prefix: str) -> list[AssetUpload]:
    if not asset_dir.is_dir():
        raise ValueError(f"asset directory does not exist: {asset_dir}")
    prefix = normalize_object_prefix(object_prefix)
    uploads: list[AssetUpload] = []
    for path in sorted(asset_dir.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(asset_dir).as_posix()
        relative_path = PurePosixPath(relative)
        if ".." in relative_path.parts:
            raise ValueError(f"unsafe asset path: {relative}")
        object_key = str(PurePosixPath(prefix) / relative_path) if prefix else str(relative_path)
        uploads.append(
            AssetUpload(
                local_path=path,
                relative_path=relative,
                object_key=object_key,
                size=path.stat().st_size,
                content_type=content_type_for(path),
            )
        )
    if not uploads:
        raise ValueError(f"asset directory contains no publishable files: {asset_dir}")
    return uploads


def delivery_mapping(*, asset_path_prefix: str, public_base_url: str) -> dict[str, str]:
    return {
        "path_prefix": normalize_relative_prefix(
            asset_path_prefix,
            field="asset_path_prefix",
            trailing_slash=True,
        ),
        "base_url": normalize_public_base_url(public_base_url),
    }


def with_delivery_mapping(
    manifest: dict[str, Any],
    *,
    asset_path_prefix: str,
    public_base_url: str,
) -> dict[str, Any]:
    updated = dict(manifest)
    existing = updated.get("asset_delivery")
    asset_delivery = dict(existing) if isinstance(existing, dict) else {}
    asset_delivery["review_images"] = delivery_mapping(
        asset_path_prefix=asset_path_prefix,
        public_base_url=public_base_url,
    )
    updated["asset_delivery"] = asset_delivery
    return updated


def write_manifest_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def publish_uploads(
    uploads: list[AssetUpload],
    *,
    client: Any,
    bucket: str,
    cache_control: str = DEFAULT_CACHE_CONTROL,
) -> dict[str, Any]:
    if not bucket.strip():
        raise ValueError("bucket is required")
    uploaded_bytes = 0
    for item in uploads:
        extra_args = {
            "ContentType": item.content_type,
            "CacheControl": cache_control,
        }
        client.upload_file(
            str(item.local_path),
            bucket,
            item.object_key,
            ExtraArgs=extra_args,
        )
        uploaded_bytes += item.size
    return {
        "uploaded_files": len(uploads),
        "uploaded_bytes": uploaded_bytes,
    }


def make_s3_client(*, endpoint_url: str | None, region: str | None, profile: str | None) -> Any:
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError(
            "Publishing requires boto3. Install it with: python -m pip install -r requirements-publishing.txt"
        ) from exc

    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    kwargs: dict[str, Any] = {}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    if region:
        kwargs["region_name"] = region
    return session.client("s3", **kwargs)


def report_payload(
    *,
    manifest: dict[str, Any],
    uploads: list[AssetUpload],
    bucket: str,
    object_prefix: str,
    public_base_url: str,
    applied: bool,
    upload_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    total_bytes = sum(item.size for item in uploads)
    sample = uploads[:REPORT_SAMPLE_LIMIT]
    result: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "applied": applied,
        "dataset_signature": str(manifest.get("dataset_signature")),
        "bucket": bucket,
        "object_prefix": normalize_object_prefix(object_prefix),
        "public_base_url": normalize_public_base_url(public_base_url),
        "planned_files": len(uploads),
        "planned_bytes": total_bytes,
        "object_sample": [
            {
                "relative_path": item.relative_path,
                "object_key": item.object_key,
                "size": item.size,
                "content_type": item.content_type,
            }
            for item in sample
        ],
        "object_sample_truncated": len(uploads) > len(sample),
    }
    if upload_result:
        result.update(upload_result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site_dir", type=Path, help="Assembled static site directory")
    parser.add_argument("--bucket", required=True, help="S3-compatible bucket name")
    parser.add_argument(
        "--object-prefix",
        default="review-cache",
        help="Object key prefix corresponding to --public-base-url",
    )
    parser.add_argument(
        "--public-base-url",
        required=True,
        help="Public CDN/object URL base for files under --object-prefix",
    )
    parser.add_argument("--endpoint-url", help="Custom S3-compatible endpoint, e.g. Cloudflare R2 or MinIO")
    parser.add_argument("--region", help="Optional S3 region")
    parser.add_argument("--profile", help="Optional local AWS profile name")
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Manifest path relative to site_dir; defaults to data/rounds.manifest.json",
    )
    parser.add_argument(
        "--asset-dir",
        type=Path,
        help="Review-image directory relative to site_dir; defaults to assets/review-cache",
    )
    parser.add_argument("--asset-path-prefix", default=DEFAULT_ASSET_PREFIX)
    parser.add_argument("--cache-control", default=DEFAULT_CACHE_CONTROL)
    parser.add_argument("--report", type=Path, help="Optional JSON plan/result report")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform uploads and write the manifest mapping. Without this flag the command is a dry run.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    site_dir = args.site_dir.resolve()
    if not site_dir.is_dir():
        raise SystemExit(f"site directory does not exist: {site_dir}")
    if not args.bucket.strip():
        raise SystemExit("bucket is required")

    try:
        manifest_path = safe_manifest_path(site_dir, args.manifest)
        asset_dir = safe_asset_dir(site_dir, args.asset_dir)
        manifest = load_manifest(manifest_path)
        uploads = build_upload_plan(asset_dir, args.object_prefix)
        public_base_url = normalize_public_base_url(args.public_base_url)
        updated_manifest = with_delivery_mapping(
            manifest,
            asset_path_prefix=args.asset_path_prefix,
            public_base_url=public_base_url,
        )

        upload_result = None
        if args.apply:
            client = make_s3_client(
                endpoint_url=args.endpoint_url,
                region=args.region,
                profile=args.profile,
            )
            upload_result = publish_uploads(
                uploads,
                client=client,
                bucket=args.bucket,
                cache_control=args.cache_control,
            )
            write_manifest_atomic(manifest_path, updated_manifest)

        report = report_payload(
            manifest=manifest,
            uploads=uploads,
            bucket=args.bucket,
            object_prefix=args.object_prefix,
            public_base_url=public_base_url,
            applied=args.apply,
            upload_result=upload_result,
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    mode = "published" if args.apply else "planned"
    print(
        f"{mode.capitalize()} {report['planned_files']:,} review-image objects "
        f"({report['planned_bytes'] / 1024 / 1024:.1f} MiB)"
    )
    print(f"Object prefix: {report['object_prefix'] or '(bucket root)'}")
    print(f"Public base: {report['public_base_url']}")
    if not args.apply:
        print("Dry run only. Re-run with --apply to upload and write the manifest mapping.")


if __name__ == "__main__":
    main()
