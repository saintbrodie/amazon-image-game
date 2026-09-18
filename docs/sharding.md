# Static sharded packs

A normal game pack stores every round in one `data/rounds.json` file. That is simple and works well for hundreds or a few thousand compact rounds, but larger curated pools eventually make startup download and JSON parsing unnecessarily expensive.

`shard_dataset.py` splits an existing browser-ready pack into deterministic static shard files plus a lightweight manifest.

## Build shards

```bash
python scripts/shard_dataset.py data/rounds.curated.json \
  --manifest data/rounds.manifest.json \
  --shard-size 250
```

This creates files such as:

```text
data/
  rounds.manifest.json
  shards/
    rounds-0001.json
    rounds-0002.json
    rounds-0003.json
```

The generated files are ignored by Git by default.

## Validate

```bash
python scripts/validate_shards.py data/rounds.manifest.json
```

Validation checks:

- every manifest shard exists
- SHA-256 integrity for every shard
- no duplicate round IDs
- no missing indexed rounds
- manifest index points to the correct shard
- category counts agree at shard and dataset level
- dataset signature agrees with the actual round IDs
- shard paths cannot escape the manifest directory

## Manifest shape

The manifest intentionally contains no full review text, product metadata, or answer-choice arrays. It keeps just enough information to select rounds before loading their full shard.

```json
{
  "version": 1,
  "format": "amazon-image-game-sharded-pack",
  "name": "Amazon Review Mystery Pack",
  "dataset_signature": "5e5a...",
  "round_count": 10000,
  "shard_size": 250,
  "categories": {
    "Automotive": 2000,
    "Home_and_Kitchen": 2000
  },
  "shards": [
    {
      "id": "0001",
      "path": "shards/rounds-0001.json",
      "round_count": 250,
      "sha256": "...",
      "categories": {
        "Automotive": 47,
        "Home_and_Kitchen": 55
      }
    }
  ],
  "index": [
    {
      "id": "abc123",
      "category": "Automotive",
      "shard": "0001"
    }
  ]
}
```

## Determinism

Round-to-shard assignment is stable for the same set of round IDs and seed, even if the input JSON round order changes. The dataset signature depends only on the complete set of round IDs, so changing shard size or assignment seed does not create a different logical dataset identity.

The deterministic index is important for daily challenges. A browser can choose the daily round IDs from the lightweight manifest first, discover which shards contain those IDs, and fetch only those shard files.

## Deployment intent

This format is designed for static hosting such as GitHub Pages, Cloudflare Pages, S3-compatible object storage, or any ordinary HTTP server. It does not require a database or API server.

A future browser loader can prefer `data/rounds.manifest.json`, select only the rounds required for the current game, and lazily fetch their shards. The existing single-file `data/rounds.json` path remains the compatibility fallback.
