#!/usr/bin/env python3
"""Flag generated game rounds that deserve privacy or safety review.

This is a curation aid, not a content-safety oracle. The standard-library text
checks target high-confidence contact/identity leakage. Optional local-image
checks use Pillow for EXIF metadata and OpenCV for face / QR detection.

By default the script annotates rounds without removing them. --exclude-high
removes only rounds carrying at least one high-severity flag.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

EMAIL_RE = re.compile(r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w.-])", re.I)
PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[ .-]?)?(?:\(\d{3}\)|\d{3})[ .-]\d{3}[ .-]\d{4}(?!\d)"
)
URL_RE = re.compile(r"\b(?:https?://|www\.)[^\s<>()]+", re.I)
SOCIAL_RE = re.compile(r"(?<![\w@])@[A-Za-z0-9_][A-Za-z0-9_.-]{2,30}(?![\w@])")
COORD_RE = re.compile(
    r"(?<!\d)([-+]?(?:[0-8]?\d(?:\.\d+)?|90(?:\.0+)?))\s*,\s*"
    r"([-+]?(?:1[0-7]\d(?:\.\d+)?|180(?:\.0+)?|(?:\d?\d)(?:\.\d+)?))(?!\d)"
)

SEVERITY_WEIGHT = {"low": 5, "medium": 20, "high": 50}
IDENTIFYING_EXIF_TAGS = {
    315: "exif_artist",
    33432: "exif_copyright",
    37510: "exif_user_comment",
    42032: "exif_camera_owner",
    42033: "exif_camera_serial",
}


def _text_blob(round_data: dict[str, Any]) -> str:
    parts = []
    for key in ("review_title", "review_text"):
        value = round_data.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)
    return "\n".join(parts)


def text_flags(round_data: dict[str, Any]) -> list[dict[str, str]]:
    text = _text_blob(round_data)
    if not text:
        return []
    flags: list[dict[str, str]] = []
    checks = [
        (EMAIL_RE, "contact_email", "high"),
        (PHONE_RE, "contact_phone", "high"),
        (URL_RE, "external_url", "medium"),
        (SOCIAL_RE, "social_handle", "medium"),
        (COORD_RE, "possible_coordinates", "high"),
    ]
    for pattern, name, severity in checks:
        if pattern.search(text):
            flags.append({"name": name, "severity": severity, "source": "review_text"})
    return flags


def _safe_local_path(value: str, image_root: Path) -> Path | None:
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        return None
    root = image_root.resolve()
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"image path escapes image root: {value}") from exc
    return candidate


def pillow_image_flags(path: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    try:
        from PIL import ExifTags, Image
    except ImportError as exc:
        raise RuntimeError("Image metadata screening requires Pillow") from exc

    flags: list[dict[str, str]] = []
    details: dict[str, Any] = {}
    with Image.open(path) as image:
        details["width"] = int(image.width)
        details["height"] = int(image.height)
        details["format"] = image.format
        exif = image.getexif()
        if exif:
            gps_tag = next((tag for tag, name in ExifTags.TAGS.items() if name == "GPSInfo"), 34853)
            if exif.get(gps_tag):
                flags.append({"name": "exif_gps_location", "severity": "high", "source": "image_metadata"})
            for tag, flag_name in IDENTIFYING_EXIF_TAGS.items():
                value = exif.get(tag)
                if value not in (None, "", b""):
                    flags.append({"name": flag_name, "severity": "medium", "source": "image_metadata"})

        if image.width < 160 or image.height < 160:
            flags.append({"name": "very_small_image", "severity": "low", "source": "image"})
        ratio = max(image.width / max(1, image.height), image.height / max(1, image.width))
        if ratio >= 5:
            flags.append({"name": "extreme_aspect_ratio", "severity": "low", "source": "image"})
    return flags, details


def opencv_image_flags(path: Path, *, detect_faces: bool, detect_qr: bool) -> tuple[list[dict[str, str]], dict[str, Any]]:
    if not detect_faces and not detect_qr:
        return [], {}
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("Face / QR screening requires opencv-python-headless") from exc

    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"OpenCV could not decode {path}")

    flags: list[dict[str, str]] = []
    details: dict[str, Any] = {}
    if detect_faces:
        cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        detector = cv2.CascadeClassifier(str(cascade_path))
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        count = len(faces)
        details["face_count"] = count
        if count:
            flags.append({"name": "person_face_detected", "severity": "medium", "source": "image"})

    if detect_qr:
        detector = cv2.QRCodeDetector()
        value, points, _ = detector.detectAndDecode(image)
        found = bool(value or points is not None)
        details["qr_detected"] = found
        if found:
            flags.append({"name": "qr_code_detected", "severity": "medium", "source": "image"})
    return flags, details


def analyze_round(
    round_data: dict[str, Any],
    *,
    image_root: Path | None = None,
    inspect_images: bool = False,
    detect_faces: bool = False,
    detect_qr: bool = False,
) -> dict[str, Any]:
    flags = text_flags(round_data)
    image_details: dict[str, Any] = {}

    if inspect_images:
        image_value = round_data.get("review_image")
        if isinstance(image_value, str):
            local_path = _safe_local_path(image_value, image_root or Path("."))
            if local_path is None:
                flags.append({"name": "image_not_local", "severity": "low", "source": "image"})
            elif not local_path.is_file():
                flags.append({"name": "image_missing", "severity": "high", "source": "image"})
            else:
                pillow_flags, pillow_details = pillow_image_flags(local_path)
                flags.extend(pillow_flags)
                image_details.update(pillow_details)
                cv_flags, cv_details = opencv_image_flags(
                    local_path,
                    detect_faces=detect_faces,
                    detect_qr=detect_qr,
                )
                flags.extend(cv_flags)
                image_details.update(cv_details)

    # Deduplicate by stable flag identity while preserving first occurrence.
    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for flag in flags:
        key = (flag["name"], flag["severity"], flag["source"])
        if key not in seen:
            seen.add(key)
            unique.append(flag)

    severity_counts = Counter(flag["severity"] for flag in unique)
    score = min(100, sum(SEVERITY_WEIGHT.get(flag["severity"], 0) for flag in unique))
    high_risk = severity_counts.get("high", 0) > 0
    return {
        "risk_score": score,
        "needs_review": bool(unique),
        "high_risk": high_risk,
        "flags": unique,
        "severity_counts": dict(sorted(severity_counts.items())),
        "image": image_details,
    }


def screen_dataset(
    payload: dict[str, Any],
    *,
    image_root: Path | None = None,
    inspect_images: bool = False,
    detect_faces: bool = False,
    detect_qr: bool = False,
    exclude_high: bool = False,
) -> dict[str, Any]:
    rounds = payload.get("rounds")
    if not isinstance(rounds, list):
        raise ValueError("dataset must contain a rounds array")

    output_rounds: list[dict[str, Any]] = []
    flag_counts: Counter[str] = Counter()
    severity_counts: Counter[str] = Counter()
    needs_review = 0
    high_risk = 0
    excluded = 0

    for round_data in rounds:
        if not isinstance(round_data, dict):
            continue
        screening = analyze_round(
            round_data,
            image_root=image_root,
            inspect_images=inspect_images,
            detect_faces=detect_faces,
            detect_qr=detect_qr,
        )
        if screening["needs_review"]:
            needs_review += 1
        if screening["high_risk"]:
            high_risk += 1
        for flag in screening["flags"]:
            flag_counts[flag["name"]] += 1
            severity_counts[flag["severity"]] += 1
        if exclude_high and screening["high_risk"]:
            excluded += 1
            continue
        updated = copy.deepcopy(round_data)
        updated["screening"] = screening
        output_rounds.append(updated)

    output = copy.deepcopy(payload)
    output["rounds"] = output_rounds
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rounds_before": len(rounds),
        "rounds_after": len(output_rounds),
        "needs_review_rounds": needs_review,
        "high_risk_rounds": high_risk,
        "excluded_high_risk_rounds": excluded,
        "flag_counts": dict(flag_counts.most_common()),
        "severity_counts": dict(sorted(severity_counts.items())),
        "inspect_images": inspect_images,
        "detect_faces": detect_faces,
        "detect_qr": detect_qr,
    }
    output["screening_summary"] = summary
    stats = output.get("stats")
    if not isinstance(stats, dict):
        stats = {}
        output["stats"] = stats
    stats["rounds_written"] = len(output_rounds)
    stats["screening"] = copy.deepcopy(summary)
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/rounds.screened.json"))
    parser.add_argument("--report", type=Path, help="Optional JSON summary output")
    parser.add_argument("--image-root", type=Path, default=Path("."))
    parser.add_argument("--inspect-images", action="store_true", help="Inspect local review images with Pillow")
    parser.add_argument("--detect-faces", action="store_true", help="Flag likely faces with OpenCV Haar detection")
    parser.add_argument("--detect-qr", action="store_true", help="Flag QR codes with OpenCV")
    parser.add_argument(
        "--exclude-high",
        action="store_true",
        help="Remove only rounds carrying a high-severity screening flag",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if (args.detect_faces or args.detect_qr) and not args.inspect_images:
        raise SystemExit("--detect-faces/--detect-qr require --inspect-images")
    payload = json.loads(args.dataset.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("dataset root must be a JSON object")
    try:
        result = screen_dataset(
            payload,
            image_root=args.image_root,
            inspect_images=args.inspect_images,
            detect_faces=args.detect_faces,
            detect_qr=args.detect_qr,
            exclude_high=args.exclude_high,
        )
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    summary = result["screening_summary"]
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        f"Screened {summary['rounds_before']:,} rounds: "
        f"{summary['needs_review_rounds']:,} need review, "
        f"{summary['high_risk_rounds']:,} high-risk, "
        f"{summary['excluded_high_risk_rounds']:,} excluded"
    )
    if summary["flag_counts"]:
        print(json.dumps(summary["flag_counts"], indent=2))


if __name__ == "__main__":
    main()
