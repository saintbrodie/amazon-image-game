# What Did They Buy?

A fast little browser game where you see a mysterious customer review photo and guess which product the reviewer bought.

The repository includes a six-round original demo and a streaming dataset builder for the [McAuley Lab Amazon Reviews 2023 dataset](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023). No live Amazon scraping is required.

## Features

- Photo-only and photo-plus-review clue modes
- Four-choice rounds with keyboard shortcuts
- Score and streak bonuses
- Mobile-friendly, framework-free UI
- Bundled original demo images, so the game works immediately
- Automatic `data/rounds.json` loading with demo fallback
- Standard-library Python builder for Amazon Reviews 2023 JSONL or JSONL.GZ files
- Bounded reservoir sampling instead of loading the full review corpus into memory
- Lightweight CI: JavaScript syntax, JSON validation, and importer tests only

## Run it

Clone the repo and serve the directory with any static server:

```bash
python -m http.server 8000
```

Then open `http://localhost:8000`.

A server is recommended instead of opening `index.html` directly because the game loads its rounds with `fetch()`.

## Try real Amazon Reviews 2023 data

The McAuley dataset is split into matching review and item-metadata files by category. Review records contain customer-posted image URLs and `parent_asin`; metadata records contain the corresponding product title, categories, price, and product images.

For a first test, download one category pair into `data/raw/`. Pet Supplies is a fun starting point:

```bash
mkdir -p data/raw
curl -L -o data/raw/Pet_Supplies.jsonl.gz \
  https://datarepo.eng.ucsd.edu/mcauley_group/data/amazon_2023/raw/review_categories/Pet_Supplies.jsonl.gz
curl -L -o data/raw/meta_Pet_Supplies.jsonl.gz \
  https://datarepo.eng.ucsd.edu/mcauley_group/data/amazon_2023/raw/meta_categories/meta_Pet_Supplies.jsonl.gz
```

Build a compact game dataset:

```bash
python scripts/build_dataset.py \
  --reviews data/raw/Pet_Supplies.jsonl.gz \
  --metadata data/raw/meta_Pet_Supplies.jsonl.gz \
  --output data/rounds.json \
  --limit 5000 \
  --name "Pet Supplies"
```

Refresh the game. It will prefer `data/rounds.json` and automatically fall back to `data/demo.json` when generated data is not present.

On Windows PowerShell, the same builder works with normal Windows paths. `curl.exe` can be used for the downloads if PowerShell aliases `curl` to another command.

## How the builder works

1. Streams the review file and reservoir-samples reviews that contain customer images.
2. Collects the sampled `parent_asin` values.
3. Streams the matching metadata file once.
4. Keeps metadata for sampled products plus a bounded distractor pool.
5. Prefers distractors from the same main category.
6. Writes a small browser-ready JSON file containing only playable rounds.

The default sampling seed is deterministic. Change `--seed` if you want a different pool.

### Output shape

```json
{
  "version": 1,
  "name": "Pet Supplies",
  "rounds": [
    {
      "id": "...",
      "review_image": "https://...",
      "rating": 2,
      "review_title": "Broke in two days",
      "review_text": "...",
      "product": {
        "title": "Automatic Cat Water Fountain",
        "category": "Pet Supplies",
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
python -m json.tool data/demo.json
python -m unittest discover -s tests -v
```

CI runs only these lightweight checks and cancels superseded runs.

## GitHub Pages

The game has no build step. GitHub Pages can publish the repository root directly. The bundled demo works as-is. Generated `data/rounds.json` and raw datasets are ignored by Git because real datasets can become large and should be an intentional publishing decision.

## Content and rights note

This project is not affiliated with or endorsed by Amazon. The bundled demo artwork is original to this repository. The Amazon Reviews 2023 dataset contains third-party review content and customer-posted image URLs. Its availability as a research dataset should not be treated as an automatic grant to republish every customer image in a public or commercial game. Review the dataset terms and applicable content rights before deploying real review images publicly.

## Good next steps

- Daily challenge with a deterministic shared seed
- Category packs and difficulty controls
- Better distractors based on title/category similarity
- Image health checks and local caching during dataset preparation
- Duplicate detection with perceptual hashes
- Moderation filters for unsafe or personally identifying review images
- A tiny API for a much larger rotating round pool
