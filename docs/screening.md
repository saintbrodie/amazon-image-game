# Review-media screening

`scripts/screen_dataset.py` is a conservative curation aid for generated packs. It does not claim to decide whether an image is universally safe. Instead, it raises review flags that are useful before publishing customer-supplied media.

## What it checks

Text checks use the Python standard library and flag likely:

- email addresses
- phone numbers
- external URLs
- social handles
- latitude/longitude coordinates

Optional local-image inspection adds:

- GPS EXIF metadata
- identifying EXIF fields such as camera owner/serial, artist, user comment, and copyright
- very small or extreme-aspect-ratio images
- likely human faces using OpenCV's bundled frontal-face cascade
- QR codes using OpenCV's QR detector

Face and QR detection are intentionally **review signals**, not automatic rejection rules. Haar face detection can miss faces and can produce false positives. QR detection says a code exists, not that its contents are harmful.

## Recommended pipeline

First build, score, and cache the pack:

```bash
python scripts/build_pack.py --categories All_Beauty --limit 500 --output data/rounds.json
python scripts/score_dataset.py data/rounds.json --output data/rounds.scored.json
python -m pip install -r requirements-images.txt
python scripts/cache_images.py data/rounds.scored.json \
  --output data/rounds.cached.json \
  --perceptual-threshold 4
```

Then install the optional screening dependencies and inspect the local images:

```bash
python -m pip install -r requirements-screening.txt
python scripts/screen_dataset.py data/rounds.cached.json \
  --output data/rounds.screened.json \
  --report data/screening-report.json \
  --inspect-images \
  --detect-faces \
  --detect-qr
```

Each round receives a `screening` object with:

- `risk_score`
- `needs_review`
- `high_risk`
- `flags`
- per-severity counts
- optional image inspection metadata

The dataset receives a `screening_summary` with aggregate counts.

## High-confidence exclusion

`--exclude-high` removes only rounds with a high-severity flag. Current high-severity flags are deliberately narrow, such as contact information, coordinates, GPS EXIF, or a missing local image during requested image inspection.

```bash
python scripts/screen_dataset.py data/rounds.cached.json \
  --output data/rounds.screened.json \
  --inspect-images \
  --detect-faces \
  --detect-qr \
  --exclude-high
```

Medium-severity signals such as a detected face, QR code, external URL, social handle, or identifying EXIF field remain in the pack for human curation.

## Important limitation

This helper does **not** detect every unsafe visual category and should not be treated as a substitute for human review or a dedicated image-safety model. Its purpose is to remove easy privacy mistakes and prioritize the rounds a curator should inspect first.
