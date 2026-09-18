# What Did They Buy?

A browser game where you see a mysterious customer review photo and guess which product the reviewer bought.

The repository includes a six-round original demo plus streaming data tools for the [McAuley Lab Amazon Reviews 2023 dataset](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023). No live Amazon-page scraping is required.

## Features

- Photo-only and photo-plus-review clue modes
- Four-choice rounds with keyboard shortcuts
- Score and streak bonuses
- Category filtering and selectable game length
- Deterministic five-round daily challenge
- Shareable daily result squares and deep links
- Daily result persistence per dataset/date
- Broken-image skip handling
- Mobile-friendly, framework-free UI
- Bundled original demo images, so the game works immediately
- Automatic `data/rounds.json` loading with demo fallback
- Standard-library Python builders for local files or streamed `.jsonl.gz` URLs
- Multi-category pack generation
- Hierarchical-category distractors with near-duplicate title rejection
- Optional review-image URL health checks
- Dataset validation and lightweight CI

## Run it

```bash
python -m http.server 8000
```

Then open `http://localhost:8000`. A static server is recommended because the game loads round data with `fetch()`.

## Daily challenge

Click **Daily challenge** for the same five rounds and answer order for everyone using the same dataset and UTC date. A completed result is stored in local storage using both the dataset signature and date.

Daily deep links use:

```text
?daily=2026-09-18
```

`?daily=1` and `?daily=today` resolve to the current UTC date. Shared results look like:

```text
What Did They Buy? Daily 2026-09-18
4/5 · 480 pts
🟩🟥🟩🟩🟩
https://example.test/?daily=2026-09-18
```

The deterministic logic lives in `game-core.js` and has zero dependencies so it can be tested directly with Node.

## Build a real multi-category pack

The easiest path streams the official UCSD category archives directly. Raw multi-gigabyte files are not retained on disk.

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

The source archives are large, so a five-category build transfers significant data even though it streams them. Image URL checks are enabled by default.

Useful options:

```bash
# Keep successful categories if another remote category fails
python scripts/build_pack.py --limit 2000 --continue-on-error

# Faster data-logic iteration without selected-image health checks
python scripts/build_pack.py --limit 500 --no-check-images
```

Default categories:

- `Pet_Supplies`
- `Patio_Lawn_and_Garden`
- `Tools_and_Home_Improvement`
- `Automotive`
- `Home_and_Kitchen`

## Use already-downloaded raw files

```text
data/raw/
  Pet_Supplies.jsonl.gz
  meta_Pet_Supplies.jsonl.gz
  Automotive.jsonl.gz
  meta_Automotive.jsonl.gz
```

```bash
python scripts/build_pack.py \
  --categories Pet_Supplies Automotive \
  --raw-dir data/raw \
  --limit 1000
```

`data/raw/` and generated `data/rounds.json` are ignored by Git by default.

## Build one category directly

`scripts/build_dataset.py` accepts local paths or HTTP(S) URLs:

```bash
python scripts/build_dataset.py \
  --reviews https://datarepo.eng.ucsd.edu/mcauley_group/data/amazon_2023/raw/review_categories/Pet_Supplies.jsonl.gz \
  --metadata https://datarepo.eng.ucsd.edu/mcauley_group/data/amazon_2023/raw/meta_categories/meta_Pet_Supplies.jsonl.gz \
  --source-category Pet_Supplies \
  --output data/rounds.json \
  --limit 1000
```

For fixture/debug work, `--max-review-records` and `--max-metadata-records` cap scans. Metadata caps can reduce successful joins and are not recommended for final packs.

## Round generation

1. Stream review records and reservoir-sample reviews containing customer images.
2. Join sampled reviews to metadata with `parent_asin`.
3. Keep a bounded metadata reservoir for distractors.
4. Normalize known image representations and numeric/string prices.
5. Use hierarchical categories to rank plausible wrong answers.
6. Reject near-duplicate listing titles that make answers ambiguous.
7. Emit at most one round per parent product.
8. Optionally verify selected review image URLs.
9. Balance categories, deduplicate, shuffle, and trim the final pack.

## Validate a generated pack

```bash
python scripts/validate_dataset.py data/rounds.json
```

The validator checks required fields, exactly four unique choices, correct-answer presence, duplicate IDs/products, ratings, and image references.

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
      "choices": ["Automatic Cat Water Fountain", "...", "...", "..."]
    }
  ]
}
```

## Tests

```bash
node --check game-core.js
node --check app.js
node tests/test_game_core.js
python -m compileall -q scripts tests
python scripts/validate_dataset.py data/demo.json
python -m unittest discover -s tests -p 'test_*.py' -v
```

CI runs only these lightweight checks and cancels superseded runs.

## GitHub Pages

The game has no build step. GitHub Pages can publish the repository root directly. The bundled demo works as-is. A generated real-data pack is intentionally ignored by Git because it may be large and because publishing third-party review media should be a deliberate decision.

## Content and rights note

This project is not affiliated with or endorsed by Amazon. The bundled demo artwork is original to this repository. The Amazon Reviews 2023 dataset contains third-party review content and customer-posted image URLs. Research-dataset availability should not be treated as an automatic grant to republish every customer image in a public or commercial game. Review the dataset terms and applicable content rights before deploying real review images publicly.

## Next technical milestones

- Per-round difficulty based on distractor similarity
- Perceptual-image duplicate detection
- Optional local image cache for controlled/private deployments
- Moderation filters for unsafe or personally identifying review images
- Tiny API/object-storage mode for packs too large to ship as one JSON file
