# Shared multi-curator workspaces

The curator still works completely offline in one browser. Shared mode is an optional layer for two or more curators working on the same dataset signature.

The repository includes a small standard-library Python server backed by SQLite. It serves the static game/curator and exposes a workspace API from the same origin, so no separate application framework is required.

## Fastest local setup

From the repository root:

```bash
python scripts/shared_workspace_server.py \
  --root . \
  --db data/curator-workspaces.sqlite
```

Open:

```text
http://127.0.0.1:8000/curate.html
```

In **Shared workspace**:

1. Enter an operator name.
2. Leave **Workspace API** at `/api/workspaces` for same-origin use.
3. Click **Connect**.
4. Leave **Auto sync** enabled unless you deliberately want manual synchronization.

Each curator should use a different operator name. Operator names are audit labels, not authentication identities.

## Using a packaged deployment artifact

The deployment ZIP contains:

```text
workspace-sync.js
curate-shared.js
curate-shared.css
tools/shared_workspace_server.py
```

From the extracted site directory:

```bash
python tools/shared_workspace_server.py \
  --root . \
  --db curator-workspaces.sqlite
```

A normal static web server still works if shared curation is not needed. The extra browser controls simply remain disconnected.

## Multiple machines on a trusted LAN

Bind the server to a LAN interface and use a token:

```bash
export CURATOR_WORKSPACE_TOKEN='use-a-long-random-value'
python scripts/shared_workspace_server.py \
  --root . \
  --db data/curator-workspaces.sqlite \
  --host 0.0.0.0 \
  --port 8000
```

Curators browse to the server machine, for example:

```text
http://curator-server:8000/curate.html
```

Enter the same bearer token in the curator UI. The browser stores that token in `sessionStorage`, not persistent `localStorage`, so it is cleared when the browser session ends.

For anything beyond a trusted LAN, put the service behind HTTPS and an authenticating reverse proxy. The built-in bearer token is intentionally small and is not an account/role system.

## Separate static host and workspace API

Same-origin hosting is simplest. If the static curator is served from one origin and the workspace service from another, launch the service with the exact allowed curator origin:

```bash
python scripts/shared_workspace_server.py \
  --root . \
  --db data/curator-workspaces.sqlite \
  --host 0.0.0.0 \
  --port 8000 \
  --token 'long-random-token' \
  --cors-origin 'https://game.example.com'
```

Then set **Workspace API** in the browser to:

```text
https://curator-api.example.com/api/workspaces
```

Do not combine wildcard CORS with bearer authentication. The server rejects that configuration.

## What is synchronized

Shared workspace data is scoped by the dataset signature and contains:

- keep/reject decisions by round ID
- per-round notes and tags
- saved queue presets

It does **not** modify public game shards, review images, screening results, or generated dataset files.

Local workspace JSON export/import and **Copy Actions JSON** continue to work independently of shared mode.

## Revisions and three-way merging

Every successful shared write is stored as a new SQLite revision with:

- monotonically increasing revision number
- operator name
- timestamp
- complete normalized workspace snapshot

The browser remembers the revision it last synchronized. When a curator saves against an older revision, the server loads that historical revision as the common base and performs a three-way merge:

```text
common base
   ├─ curator's local workspace
   └─ current shared workspace
```

Disjoint changes merge automatically. Examples:

- Alice keeps round A while Bob rejects round B.
- Alice adds a note to round A while Bob changes round B.
- Alice saves a `Faces` queue while Bob saves a `QR` queue.

## What counts as a conflict

The merge units are:

- one round decision
- one round annotation record (note + tags together)
- one saved queue preset, keyed case-insensitively by preset name

A conflict occurs when both the local curator and the shared workspace changed the same merge unit differently after the common base revision.

The server returns HTTP `409` instead of silently choosing a winner. The curator then shows two explicit options:

- **Keep my conflicting edits**
- **Use shared conflicting edits**

Only overlapping units use that choice. Non-conflicting edits from both sides remain merged.

## Auto sync and polling

With **Auto sync** enabled:

- local workspace changes are debounced for roughly 700 ms before upload
- the browser checks for newer shared revisions periodically
- a newer remote revision triggers the same three-way merge path

**Sync now** forces an immediate synchronization.

If a conflict is open, automatic synchronization pauses until a curator resolves it.

## Activity and history

The UI shows the latest shared revision and recent actors. The server retains complete revision history in SQLite rather than only the current workspace.

API endpoints:

```text
GET /api/workspaces/<dataset-signature>
PUT /api/workspaces/<dataset-signature>
GET /api/workspaces/<dataset-signature>/history
```

The `PUT` request includes the curator's `base_revision`, actor, workspace, and conflict strategy.

Back up the SQLite database if the shared curation history matters. The database is the durable shared state.

## Authentication and security boundaries

The built-in service is deliberately small. It supports:

- loopback-by-default binding
- optional bearer token
- constant-time token comparison
- optional explicit CORS origin
- request-size limits
- normalized dataset-signature paths

It does not provide:

- user accounts
- per-user permissions
- SSO/OIDC
- TLS termination
- tenant isolation
- password recovery

For a team-facing internet deployment, put it behind infrastructure that provides those controls, or replace the storage/API implementation while keeping the same browser sync contract.

## Failure behavior

Shared mode is optional. If the workspace server is unavailable:

- the game is unaffected
- the curator still saves locally in the browser
- export/import still works
- local edits can be synchronized later after reconnecting

A requested synchronization failure is surfaced in the shared status area rather than silently discarding local state.
