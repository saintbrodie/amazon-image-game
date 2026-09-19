import json
import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from shared_workspace_server import (  # noqa: E402
    WorkspaceStore,
    empty_workspace,
    merge_workspaces,
    normalize_workspace,
)


def workspace(signature="sig", decisions=None, annotations=None, presets=None):
    return {
        "version": 2,
        "dataset_signature": signature,
        "decisions": decisions or {},
        "annotations": annotations or {},
        "queue_presets": presets or [],
    }


class SharedWorkspaceMergeTests(unittest.TestCase):
    def test_disjoint_changes_merge_without_conflict(self):
        base = workspace(decisions={"a": "keep"})
        local = workspace(decisions={"a": "keep", "b": "reject"})
        remote = workspace(decisions={"a": "keep", "c": "keep"})
        merged, conflicts = merge_workspaces(base, local, remote)
        self.assertEqual(conflicts, [])
        self.assertEqual(merged["decisions"], {"a": "keep", "b": "reject", "c": "keep"})

    def test_same_round_conflict_is_reported(self):
        base = workspace(decisions={})
        local = workspace(decisions={"a": "keep"})
        remote = workspace(decisions={"a": "reject"})
        merged, conflicts = merge_workspaces(base, local, remote)
        self.assertEqual(merged["decisions"]["a"], "reject")
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["field"], "decisions")
        self.assertEqual(conflicts[0]["key"], "a")

    def test_conflict_strategies_resolve_explicitly(self):
        base = workspace(annotations={"a": {"note": "base", "tags": []}})
        local = workspace(annotations={"a": {"note": "mine", "tags": ["x"]}})
        remote = workspace(annotations={"a": {"note": "theirs", "tags": ["y"]}})
        mine, conflicts = merge_workspaces(base, local, remote, strategy="prefer_local")
        theirs, conflicts_remote = merge_workspaces(base, local, remote, strategy="prefer_remote")
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(len(conflicts_remote), 1)
        self.assertEqual(mine["annotations"]["a"]["note"], "mine")
        self.assertEqual(theirs["annotations"]["a"]["note"], "theirs")

    def test_preset_names_merge_case_insensitively(self):
        base = workspace()
        local = workspace(presets=[{"name": "Faces", "status": "undecided", "maxPriority": 20}])
        remote = workspace(presets=[{"name": "QR", "status": "all", "maxPriority": 30}])
        merged, conflicts = merge_workspaces(base, local, remote)
        self.assertEqual(conflicts, [])
        self.assertEqual([row["name"] for row in merged["queue_presets"]], ["Faces", "QR"])

    def test_normalization_drops_invalid_values(self):
        result = normalize_workspace({
            "decisions": {"a": "keep", "b": "maybe"},
            "annotations": {"a": {"note": " hi ", "tags": ["One", "one", "Two"]}},
            "queue_presets": [{"name": " Queue ", "maxPriority": -5}],
        }, "sig")
        self.assertEqual(result["decisions"], {"a": "keep"})
        self.assertEqual(result["annotations"]["a"], {"note": "hi", "tags": ["One", "Two"]})
        self.assertEqual(result["queue_presets"][0]["maxPriority"], 0)


class WorkspaceStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = WorkspaceStore(Path(self.temp.name) / "workspaces.sqlite")

    def tearDown(self):
        self.temp.cleanup()

    def test_first_save_creates_revision_and_history(self):
        result = self.store.save(
            "sig",
            base_revision=0,
            workspace=workspace(decisions={"a": "keep"}),
            actor="Alice",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["revision"], 1)
        self.assertEqual(self.store.head("sig")["workspace"]["decisions"], {"a": "keep"})
        self.assertEqual(self.store.history("sig")[0]["updated_by"], "Alice")

    def test_stale_disjoint_save_merges_onto_current_revision(self):
        first = self.store.save(
            "sig",
            base_revision=0,
            workspace=workspace(decisions={"a": "keep"}),
            actor="Alice",
        )
        self.assertEqual(first["revision"], 1)
        second = self.store.save(
            "sig",
            base_revision=0,
            workspace=workspace(decisions={"b": "reject"}),
            actor="Bob",
        )
        self.assertTrue(second["ok"])
        self.assertEqual(second["revision"], 2)
        self.assertEqual(second["workspace"]["decisions"], {"a": "keep", "b": "reject"})

    def test_stale_conflict_returns_current_without_writing(self):
        self.store.save(
            "sig",
            base_revision=0,
            workspace=workspace(decisions={"a": "keep"}),
            actor="Alice",
        )
        conflict = self.store.save(
            "sig",
            base_revision=0,
            workspace=workspace(decisions={"a": "reject"}),
            actor="Bob",
        )
        self.assertFalse(conflict["ok"])
        self.assertTrue(conflict["conflict"])
        self.assertEqual(conflict["revision"], 1)
        self.assertEqual(self.store.head("sig")["revision"], 1)

    def test_explicit_resolution_advances_revision(self):
        self.store.save(
            "sig",
            base_revision=0,
            workspace=workspace(decisions={"a": "keep"}),
            actor="Alice",
        )
        result = self.store.save(
            "sig",
            base_revision=0,
            workspace=workspace(decisions={"a": "reject"}),
            actor="Bob",
            strategy="prefer_local",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["revision"], 2)
        self.assertEqual(result["workspace"]["decisions"]["a"], "reject")
        self.assertEqual(result["resolved_conflicts"], 1)

    def test_unknown_old_base_revision_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "no longer available"):
            self.store.save(
                "sig",
                base_revision=9,
                workspace=workspace(),
                actor="Alice",
            )


if __name__ == "__main__":
    unittest.main()
