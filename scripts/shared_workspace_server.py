#!/usr/bin/env python3
"""Serve the static curator plus an optional shared workspace API.

The API stores full curator workspaces in SQLite and keeps every revision.
Clients send the revision they last synchronized. If the shared workspace moved
since then, the server performs a three-way merge against that historical base.
Disjoint decisions/annotations/presets merge automatically. Conflicting edits
return HTTP 409 unless the client explicitly selects prefer_local or
prefer_remote.

The server defaults to loopback and no authentication for local development.
Use --token (or CURATOR_WORKSPACE_TOKEN) and HTTPS through a reverse proxy before
exposing it beyond a trusted LAN.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sqlite3
import threading
from copy import deepcopy
from datetime import datetime, timezone
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

SIGNATURE_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
MISSING = object()
VALID_DECISIONS = {"keep", "reject"}
VALID_STRATEGIES = {"reject", "prefer_local", "prefer_remote"}
MAX_BODY_BYTES = 8 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def normalize_tags(value: Any) -> list[str]:
    source = value if isinstance(value, list) else []
    result: list[str] = []
    seen: set[str] = set()
    for raw in source:
        tag = clean_text(raw, 48)
        if not tag:
            continue
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(tag)
        if len(result) >= 16:
            break
    return result


def normalize_annotation(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    note = str(value.get("note") or "").strip()[:4000]
    tags = normalize_tags(value.get("tags"))
    if not note and not tags:
        return None
    return {"note": note, "tags": tags}


def normalize_preset(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    name = clean_text(value.get("name"), 60)
    if not name:
        return None
    try:
        priority = int(round(float(value.get("maxPriority", 20))))
    except (TypeError, ValueError):
        priority = 20
    return {
        "name": name,
        "category": clean_text(value.get("category"), 128) or "all",
        "status": clean_text(value.get("status"), 32) or "undecided",
        "screening": clean_text(value.get("screening"), 32) or "all",
        "signal": clean_text(value.get("signal"), 128) or "all",
        "tag": clean_text(value.get("tag"), 64) or "all",
        "sort": clean_text(value.get("sort"), 32) or "priority",
        "maxPriority": max(0, min(100, priority)),
    }


def empty_workspace(signature: str) -> dict[str, Any]:
    return {
        "version": 2,
        "dataset_signature": signature,
        "decisions": {},
        "annotations": {},
        "queue_presets": [],
    }


def normalize_workspace(value: Any, signature: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("workspace must be a JSON object")
    supplied = value.get("dataset_signature")
    if supplied not in (None, "", signature):
        raise ValueError("workspace dataset_signature does not match request path")

    decisions: dict[str, str] = {}
    raw_decisions = value.get("decisions")
    if isinstance(raw_decisions, dict):
        for raw_id, decision in raw_decisions.items():
            round_id = str(raw_id).strip()
            if round_id and decision in VALID_DECISIONS:
                decisions[round_id] = decision

    annotations: dict[str, dict[str, Any]] = {}
    raw_annotations = value.get("annotations")
    if isinstance(raw_annotations, dict):
        for raw_id, raw_annotation in raw_annotations.items():
            round_id = str(raw_id).strip()
            annotation = normalize_annotation(raw_annotation)
            if round_id and annotation:
                annotations[round_id] = annotation

    raw_presets = value.get("queue_presets")
    if raw_presets is None:
        raw_presets = value.get("presets")
    presets_by_key: dict[str, dict[str, Any]] = {}
    if isinstance(raw_presets, list):
        for raw in raw_presets:
            preset = normalize_preset(raw)
            if preset:
                presets_by_key[preset["name"].casefold()] = preset
            if len(presets_by_key) >= 30:
                break

    return {
        "version": 2,
        "dataset_signature": signature,
        "decisions": dict(sorted(decisions.items())),
        "annotations": dict(sorted(annotations.items())),
        "queue_presets": sorted(presets_by_key.values(), key=lambda row: row["name"].casefold()),
    }


def _preset_map(workspace: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        preset["name"].casefold(): preset
        for preset in workspace.get("queue_presets", [])
        if isinstance(preset, dict) and isinstance(preset.get("name"), str)
    }


def _conflict_value(value: Any) -> dict[str, Any]:
    if value is MISSING:
        return {"present": False, "value": None}
    return {"present": True, "value": deepcopy(value)}


def merge_mapping(
    base: dict[str, Any],
    local: dict[str, Any],
    remote: dict[str, Any],
    *,
    field: str,
    strategy: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    result: dict[str, Any] = {}
    conflicts: list[dict[str, Any]] = []
    for key in sorted(set(base) | set(local) | set(remote)):
        base_value = base.get(key, MISSING)
        local_value = local.get(key, MISSING)
        remote_value = remote.get(key, MISSING)

        if local_value == base_value:
            chosen = remote_value
        elif remote_value == base_value or local_value == remote_value:
            chosen = local_value
        else:
            conflicts.append({
                "field": field,
                "key": key,
                "base": _conflict_value(base_value),
                "local": _conflict_value(local_value),
                "remote": _conflict_value(remote_value),
            })
            chosen = local_value if strategy == "prefer_local" else remote_value

        if chosen is not MISSING:
            result[key] = deepcopy(chosen)
    return result, conflicts


def merge_workspaces(
    base: dict[str, Any],
    local: dict[str, Any],
    remote: dict[str, Any],
    *,
    strategy: str = "reject",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if strategy not in VALID_STRATEGIES:
        raise ValueError(f"unknown conflict strategy: {strategy}")
    signature = str(remote.get("dataset_signature") or local.get("dataset_signature") or base.get("dataset_signature") or "")
    base_n = normalize_workspace(base, signature)
    local_n = normalize_workspace(local, signature)
    remote_n = normalize_workspace(remote, signature)

    decisions, decision_conflicts = merge_mapping(
        base_n["decisions"], local_n["decisions"], remote_n["decisions"],
        field="decisions", strategy=strategy,
    )
    annotations, annotation_conflicts = merge_mapping(
        base_n["annotations"], local_n["annotations"], remote_n["annotations"],
        field="annotations", strategy=strategy,
    )
    presets, preset_conflicts = merge_mapping(
        _preset_map(base_n), _preset_map(local_n), _preset_map(remote_n),
        field="queue_presets", strategy=strategy,
    )
    conflicts = decision_conflicts + annotation_conflicts + preset_conflicts

    merged = {
        "version": 2,
        "dataset_signature": signature,
        "decisions": decisions,
        "annotations": annotations,
        "queue_presets": sorted(presets.values(), key=lambda row: row["name"].casefold()),
    }
    return merged, conflicts


class WorkspaceStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workspace_revisions (
                    dataset_signature TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    workspace_json TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (dataset_signature, revision)
                )
                """
            )

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "revision": int(row["revision"]),
            "workspace": json.loads(row["workspace_json"]),
            "updated_by": row["actor"],
            "updated_at": row["created_at"],
        }

    def head(self, signature: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT revision, workspace_json, actor, created_at FROM workspace_revisions "
                "WHERE dataset_signature = ? ORDER BY revision DESC LIMIT 1",
                (signature,),
            ).fetchone()
        return self._decode(row)

    def revision(self, signature: str, revision: int) -> dict[str, Any] | None:
        if revision == 0:
            return {
                "revision": 0,
                "workspace": empty_workspace(signature),
                "updated_by": "",
                "updated_at": "",
            }
        with self._connect() as connection:
            row = connection.execute(
                "SELECT revision, workspace_json, actor, created_at FROM workspace_revisions "
                "WHERE dataset_signature = ? AND revision = ?",
                (signature, revision),
            ).fetchone()
        return self._decode(row)

    def history(self, signature: str, limit: int = 10) -> list[dict[str, Any]]:
        limit = max(1, min(100, int(limit)))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT revision, actor, created_at FROM workspace_revisions "
                "WHERE dataset_signature = ? ORDER BY revision DESC LIMIT ?",
                (signature, limit),
            ).fetchall()
        return [
            {
                "revision": int(row["revision"]),
                "updated_by": row["actor"],
                "updated_at": row["created_at"],
            }
            for row in rows
        ]

    def save(
        self,
        signature: str,
        *,
        base_revision: int,
        workspace: dict[str, Any],
        actor: str,
        strategy: str = "reject",
    ) -> dict[str, Any]:
        if base_revision < 0:
            raise ValueError("base_revision must be non-negative")
        if strategy not in VALID_STRATEGIES:
            raise ValueError("invalid conflict_strategy")
        actor_name = clean_text(actor, 80) or "anonymous"
        local = normalize_workspace(workspace, signature)

        with self._lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                current_row = connection.execute(
                    "SELECT revision, workspace_json, actor, created_at FROM workspace_revisions "
                    "WHERE dataset_signature = ? ORDER BY revision DESC LIMIT 1",
                    (signature,),
                ).fetchone()
                current = self._decode(current_row) or {
                    "revision": 0,
                    "workspace": empty_workspace(signature),
                    "updated_by": "",
                    "updated_at": "",
                }
                if base_revision > current["revision"]:
                    raise ValueError("base_revision is newer than the shared workspace")

                base = self.revision(signature, base_revision)
                if base is None:
                    raise ValueError("base_revision is no longer available")

                if base_revision == current["revision"]:
                    merged = local
                    conflicts: list[dict[str, Any]] = []
                else:
                    merged, conflicts = merge_workspaces(
                        base["workspace"], local, current["workspace"], strategy=strategy
                    )

                if conflicts and strategy == "reject":
                    connection.rollback()
                    return {
                        "ok": False,
                        "conflict": True,
                        "revision": current["revision"],
                        "workspace": current["workspace"],
                        "updated_by": current["updated_by"],
                        "updated_at": current["updated_at"],
                        "conflicts": conflicts,
                    }

                if merged == current["workspace"]:
                    connection.rollback()
                    return {
                        "ok": True,
                        "conflict": False,
                        "changed": False,
                        "revision": current["revision"],
                        "workspace": current["workspace"],
                        "updated_by": current["updated_by"],
                        "updated_at": current["updated_at"],
                        "resolved_conflicts": len(conflicts),
                    }

                new_revision = current["revision"] + 1
                created_at = utc_now()
                connection.execute(
                    "INSERT INTO workspace_revisions "
                    "(dataset_signature, revision, workspace_json, actor, created_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        signature,
                        new_revision,
                        json.dumps(merged, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
                        actor_name,
                        created_at,
                    ),
                )
                connection.commit()
                return {
                    "ok": True,
                    "conflict": False,
                    "changed": True,
                    "revision": new_revision,
                    "workspace": merged,
                    "updated_by": actor_name,
                    "updated_at": created_at,
                    "resolved_conflicts": len(conflicts),
                }


