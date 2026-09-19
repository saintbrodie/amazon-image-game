# Curator workspace

`curate.html` is the human review surface for generated game rounds. It keeps deployment decisions separate from operator-only working notes.

## Workspace state

The curator stores a dataset-scoped workspace in browser `localStorage`. The key includes the dataset signature, so work from one generated pack is not silently reused for another.

A workspace can contain:

- keep/reject decisions
- per-round tags
- per-round private operator notes
- saved queue presets

Tags and notes are curator metadata only. They are not written into game shards and are not included in the compact deployment payload.

## Tags and notes

Each displayed round has a **Tags** field and an **Operator note** field.

Tags are comma-separated. They are trimmed, case-insensitively deduplicated, capped at 16 tags per round, and limited to 48 characters per tag. Notes are trimmed and limited to 4,000 characters.

As soon as a tag is saved it appears in the **Tag** queue filter. This is useful for temporary review buckets such as:

- `funny`
- `ambiguous`
- `needs title check`
- `great image`
- `revisit`

## Queue presets

**Save current queue** stores the active:

- category
- decision status
- screening filter
- signal queue
- tag filter
- sort order
- auto-keep priority threshold

Presets are local to the dataset workspace and can be applied or deleted from the preset toolbar. An explicit auto-keep threshold of `0` is preserved.

## Export and import

**Export workspace** downloads a version 2 workspace JSON containing decisions, annotations, and queue presets. Use this when moving curation work between browsers or retaining a review record.

**Import workspace** accepts both the richer workspace export and older decision-only exports. Matching round IDs are imported. If the dataset signature differs, the curator requires confirmation before importing matching IDs.

## Deployment payload

**Copy Actions JSON** intentionally produces a smaller version 1 payload containing only:

- `dataset_signature`
- `kept_ids`
- `rejected_ids`

It excludes notes, tags, and queue presets. Paste this compact JSON into the `curation_json` input of the **Build deployment artifact** workflow.

The deployment workflow validates the dataset signature before applying decisions. Operator workspace metadata therefore remains private to the curation workflow and does not become part of the public static game artifact.

## Bulk actions

Bulk actions continue to operate only on undecided rounds:

- **Reject high-risk** rejects undecided high-risk screening rows.
- **Keep clear ≤N** keeps undecided screened-clear rounds at or below the configured curation-priority threshold.
- **Undo bulk** restores the previous state of the most recent bulk operation.

Existing manual keep/reject decisions are preserved by bulk actions.
