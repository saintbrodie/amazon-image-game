# Static sharded packs

A normal game pack stores every round in one `data/rounds.json` file. That is simple and works well for hundreds or a few thousand compact rounds, but larger curated pools eventually make startup download and JSON parsing unnecessarily expensive.

`shard_dataset.py` splits an existing browser-ready pack into deterministic static shard files plus a lightweight manifest. Both the game and Round Curator consume this format directly and lazy-load only the shards they actually need.

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

The manifest intentionally contains no full review text, image URL, product metadata, or answer-choice arrays. It keeps enough information to select game rounds and triage curator queues before loading full shard records.

When scoring/screening information exists, each index row may also include compact curation fields:

- `analysis.curation_priority`
- `analysis.difficulty_score`
- `screening.risk_score`
- `screening.needs_review`
- `screening.high_risk`
- compact severity counts
- compact screening flag `name`/`severity` pairs for signal queues

Detailed screening metadata, flag sources/details, image metadata, reviews, choices, and product records remain only in shard files.

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
      "shard": "0001",
      "analysis": {
        "curation_priority": 18,
        "difficulty_score": 44
      },
      "screening": {
        "risk_score": 20,
        "needs_review": true,
        "high_risk": false,
        "severity_counts": {"medium": 1},
        "flags": [
          {"name": "person_face_detected", "severity": "medium"}
        ]
      }
    }
  ]
}
```

## Determinism

Round-to-shard assignment is stable for the same set of round IDs and seed, even if the input JSON round order changes. The dataset signature depends only on the complete set of round IDs, so changing shard size or assignment seed does not create a different logical dataset identity.

The deterministic index is important for daily challenges. A browser can choose the daily round IDs from the lightweight manifest first, discover which shards contain those IDs, and fetch only those shard files.

## Browser behavior

`dataset-loader.js` prefers `data/rounds.manifest.json` and falls back to the legacy single-file datasets when no manifest exists.

The game:

1. selects ordinary or daily round IDs from the manifest index
2. resolves only the shards containing those IDs
3. fetches each required shard once and caches it for the page session

The curator:

1. filters/sorts the compact index without fetching full rounds
2. builds screening-signal queues from compact flag summaries
3. computes conservative bulk-action candidate counts from index summaries
4. fetches only the shard containing the round currently displayed
5. ignores stale asynchronous loads when navigation moves to another round first

Chromium E2E tests assert that both surfaces fetch fewer than all shards for small selections and that curator filtering does not silently preload unrelated data.

## Deployment intent

This format is designed for static hosting such as GitHub Pages, Cloudflare Pages, S3-compatible object storage, or any ordinary HTTP server. It does not require a database or API server.

The existing single-file `data/rounds.json` path remains the compatibility fallback for small packs and hand-authored datasets.
