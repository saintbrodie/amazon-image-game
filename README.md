# What Did They Buy?

A browser game where you see a mysterious customer review photo and guess which product the reviewer bought.

The repository includes an original bundled demo plus streaming tools for the [McAuley Lab Amazon Reviews 2023 dataset](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023). The game does not scrape live Amazon product pages.

## Features

- Photo-only and photo-plus-review clue modes
- Four-choice rounds with keyboard shortcuts
- Score and streak bonuses
- Category filtering and selectable game length
- Deterministic five-round daily challenge with shareable results
- Broken-image skip handling
- Browser-based keep/reject curator
- Lazy sharded curation for large packs
- Screening-aware curator filters, signal queues, sorting, and risk badges
- Reversible conservative bulk curation actions
- Per-round private curator notes and tags with tag-based queues
- Saved curator queue presets
- Portable curator workspace export/import separated from compact deployment decisions
- Heuristic difficulty and curation-priority scoring
- Conservative privacy/review-media screening helpers
- Dataset audit reports
- Optional local review-image caching
- Exact and optional perceptual image deduplication
- Safe dry-run-first image-cache pruning and reclaimable-space reporting
- S3-compatible publishing for large cached review-image pools
- Manifest-level CDN/object-storage delivery mapping without shard rewrites
- Streaming Amazon Reviews 2023 ingestion with bounded memory
- Pack-level distractor reranking for more plausible wrong answers
- Deterministic static sharding with lazy browser loading
- Manual GitHub Actions workflow that produces a ready-to-host static-site artifact
- Optional curator-decision application during deployment builds
- Chromium end-to-end tests for the sharded game and curator paths
- Mobile-friendly, framework-free UI

## Run the game

```bash
python -m http.server 8000
```

Open `http://localhost:8000`.

The browser prefers `data/rounds.manifest.json` when a sharded pack exists, otherwise it tries `data/rounds.json` and falls back to the bundled `data/demo.json`.

## Daily challenge

Daily mode deterministically selects the same five round IDs and answer order for a given UTC date and dataset.

```text
?daily=2026-09-18
```

`?daily=1` and `?daily=today` resolve to the current UTC date. Completed results are stored locally per dataset signature/date and can be shared as result squares.

## Build a real Amazon Reviews 2023 pack

The builder streams the current raw `.jsonl` files directly from the official McAuley Lab Hugging Face dataset repository. It does not retain the multi-gigabyte source files on disk.

```bash
python scripts/build_pack.py \
  --categories Pet_Supplies Patio_Lawn_and_Garden Tools_and_Home_Improvement Automotive Home_and_Kitchen \
  --limit 2000 \
  --output data/rounds.json
```

PowerShell:

```powershell
python scripts/build_pack.py `
  --categories Pet_Supplies Patio_Lawn_and_Garden Tools_and_Home_Improvement Automotive Home_and_Kitchen `
  --limit 2000 `
  --output data/rounds.json
```

The current source layout is:

```text
https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/main/raw/review_categories/<CATEGORY>.jsonl
https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/main/raw/meta_categories/meta_<CATEGORY>.jsonl
```

The files vary dramatically in size. `All_Beauty` is useful for a quick real-data smoke test. Categories such as Pet Supplies, Automotive, and Home & Kitchen are multi-gigabyte streams.

Useful options:

```bash
# Keep successful categories if another source fails
python scripts/build_pack.py --limit 2000 --continue-on-error

# Skip live review-image checks while iterating on data logic
python scripts/build_pack.py --limit 500 --no-check-images

# Development-only scan caps
python scripts/build_pack.py \
  --categories All_Beauty \
  --limit 50 \
  --max-review-records 100000 \
  --max-metadata-records 100000
```

Metadata scan caps can prevent sampled `parent_asin` values from being found, so do not use them for a final pack unless you understand that tradeoff.

### Distractor selection

The streaming joiner first builds plausible choices from a bounded metadata reservoir. During final pack assembly, `scripts/pack_choices.py` pools those candidate titles by source category and reranks them against each correct product title. Very similar titles are rejected to reduce ambiguous model/variant questions.

This second pass is intentionally cheap. It improves choice quality without downloading metadata twice or loading an entire Amazon category into memory.

## Use already-downloaded raw files

Both `.jsonl` and `.jsonl.gz` local sources are supported:

```text
data/raw/
  All_Beauty.jsonl
  meta_All_Beauty.jsonl
  Pet_Supplies.jsonl.gz
  meta_Pet_Supplies.jsonl.gz
```

```bash
python scripts/build_pack.py \
  --categories All_Beauty Pet_Supplies \
  --raw-dir data/raw \
  --limit 1000
