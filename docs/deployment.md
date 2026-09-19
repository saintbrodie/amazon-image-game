# Build a deployable game artifact

The `Build deployment artifact` GitHub Actions workflow turns a real Amazon Reviews 2023 category selection into a ready-to-host static site. It is intentionally manual for real data so ordinary pushes do not download multi-gigabyte source files.

## Run it

Open **Actions -> Build deployment artifact -> Run workflow** and choose:

- `categories`: space-separated Amazon Reviews 2023 category keys, for example `Pet_Supplies Automotive`
- `limit`: maximum playable rounds to keep
- `shard_size`: rounds per browser shard
- `inspect_images`: inspect cached images for metadata/privacy signals
- `detect_faces`: use the conservative OpenCV face detector as a human-review flag
- `detect_qr`: flag images containing QR codes
- `use_safety_model`: optionally run the heavyweight local transformer image classifier
- `safety_model`: Hugging Face image-classification model ID; defaults to `Falconsai/nsfw_image_detection`
- `safety_model_revision`: optional model revision/commit for reproducible builds
- `safety_positive_labels`: space-separated classifier labels treated as review-worthy; defaults to `nsfw`
- `safety_review_threshold`: score that creates a medium human-review flag; defaults to `0.60`
- `safety_high_threshold`: score that creates a high-severity flag; defaults to `0.95`
- `safety_device`: Transformers device selection such as `auto`, `cpu`, or `0`
- `exclude_high`: remove rounds with high-confidence privacy/problem flags, including model hits above the high threshold when model screening is enabled
- `curation_json`: optional compact curator decisions JSON
- `only_kept`: when curation JSON is supplied, remove unreviewed rounds too and deploy only explicit keeps

A small first run such as `All_Beauty`, 100 to 250 rounds, and shard size 50 to 75 is useful for checking the complete pipeline before starting a much larger category.

The transformer model is **off by default**. When disabled, the workflow installs only the normal Pillow/OpenCV screening dependencies. When enabled for a manual run, it additionally installs `requirements-screening-model.txt` and downloads the requested model. Pull-request packaging tests force the model off so routine validation does not spend Actions minutes on heavyweight model installation.

## Curated deployment

The intended operator loop is:

1. Build or serve the screened pack you want to review.
2. Open `curate.html`.
3. Review manually and/or use the conservative bulk actions.
4. Click **Copy Actions JSON** for a compact one-line decisions payload, or **Export workspace** to keep decisions plus curator notes/tags/presets.
5. Run **Build deployment artifact** again with the same category/limit and screening settings.
6. Paste the copied payload into `curation_json`.
7. Leave `only_kept` off to drop explicit rejects while retaining unreviewed rounds, or enable it for a strict hand-picked site.

The workflow compares the decisions file's `dataset_signature` with the screened pack before applying it. A mismatch fails the build rather than silently applying decisions to a different set of rounds.

Bulk actions in the curator only touch undecided rounds. The built-in high-risk reject and clear/low-priority keep actions preserve prior manual decisions and support one-step undo.

## Model-screened deployment

For the documented default classifier, a practical starting configuration is:

```text
use_safety_model: true
safety_model: Falconsai/nsfw_image_detection
safety_positive_labels: nsfw
safety_review_threshold: 0.60
safety_high_threshold: 0.95
safety_device: auto
```

Model hits between the review and high thresholds remain in the pack with a medium review flag. Scores at or above the high threshold become high-severity flags and can therefore be removed by `exclude_high`.

If you want **all model hits to remain human-review-only**, set:

```text
safety_high_threshold: 1.0
```

For reproducible production builds, pin `safety_model_revision` to a known Hugging Face commit/revision rather than relying indefinitely on a moving model default.

The model score, label scores, thresholds, and model ID are included in each classified round's `screening.image.safety_model` metadata and summarized in the screening report. See [`screening.md`](screening.md) for the model adapter behavior and limitations.

## Pipeline

The workflow runs the same tools available locally:

1. stream/build the selected real-data pack
2. validate it
3. score and audit the rounds
4. cache review images locally
5. exact/perceptual-dedupe the cached images
6. screen text and images for privacy/review signals
7. optionally run the transformer image-safety classifier
8. optionally remove high-severity cases
9. audit the screened pack again
10. optionally validate and apply exported curator decisions
11. audit the curated pack when decisions were applied
12. split the final pack into deterministic static shards
13. validate every shard and hash
14. assemble the game and curator browser files, manifest, shards, and cached images
15. serve the generated directory over HTTP and smoke-test the game data and curator page
16. upload the site and reports as separate GitHub Actions artifacts

Pull requests exercise this same packaging path against the bundled demo instead of the remote Amazon dataset. The PR fixture also creates a valid curation decisions file, rejects one fixture round, verifies that the final sharded site contains five rounds instead of six, and verifies that heavyweight model screening stayed disabled.

## Artifacts

A successful manual run produces two downloadable artifacts:

### `amazon-image-game-site-<run id>`

This is the deployable directory. It contains:

```text
index.html
styles.css
controls.css
daily.css
game-core.js
dataset-loader.js
app.js
curate.html
curate.js
curate-actions.js
curate-screening.js
curate.css
curate-quality.css
curate-screening.css
build-info.json
CONTENT_RIGHTS_NOTICE.txt
assets/review-cache/...
data/rounds.manifest.json
data/shards/rounds-....json
```

`build-info.json` records the deployed round count, final dataset signature, screening report summary, and curation summary. When the optional model is enabled, its configuration is present inside the screening summary.

Serve that directory from any ordinary static HTTP host. No application server or database is required.

### `amazon-image-game-reports-<run id>`

This contains the intermediate full packs plus before/after audits, screening report, curation report, final curated pack, and the decisions file when curation was applied. Keep it for curation/debugging rather than serving it publicly by default.

## Local equivalent

The same curation step can be applied offline:

```bash
python scripts/apply_curation.py \
  --dataset data/rounds.screened.json \
  --decisions curation-<signature>.json \
  --output data/rounds.curated.json
```

Add `--only-kept` for a strict hand-picked pack. Signature mismatches fail by default.

## Content rights

The deployment artifact can contain customer-posted third-party media. The workflow packages the data technically; it does not grant republication rights. Confirm the dataset/content terms appropriate to your use before publishing a real-data artifact.
