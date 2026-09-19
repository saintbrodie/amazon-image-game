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

A small first run such as `All_Beauty`, 100 to 250 rounds, and shard size 50 to 75 is useful for checking the complete pipeline before starting a much larger category.

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
9. split it into deterministic static shards
10. validate every shard and hash
11. assemble the browser files, manifest, shards, and cached images
12. serve the generated directory over HTTP and smoke-test the manifest and first shard
13. upload the site and reports as separate GitHub Actions artifacts

Pull requests exercise this same packaging path against the bundled demo instead of the remote Amazon dataset.

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
build-info.json
CONTENT_RIGHTS_NOTICE.txt
assets/review-cache/...
data/rounds.manifest.json
data/shards/rounds-....json
```

Serve that directory from any ordinary static HTTP host. No application server or database is required.

### `amazon-image-game-reports-<run id>`

This contains the intermediate full packs plus before/after audits and the screening report. Keep it for curation/debugging rather than serving it publicly by default.

## Content rights

The deployment artifact can contain customer-posted third-party media. The workflow packages the data technically; it does not grant republication rights. Confirm the dataset/content terms appropriate to your use before publishing a real-data artifact.
