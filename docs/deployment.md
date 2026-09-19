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
- `exclude_high`: remove rounds with high-confidence privacy/problem flags
- `curation_json`: optional compact curator decisions JSON
- `only_kept`: when curation JSON is supplied, remove unreviewed rounds too and deploy only explicit keeps

A small first run such as `All_Beauty`, 100 to 250 rounds, and shard size 50 to 75 is useful for checking the complete pipeline before starting a much larger category.

## Curated deployment

The intended operator loop is:

1. Build or serve the screened pack you want to review.
2. Open `curate.html`.
3. Review manually and/or use the conservative bulk actions.
4. Click **Copy Actions JSON** for a compact one-line decisions payload, or **Export decisions** to keep a file copy.
5. Run **Build deployment artifact** again with the same category/limit settings.
6. Paste the copied payload into `curation_json`.
7. Leave `only_kept` off to drop explicit rejects while retaining unreviewed rounds, or enable it for a strict hand-picked site.

The workflow compares the decisions file's `dataset_signature` with the screened pack before applying it. A mismatch fails the build rather than silently applying decisions to a different set of rounds.

Bulk actions in the curator only touch undecided rounds. The built-in high-risk reject and clear/low-priority keep actions preserve prior manual decisions and support one-step undo.

## Pipeline

The workflow runs the same tools available locally:

1. stream/build the selected real-data pack
2. validate it
3. score and audit the rounds
4. cache review images locally
5. exact/perceptual-dedupe the cached images
6. screen text and images for privacy/review signals
7. optionally remove high-severity cases
8. audit the screened pack again
9. optionally validate and apply exported curator decisions
10. audit the curated pack when decisions were applied
11. split the final pack into deterministic static shards
12. validate every shard and hash
13. assemble the game and curator browser files, manifest, shards, and cached images
14. serve the generated directory over HTTP and smoke-test the game data and curator page
15. upload the site and reports as separate GitHub Actions artifacts

Pull requests exercise this same packaging path against the bundled demo instead of the remote Amazon dataset. The PR fixture also creates a valid curation decisions file, rejects one fixture round, and verifies that the final sharded site contains five rounds instead of six.

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

`build-info.json` records the deployed round count, final dataset signature, screening report summary, and curation summary.

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
