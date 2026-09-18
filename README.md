# What Did They Buy?

A browser game where you see a mysterious customer review photo and guess which product the reviewer bought.

The repository includes a six-round original demo plus streaming data tools for the [McAuley Lab Amazon Reviews 2023 dataset](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023). No live Amazon-page scraping is required.

## Features

- Photo-only and photo-plus-review clue modes
- Four-choice rounds with keyboard shortcuts
- Score and streak bonuses
- Category filtering and selectable game length
- Broken-image skip handling
- Mobile-friendly, framework-free UI
- Bundled original demo images, so the game works immediately
- Automatic `data/rounds.json` loading with demo fallback
- Standard-library Python builders for local files or streamed `.jsonl.gz` URLs
- Multi-category pack generation
- Bounded reservoir sampling instead of loading the full corpus into memory
- Hierarchical-category distractors with near-duplicate title rejection
- Optional review-image URL health checks before publishing a pack
- Dataset validation and lightweight CI

## Run it

Clone the repo and serve the directory with any static server:

```bash
python -m http.server 8000
```

Then open `http://localhost:8000`.

A server is recommended instead of opening `index.html` directly because the game loads its rounds with `fetch()`.

## Build a real multi-category pack

The easiest path now streams the official UCSD category archives directly. It does not keep the raw multi-gigabyte files on disk.

```bash
python scripts/build_pack.py \
  --categories Pet_Supplies Patio_Lawn_and_Garden Tools_and_Home_Improvement Automotive Home_and_Kitchen \
  --limit 2000 \
  --output data/rounds.json
```

On PowerShell:

```powershell
python scripts/build_pack.py `
  --categories Pet_Supplies Patio_Lawn_and_Garden Tools_and_Home_Improvement Automotive Home_and_Kitchen `
  --limit 2000 `
  --output data/rounds.json
```

The builder processes categories sequentially, reservoir-samples image-bearing reviews, joins them to metadata with `parent_asin`, checks the selected review image URLs, and writes one compact pack. The source archives are large, so a five-category build transfers a significant amount of data even though it does not store the raw files locally.

To keep successful categories if one remote file fails:

```bash
python scripts/build_pack.py --limit 2000 --continue-on-error
```

Image URL checks are enabled by default. Disable them when iterating on data logic:

```bash
python scripts/build_pack.py --limit 500 --no-check-images
```

The script defaults to these five game-friendly categories:

- `Pet_Supplies`
- `Patio_Lawn_and_Garden`
- `Tools_and_Home_Improvement`
- `Automotive`
- `Home_and_Kitchen`

## Use already-downloaded raw files

Put matching category pairs in one directory:

```text
data/raw/
  Pet_Supplies.jsonl.gz
  meta_Pet_Supplies.jsonl.gz
  Automotive.jsonl.gz
  meta_Automotive.jsonl.gz
```

Then:

```bash
python scripts/build_pack.py \
  --categories Pet_Supplies Automotive \
  --raw-dir data/raw \
  --limit 1000
```

`data/raw/` and generated `data/rounds.json` are ignored by Git by default.

## Build one category directly

`scripts/build_dataset.py` accepts either local paths or HTTP(S) URLs:

```bash
python scripts/build_dataset.py \
  --reviews https://datarepo.eng.ucsd.edu/mcauley_group/data/amazon_2023/raw/review_categories/Pet_Supplies.jsonl.gz \
  --metadata https://datarepo.eng.ucsd.edu/mcauley_group/data/amazon_2023/raw/meta_categories/meta_Pet_Supplies.jsonl.gz \
  --source-category Pet_Supplies \
  --output data/rounds.json \
  --limit 1000
```

For development against a small local fixture, `--max-review-records` and `--max-metadata-records` can cap scans. Those caps are primarily debugging tools because stopping the metadata scan early may prevent sampled `parent_asin` values from being found.

## How round generation works

1. Stream review records and reservoir-sample reviews containing customer images.
2. Collect sampled `parent_asin` values.
3. Stream matching product metadata.
4. Keep metadata for sampled products plus a bounded distractor reservoir.
5. Normalize both known Amazon metadata image representations and numeric/string prices.
6. Use hierarchical product categories to rank plausible distractors.
7. Reject very similar listing titles that would make an answer ambiguous.
8. Emit at most one review round per parent product.
9. For multi-category packs, optionally verify selected review image URLs and remove dead ones.
10. Shuffle and trim the final pack to the requested size.

The seed is deterministic. Change `--seed` for a different sample.

## Validate a generated pack

Before using or publishing generated data:

```bash
python scripts/validate_dataset.py data/rounds.json
```

The validator checks required round fields, four unique choices, correct-answer presence, duplicate round IDs, duplicate `parent_asin` products, ratings, and image references.

## Output shape

```json
{
  "version": 2,
  "name": "Amazon Review Mystery Pack",
  "categories": ["Pet_Supplies", "Automotive"],
  "rounds": [
    {
      "id": "...",
      "source_category": "Pet_Supplies",
      "review_image": "https://...",
      "rating": 2,
      "review_title": "Broke in two days",
      "review_text": "...",
      "product": {
        "title": "Automatic Cat Water Fountain",
        "category": "Pet Supplies",
        "category_path": ["Cats", "Feeding & Watering Supplies", "Fountains"],
        "leaf_category": "Fountains",
        "price": 29.99,
        "asin": "...",
        "parent_asin": "...",
        "source_url": "https://www.amazon.com/dp/..."
      },
      "choices": [
        "Automatic Cat Water Fountain",
        "...",
        "...",
        "..."
      ]
    }
  ]
}
```

## Tests

```bash
node --check app.js
python -m compileall -q scripts tests
python scripts/validate_dataset.py data/demo.json
python -m unittest discover -s tests -v
```

CI runs only these lightweight checks and cancels superseded runs.

## GitHub Pages

The game has no build step. GitHub Pages can publish the repository root directly. The bundled demo works as-is. A generated real-data pack is intentionally ignored by Git because it may be large and because publishing third-party review media should be a deliberate decision.

## Content and rights note

This project is not affiliated with or endorsed by Amazon. The bundled demo artwork is original to this repository. The Amazon Reviews 2023 dataset contains third-party review content and customer-posted image URLs. Its availability as a research dataset should not be treated as an automatic grant to republish every customer image in a public or commercial game. Review the dataset terms and applicable content rights before deploying real review images publicly.

## Next technical milestones

- Deterministic daily challenge and shareable score card
- Per-round difficulty based on distractor similarity
- Perceptual-image duplicate detection
- Optional local image cache for controlled/private deployments
- Moderation filters for unsafe or personally identifying review images
- Tiny API/object-storage mode for packs too large to ship as one JSON file
