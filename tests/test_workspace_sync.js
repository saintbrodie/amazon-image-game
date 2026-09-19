const assert = require("assert");
const WorkspaceSync = require("../workspace-sync.js");

function response(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() { return payload; },
  };
}

(async function run() {
  assert.strictEqual(
    WorkspaceSync.workspaceUrl("/api/workspaces/", "sig 1"),
    "/api/workspaces/sig%201",
  );
  assert.strictEqual(
    WorkspaceSync.historyUrl("https://curator.example/api/workspaces", "abc"),
    "https://curator.example/api/workspaces/abc/history",
  );
  assert.throws(() => WorkspaceSync.normalizeApiBase("javascript:alert(1)"), /http\(s\)/i);

  {
    const calls = [];
    const client = new WorkspaceSync.Client({
      datasetSignature: "sig",
      actor: "Alice",
      token: "secret",
      fetchFn: async (url, options) => {
        calls.push({ url, options });
        return response({ exists: false, revision: 0 }, 404);
      },
    });
    const result = await client.get();
    assert.strictEqual(result.exists, false);
    assert.strictEqual(result.revision, 0);
    assert.deepStrictEqual(result.workspace.decisions, {});
    assert.strictEqual(calls[0].options.headers.Authorization, "Bearer secret");
  }

  {
    let request = null;
    const client = new WorkspaceSync.Client({
      datasetSignature: "sig",
      actor: "Bob",
      fetchFn: async (url, options) => {
        request = { url, options };
        return response({
          ok: true,
          revision: 4,
          workspace: WorkspaceSync.emptyWorkspace("sig"),
          updated_by: "Bob",
        });
      },
    });
    const result = await client.sync({
      version: 2,
      dataset_signature: "sig",
      decisions: { a: "keep" },
      annotations: {},
      queue_presets: [],
    }, { baseRevision: 3 });
    assert.strictEqual(result.revision, 4);
    const body = JSON.parse(request.options.body);
    assert.strictEqual(body.actor, "Bob");
    assert.strictEqual(body.base_revision, 3);
    assert.strictEqual(body.conflict_strategy, "reject");
    assert.strictEqual(body.workspace.decisions.a, "keep");
  }

  {
    const client = new WorkspaceSync.Client({
      datasetSignature: "sig",
      fetchFn: async () => response({
        conflict: true,
        revision: 8,
        conflicts: [{ field: "decisions", key: "a" }],
      }, 409),
    });
    await assert.rejects(
      () => client.sync(WorkspaceSync.emptyWorkspace("sig"), { baseRevision: 5 }),
      (error) => {
        assert.ok(error instanceof WorkspaceSync.WorkspaceConflictError);
        assert.strictEqual(error.revision, 8);
        assert.strictEqual(error.conflicts.length, 1);
        return true;
      },
    );
  }

  {
    const client = new WorkspaceSync.Client({
      datasetSignature: "sig",
      fetchFn: async () => response({ history: [
        { revision: 2, updated_by: "Bob" },
        { revision: 1, updated_by: "Alice" },
      ] }),
    });
    const history = await client.history();
    assert.deepStrictEqual(history.map((row) => row.updated_by), ["Bob", "Alice"]);
  }

  console.log("workspace-sync tests passed");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