```

## Build one category directly

`scripts/build_dataset.py` accepts local paths or HTTP(S) URLs:

```bash
python scripts/build_dataset.py \
  --reviews https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/main/raw/review_categories/All_Beauty.jsonl \
  --metadata https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/main/raw/meta_categories/meta_All_Beauty.jsonl \
  --source-category All_Beauty \
  --output data/rounds.json \
  --limit 100
```

## Validate, score, and audit

Validate structural correctness:

```bash
python scripts/validate_dataset.py data/rounds.json
```

Annotate rounds with heuristic difficulty and curation-priority information:

```bash
python scripts/score_dataset.py data/rounds.json --output data/rounds.scored.json
```

Print a dataset-wide audit:

```bash
python scripts/audit_dataset.py data/rounds.scored.json
```

Machine-readable audit:

```bash
python scripts/audit_dataset.py data/rounds.scored.json --json --output data/audit.json
```

The audit includes category counts, ratings, difficulty buckets, quality flags, review-image hosts, verified-purchase counts, and helpful-vote counts. Scores are triage aids, not ground truth.

## Screen review media

`scripts/screen_dataset.py` adds conservative curation signals for likely contact information, coordinates, privacy-sensitive EXIF metadata, and optional face/QR detection.

For cached local images:

```bash
python -m pip install -r requirements-screening.txt
python scripts/screen_dataset.py data/rounds.cached.json \
  --output data/rounds.screened.json \
  --report data/screening-report.json \
  --image-root . \
  --inspect-images \
  --detect-faces \
  --detect-qr
```

`--exclude-high` removes only high-severity cases. Medium signals such as a likely face or QR code remain available for human review. See [`docs/screening.md`](docs/screening.md) for the intended workflow and limitations.

## Curate a generated pack

Serve the repo and open:

```text
http://localhost:8000/curate.html
```

The curator supports:

- `K` to keep
- `R` to reject
- left/right arrows to navigate
- category and decision filters
- screening filters for flagged, high-risk, clear, or unscreened rounds
- signal queues such as faces, QR codes, social handles, or other emitted screening flags
- per-round private tags and operator notes
- tag-based review queues
- saved queue presets for category/status/screening/signal/tag/sort/auto-keep threshold
- sorting by curation priority, screening risk, or difficulty
- visible screening severity badges and risk score
- lazy loading from sharded packs without downloading every round
- bulk reject for undecided high-risk rounds
- conservative bulk keep for screened-clear rounds below a configurable curation-priority ceiling
- one-step undo for the most recent bulk action
- existing manual decisions are never overwritten by a bulk action
- review/product/choice inspection
- version 2 workspace JSON export/import with decisions, notes, tags, and presets
- **Copy Actions JSON** for a compact deployment payload containing only dataset signature and keep/reject IDs

Operator notes, tags, and presets stay in the curator workspace and are not copied into public game shards or the compact deployment payload. See [`docs/curator-workspace.md`](docs/curator-workspace.md) for the workspace model and portability details.

Apply exported deployment decisions offline:

```bash
python scripts/apply_curation.py \
  --dataset data/rounds.screened.json \
  --decisions curation-<signature>.json \
  --output data/rounds.curated.json
```

By default only explicit rejects are removed. Add `--only-kept` for a strict hand-picked pack. Dataset-signature mismatches fail unless intentionally overridden. Signature calculation matches the browser's UTF-16 FNV behavior, including Unicode round IDs.

## Cache review images locally

For deployments where you have the appropriate rights to host the media:

```bash
python scripts/cache_images.py data/rounds.curated.json \
  --output data/rounds.cached.json \
  --asset-dir assets/review-cache \
  --public-prefix assets/review-cache
```

This downloads images to SHA-256 content-addressed filenames and removes failed or exact-duplicate images by default.

For perceptual near-duplicate detection:

```bash
python -m pip install -r requirements-images.txt
python scripts/cache_images.py data/rounds.curated.json \
  --output data/rounds.cached.json \
  --perceptual-threshold 4
```

The perceptual mode uses a 64-bit dHash and Hamming distance. `4` is a conservative starting point.

### Prune an accumulated image cache

Repeated builds can leave unreferenced content-addressed files behind. Preview reclaimable space first:

```bash
python scripts/prune_image_cache.py \
  --cache-dir assets/review-cache \
  data/rounds.cached.json
```

The pruner is dry-run by default and can union references from multiple full packs or sharded manifests. Add `--delete` only after reviewing the orphan report. See [`docs/cache-maintenance.md`](docs/cache-maintenance.md).

## Publish review images to object storage

Large rotating pools can keep the app/shard site small by moving only cached review images to S3-compatible object storage.

Dry-run the upload plan first:

```bash
python scripts/publish_assets.py site \
  --bucket my-game-assets \
  --object-prefix review-cache \
  --public-base-url https://images.example.com/reviews/ \
  --report reports/publish-plan.json
