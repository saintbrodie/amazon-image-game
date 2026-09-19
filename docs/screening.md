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
- optional local transformer image-classification safety scores

Face and QR detection are intentionally **review signals**, not automatic rejection rules. Haar face detection can miss faces and can produce false positives. QR detection says a code exists, not that its contents are harmful.

The optional transformer path is also a curation signal rather than a safety oracle. Model scores can be wrong, poorly calibrated, or sensitive to image composition and training data.

## Recommended base pipeline

First build, score, and cache the pack:

```bash
python scripts/build_pack.py --categories All_Beauty --limit 500 --output data/rounds.json
python scripts/score_dataset.py data/rounds.json --output data/rounds.scored.json
python -m pip install -r requirements-images.txt
python scripts/cache_images.py data/rounds.scored.json \
  --output data/rounds.cached.json \
  --perceptual-threshold 4
```

Then install the normal screening dependencies and inspect the local images:

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

## Optional transformer safety model

The stronger model path is deliberately opt-in so normal CI and deployment builds do not download PyTorch or model weights.

Install the heavyweight optional dependencies:

```bash
python -m pip install -r requirements-screening-model.txt
```

For GPU environments, it can be preferable to install the PyTorch build appropriate for the host/CUDA version first, then install the remaining requirements.

Enable the documented default classifier by passing `--safety-model` without a value:

```bash
python scripts/screen_dataset.py data/rounds.cached.json \
  --output data/rounds.screened.json \
  --report data/screening-report.json \
  --inspect-images \
  --detect-faces \
  --detect-qr \
  --safety-model
```

The default adapter targets [`Falconsai/nsfw_image_detection`](https://huggingface.co/Falconsai/nsfw_image_detection), an Apache-2.0 ViT image classifier whose published labels are `normal` and `nsfw`.

Default score handling is intentionally conservative:

- positive score below `0.60`: record the model scores, but add no flag
- positive score `>= 0.60`: add a **medium** `model_nsfw_content` review flag
- positive score `>= 0.95`: add a **high** `model_nsfw_content` flag

Every evaluated local image records the model ID, positive labels, thresholds, positive score, and all returned label scores under:

```text
screening.image.safety_model
```

The dataset-level `screening_summary.safety_model` records the model configuration used for the pass.

### Pinning a model revision

For a reproducible production pipeline, pin a model revision or commit:

```bash
python scripts/screen_dataset.py data/rounds.cached.json \
  --output data/rounds.screened.json \
  --inspect-images \
  --safety-model Falconsai/nsfw_image_detection \
  --safety-model-revision <hugging-face-revision>
```

The adapter does not enable `trust_remote_code`; custom models must work with the standard Transformers image-classification pipeline.

### Devices

Let Transformers select its default behavior:

```text
--safety-device auto
```

Force CPU:

```text
--safety-device cpu
```

Use a numbered accelerator device where supported:

```text
--safety-device 0
```

Backend device strings such as `mps` can also be passed through when supported by the installed Transformers/PyTorch versions.

### Custom image classifiers

A different Hugging Face image-classification model can be used as long as its positive labels are declared. Repeat `--safety-positive-label` for multiple labels:

```bash
python scripts/screen_dataset.py data/rounds.cached.json \
  --output data/rounds.screened.json \
  --inspect-images \
  --safety-model owner/model \
  --safety-positive-label unsafe \
  --safety-positive-label explicit \
  --safety-review-threshold 0.60 \
  --safety-high-threshold 0.95
```

Label matching is case-insensitive and normalizes spaces, underscores, and hyphens. Do not assume a custom model's score semantics match the default model; inspect its label set and model card first.

## High-confidence exclusion

`--exclude-high` removes only rounds with a high-severity flag. High-severity flags include narrow privacy problems such as contact information, coordinates, GPS EXIF, or a missing requested local image. When the optional transformer model is enabled, a model score at or above `--safety-high-threshold` can also become high severity.

```bash
python scripts/screen_dataset.py data/rounds.cached.json \
  --output data/rounds.screened.json \
  --inspect-images \
  --detect-faces \
  --detect-qr \
  --safety-model \
  --exclude-high
```

If you want model results to be **human-review-only**, set the high threshold to `1.0` and leave the review threshold at the desired queue cutoff:

```text
--safety-review-threshold 0.60 --safety-high-threshold 1.0
```

Medium-severity signals such as a detected face, QR code, external URL, social handle, identifying EXIF field, or medium-confidence model hit remain in the pack for human curation. A medium flag means "look at this round," not "this round is unsafe."

## Failure behavior

When model screening is requested, failures are not silently ignored. Missing dependencies, model-load failures, unexpected model output, or classification errors fail the screening command so an operator does not accidentally publish a pack believing it received model review.

Remote review-image URLs are not fetched by the safety model. Cache the review media first so screening operates on the exact local files that will be curated or published.

## Important limitations

No single classifier covers every visual safety category or deployment policy. The default adapter primarily contributes an adult-content signal because that is what the default model classifies. It does not replace dedicated violence/gore, hate-symbol, self-harm, age, or other policy-specific detectors.

The intended architecture is additive: privacy checks, face/QR detection, one or more optional model signals, and human curation all feed the same screening schema. That keeps the curator explainable and allows stronger specialist classifiers to be added later without replacing the rest of the pipeline.