class SharedWorkspaceHandler(SimpleHTTPRequestHandler):
    server_version = "MysteryCartWorkspace/1.0"

    @property
    def workspace_store(self) -> WorkspaceStore:
        return self.server.workspace_store  # type: ignore[attr-defined]

    @property
    def auth_token(self) -> str:
        return self.server.auth_token  # type: ignore[attr-defined]

    @property
    def cors_origin(self) -> str | None:
        return self.server.cors_origin  # type: ignore[attr-defined]

    def end_headers(self) -> None:
        if self.cors_origin:
            self.send_header("Access-Control-Allow-Origin", self.cors_origin)
            self.send_header("Vary", "Origin")
        super().end_headers()

    def _authorized(self) -> bool:
        if not self.auth_token:
            return True
        header = self.headers.get("Authorization", "")
        expected = f"Bearer {self.auth_token}"
        return secrets.compare_digest(header, expected)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        if isinstance(payload.get("revision"), int):
            self.send_header("ETag", f'"rev-{payload["revision"]}"')
        self.end_headers()
        self.wfile.write(encoded)

    def _api_parts(self) -> tuple[str, str | None] | None:
        path = urlparse(self.path).path
        prefix = "/api/workspaces/"
        if not path.startswith(prefix):
            return None
        remainder = path[len(prefix):].strip("/")
        if not remainder:
            return None
        parts = remainder.split("/")
        signature = unquote(parts[0])
        if not SIGNATURE_RE.fullmatch(signature):
            return None
        suffix = parts[1] if len(parts) == 2 else None
        if len(parts) > 2:
            return None
        return signature, suffix

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("request body is empty or too large")
        body = self.rfile.read(length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("request body must be valid UTF-8 JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def do_OPTIONS(self) -> None:
        if not self._api_parts():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self) -> None:
        route = self._api_parts()
        if route is None:
            super().do_GET()
            return
        if not self._authorized():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        signature, suffix = route
        if suffix == "history":
            self._send_json(HTTPStatus.OK, {
                "dataset_signature": signature,
                "history": self.workspace_store.history(signature, 12),
            })
            return
        if suffix is not None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        current = self.workspace_store.head(signature)
        if current is None:
            self._send_json(HTTPStatus.NOT_FOUND, {
                "exists": False,
                "dataset_signature": signature,
                "revision": 0,
                "workspace": empty_workspace(signature),
            })
            return
        self._send_json(HTTPStatus.OK, {
            "exists": True,
            "dataset_signature": signature,
            **current,
        })

    def do_PUT(self) -> None:
        route = self._api_parts()
        if route is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if not self._authorized():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        signature, suffix = route
        if suffix is not None:
            self._send_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "method_not_allowed"})
            return
        try:
            payload = self._read_json()
            base_revision = int(payload.get("base_revision", 0))
            strategy = str(payload.get("conflict_strategy") or "reject")
            result = self.workspace_store.save(
                signature,
                base_revision=base_revision,
                workspace=payload.get("workspace"),
                actor=str(payload.get("actor") or "anonymous"),
                strategy=strategy,
            )
        except (TypeError, ValueError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        status = HTTPStatus.CONFLICT if result.get("conflict") else HTTPStatus.OK
        self._send_json(status, result)


def build_server(
    *,
    host: str,
    port: int,
    root: Path,
    database: Path,
    token: str = "",
    cors_origin: str | None = None,
) -> ThreadingHTTPServer:
    handler = partial(SharedWorkspaceHandler, directory=str(root.resolve()))
    server = ThreadingHTTPServer((host, port), handler)
    server.workspace_store = WorkspaceStore(database.resolve())  # type: ignore[attr-defined]
    server.auth_token = token  # type: ignore[attr-defined]
    server.cors_origin = cors_origin  # type: ignore[attr-defined]
    return server


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."), help="Static site/repository root")
    parser.add_argument("--db", type=Path, default=Path("data/curator-workspaces.sqlite"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--token",
        default=os.environ.get("CURATOR_WORKSPACE_TOKEN", ""),
        help="Optional bearer token; defaults to CURATOR_WORKSPACE_TOKEN",
    )
    parser.add_argument(
        "--cors-origin",
        help="Optional allowed cross-origin curator origin; same-origin serving needs no CORS setting",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        raise SystemExit(f"static root does not exist: {root}")
    if not 1 <= args.port <= 65535:
        raise SystemExit("port must be between 1 and 65535")
    if args.cors_origin == "*" and args.token:
        raise SystemExit("do not combine wildcard CORS with bearer authentication")

    server = build_server(
        host=args.host,
        port=args.port,
        root=root,
        database=args.db,
        token=args.token,
        cors_origin=args.cors_origin,
    )
    address = server.server_address
    print(f"Shared curator server: http://{address[0]}:{address[1]}/curate.html")
    print(f"Workspace database: {args.db.resolve()}")
    if args.host not in {"127.0.0.1", "localhost", "::1"} and not args.token:
        print("WARNING: server is reachable beyond loopback without a bearer token.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
