# Object-storage publishing

Large rotating game pools do not need to carry every cached review image inside the static-site artifact. `scripts/publish_assets.py` can upload the content-addressed review-image cache to S3-compatible object storage and add a small delivery mapping to the sharded dataset manifest.

The game still serves its HTML, JavaScript, manifest, and shard JSON normally. Only matching cached review-image paths are redirected to the configured public object/CDN base URL at runtime.

## Why the manifest mapping exists

Cached rounds normally contain paths such as:

```text
assets/review-cache/0123456789abcdef01234567.jpg
```

After publishing, `data/rounds.manifest.json` gains:

```json
{
  "asset_delivery": {
    "review_images": {
      "path_prefix": "assets/review-cache/",
      "base_url": "https://cdn.example.com/reviews/"
    }
  }
}
```

`DatasetLoader` then resolves only paths under `assets/review-cache/` through that base URL. Absolute review-image URLs and unrelated local assets such as the bundled demo SVGs are left unchanged.

Because the shard JSON stays untouched, moving the image pool to another CDN or bucket later only requires changing the manifest mapping.

## Dry run first

The publisher is intentionally dry-run by default:

```bash
python scripts/publish_assets.py site \
  --bucket my-game-assets \
  --object-prefix review-cache \
  --public-base-url https://cdn.example.com/reviews/ \
  --report reports/publish-plan.json
```

This validates the site, manifest, asset directory, object prefix, and public URL. It reports the planned file/byte totals and samples at most 100 object keys. It does not upload files or modify the manifest.

The default expected layout is:

```text
site/
  data/
    rounds.manifest.json
    shards/...
  assets/
    review-cache/...
```

`--manifest` and `--asset-dir` may override those paths, but both must remain inside `site_dir`.

## Apply the upload

Install the optional publishing dependency:

```bash
python -m pip install -r requirements-publishing.txt
```

Then repeat the command with `--apply`:

```bash
python scripts/publish_assets.py site \
  --bucket my-game-assets \
  --object-prefix review-cache \
  --public-base-url https://cdn.example.com/reviews/ \
  --apply \
  --report reports/publish-result.json
```

The command uploads every ordinary file below the review-image cache with its detected image content type and:

```text
Cache-Control: public,max-age=31536000,immutable
```

That long immutable cache policy is appropriate because cache filenames are content-addressed. The manifest is written only after all uploads complete successfully.

The publisher never deletes remote objects. Use the local cache-pruning workflow separately and make remote lifecycle/deletion policies an intentional storage-provider decision.

## Credentials

Publishing uses standard boto3 credential discovery. Common choices include environment variables, an AWS credentials file, instance/runner roles, or `--profile` for a local named profile.

Do not put access keys in the manifest, command-line public URL, repository files, or generated reports.

## AWS S3

For ordinary AWS S3, the endpoint URL can normally be omitted:

```bash
python scripts/publish_assets.py site \
  --bucket my-game-assets \
  --object-prefix review-cache \
  --public-base-url https://images.example.com/reviews/ \
  --region us-east-1 \
  --apply
```

The public base URL can be an S3 public URL or, more commonly, a CDN/custom domain that serves the same object prefix.

## Cloudflare R2

R2 exposes an S3-compatible API. Supply the account-specific S3 endpoint while using the public/custom-domain URL separately for browser delivery:

```bash
python scripts/publish_assets.py site \
  --bucket my-game-assets \
  --object-prefix review-cache \
  --endpoint-url https://ACCOUNT_ID.r2.cloudflarestorage.com \
  --public-base-url https://images.example.com/reviews/ \
  --apply
```

The API endpoint and public delivery URL are deliberately separate settings.

## MinIO and other S3-compatible providers

Point `--endpoint-url` at the provider's S3 API endpoint:

```bash
python scripts/publish_assets.py site \
  --bucket game-assets \
  --object-prefix review-cache \
  --endpoint-url https://s3.internal.example.com \
  --public-base-url https://images.example.com/reviews/ \
  --apply
```

The same pattern works with S3-compatible services such as Wasabi and Backblaze B2 S3 when configured with the provider's endpoint and credentials.

## CORS and public access

Review images are loaded by normal `<img>` elements. The object/CDN URL must be reachable by the browser. If the bucket itself is private, put an appropriate public delivery layer or CDN in front of it.

The current game does not require image CORS headers merely to display the images, because it does not draw them into a canvas. Your CDN/bucket policy should still be configured according to your deployment and security requirements.

## Safety behavior

The publishing path has several deliberate limits:

- dry run unless `--apply` is provided
- manifest and asset directories cannot escape the supplied site root
- symlinked cache files are skipped
- object prefixes reject parent traversal
- public delivery URLs must be absolute HTTP(S) URLs with no query string or fragment
- runtime remapping rejects parent traversal and non-HTTP(S) delivery configuration
- absolute source review-image URLs remain unchanged
- manifest modification happens only after every upload succeeds

## Suggested deployment sequence

A practical large-pool flow is:

1. Build the real-data pack.
2. Score, audit, cache, screen, and curate it.
3. Shard the final pack.
4. Assemble the static site.
5. Run `publish_assets.py` without `--apply` and inspect the plan.
6. Publish the cached review images with `--apply`.
7. Deploy the now-updated static site normally.

Only the cached review-image pool moves to object storage. The game application remains a simple static deployment.
