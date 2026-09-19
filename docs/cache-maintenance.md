# Review-image cache maintenance

`cache_images.py` writes customer-review images into a content-addressed cache. Re-running it is safe because identical bytes reuse the same filename, but regenerating or curating packs can leave older files that are no longer referenced by any active dataset.

`scripts/prune_image_cache.py` reports those orphaned files and can remove them explicitly.

## Dry run first

```bash
python scripts/prune_image_cache.py data/rounds.cached.json \
  --asset-dir assets/review-cache \
  --public-prefix assets/review-cache \
  --report data/cache-maintenance.json
```

Dry-run is the default. It reports:

- total cache files and bytes
- referenced files and bytes
- referenced files that are missing from disk
- orphaned files and reclaimable bytes
- remote/non-cache review-image references
- skipped symlinks or unsafe paths

No file is removed without `--delete`.

## Prune after reviewing the report

```bash
python scripts/prune_image_cache.py data/rounds.cached.json \
  --asset-dir assets/review-cache \
  --public-prefix assets/review-cache \
  --report data/cache-maintenance.json \
  --delete
```

Only files under `--asset-dir` that are not referenced by any supplied source are deleted. Empty cache subdirectories are removed afterward. Symlinks are skipped rather than followed or deleted.

## Preserve a cache shared by multiple packs

Pass every active pack in one command. References are unioned before anything is classified as orphaned:

```bash
python scripts/prune_image_cache.py \
  data/pet-supplies.cached.json \
  data/automotive.cached.json \
  data/home-kitchen.cached.json \
  --asset-dir assets/review-cache \
  --public-prefix assets/review-cache
```

This is important when multiple deployed or archived packs intentionally share one content-addressed cache.

## Sharded packs

A local sharded manifest can be supplied instead of the original full JSON:

```bash
python scripts/prune_image_cache.py data/rounds.manifest.json \
  --asset-dir assets/review-cache \
  --public-prefix assets/review-cache
```

The tool reads each local shard listed by the manifest and gathers `review_image` references from the full round records. Unsafe shard paths such as `../outside.json` are rejected.

## Missing references

A referenced cache path that does not exist is never treated as an orphan. It is reported separately as a missing reference. Missing references usually indicate that a cache directory was partially copied, manually cleaned, or generated from a different pack revision.

## Safety model

The pruner is intentionally conservative:

- dry-run is the default
- deletion requires `--delete`
- source files must exist locally
- manifest shard paths cannot escape the manifest directory
- review-image paths with traversal are ignored as cache references
- symlinks are skipped
- deletion is limited to ordinary files physically contained under `--asset-dir`
- multiple supplied datasets are treated as one combined live-reference set

For a cache used by anything outside this project, include those packs as sources too or keep separate cache directories.