```

Install the optional publishing dependency and add `--apply` when the plan is correct:

```bash
python -m pip install -r requirements-publishing.txt
python scripts/publish_assets.py site \
  --bucket my-game-assets \
  --object-prefix review-cache \
  --public-base-url https://images.example.com/reviews/ \
  --apply
```

The publisher uploads content-addressed images with immutable cache headers and then adds an `asset_delivery.review_images` mapping to `data/rounds.manifest.json`. Shard JSON is not rewritten. Changing buckets or CDN domains later only requires changing the manifest mapping. AWS S3 and S3-compatible providers such as Cloudflare R2, MinIO, Wasabi, and Backblaze B2 S3 are supported through boto3 endpoint configuration. See [`docs/object-storage.md`](docs/object-storage.md).

## Static sharding

Large packs can be split into deterministic static shards:

```bash
python scripts/shard_dataset.py data/rounds.screened.json \
  --manifest data/rounds.manifest.json \
  --shard-size 75 \
  --shard-prefix shards/rounds

python scripts/validate_shards.py data/rounds.manifest.json
```

The browser and curator read the lightweight manifest first and fetch only the shards they need. Compact manifest entries include curation/difficulty scores and screening signal names/severity, while full review text, images, choices, product metadata, and detailed screening metadata stay in shard files. See [`docs/sharding.md`](docs/sharding.md).

## Build a deployable artifact in GitHub Actions

The **Build deployment artifact** workflow can turn selected real Amazon Reviews 2023 categories into a ready-to-host static-site ZIP.

It runs build, scoring, auditing, image caching, perceptual deduplication, screening, optional curator-decision application, sharding, shard validation, and an HTTP smoke test before uploading the site and a separate reports artifact.

For a curated deployment:

1. Review the same screened pack in `curate.html`.
2. Click **Copy Actions JSON**.
3. Open **Actions -> Build deployment artifact -> Run workflow**.
4. Paste the compact JSON into `curation_json`.
5. Leave `only_kept` off to remove explicit rejects while retaining unreviewed rounds, or enable it for a strict hand-picked deployment.

The workflow validates the exported dataset signature before applying decisions. A mismatch fails the build instead of silently applying decisions to another generated pack.

See [`docs/deployment.md`](docs/deployment.md) for the workflow inputs and artifact layout.

## Real-data GitHub Actions test

`.github/workflows/real-data-integration.yml` runs the complete networked data path against an actual Amazon Reviews 2023 category:

1. Verify current Hugging Face source files.
2. Stream reviews and metadata.
3. Build a real review-photo pack.
4. Validate and score it.
5. Generate an audit.
6. Download/cache the selected review images.
7. Run perceptual deduplication.
8. Validate the cached pack.
9. Upload the generated packs, reports, and cached images as an Actions artifact.

The workflow defaults to `All_Beauty` and 100 rounds because it is much smaller than the multi-gigabyte default game categories. Use **Run workflow** in GitHub Actions to choose another category or round count.

## Round generation

At a high level:

1. Stream review records and reservoir-sample image-bearing reviews.
2. Join reviews to product metadata with `parent_asin`.
3. Keep a bounded metadata reservoir for distractors.
4. Normalize known image representations, categories, and prices.
5. Generate initial taxonomy/title-based distractors.
6. Reject near-duplicate listing titles.
7. Emit at most one round per parent product.
8. Optionally verify selected review-image URLs.
9. Balance categories and deduplicate products.
10. Rerank the accumulated candidate-title bank for stronger final choices.
11. Optionally score, audit, cache, screen, curate, and shard the pack.

## Tests

```bash
node --check game-core.js
node --check dataset-loader.js
node --check app.js
node --check curate-screening.js
node --check curate-actions.js
node --check curate.js
node tests/test_game_core.js
node tests/test_dataset_loader.js
node tests/test_curate_screening.js
node tests/test_curate_actions.js
node tests/test_curate_state.js
python -m compileall -q scripts tests
python scripts/validate_dataset.py data/demo.json
python -m unittest discover -s tests -p 'test_*.py' -v
```

Normal CI stays lightweight and network-free. Separate workflows cover the Chromium and expensive real-data integration paths.

## GitHub Pages

The game has no build step and can be served as static files. The bundled demo works immediately. Generated real-data packs and cached review images are ignored by Git by default because they can be large and because publishing third-party review media should be an intentional decision.

## Content and rights note

This project is not affiliated with or endorsed by Amazon. The bundled demo artwork is original to this repository. Amazon Reviews 2023 contains third-party review text and customer-posted image URLs. Dataset availability should not be treated as an automatic grant to republish or permanently cache every customer image. Review the dataset terms and applicable rights before public deployment.

## Next technical milestones

- Stronger optional image-safety model integration while keeping human review in the loop
- Shared/multi-curator workspace support if curation moves beyond a single operator/browser
