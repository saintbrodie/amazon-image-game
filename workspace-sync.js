(function initWorkspaceSync(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.WorkspaceSync = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function workspaceSyncFactory() {
  class WorkspaceConflictError extends Error {
    constructor(message, payload) {
      super(message);
      this.name = "WorkspaceConflictError";
      this.payload = payload || {};
      this.conflicts = Array.isArray(payload?.conflicts) ? payload.conflicts : [];
      this.revision = Number(payload?.revision) || 0;
    }
  }

  function cleanText(value, fallback = "") {
    return typeof value === "string" && value.trim() ? value.trim() : fallback;
  }

  function normalizeApiBase(value) {
    const raw = cleanText(value, "/api/workspaces");
    if (/^https?:\/\//i.test(raw)) return raw.replace(/\/+$/, "");
    if (/^[a-z][a-z0-9+.-]*:/i.test(raw) || raw.startsWith("//")) {
      throw new Error("Shared workspace API must use http(s) or a same-origin path.");
    }
    return `/${raw.replace(/^\/+|\/+$/g, "")}`;
  }

  function workspaceUrl(apiBase, signature) {
    const base = normalizeApiBase(apiBase);
    return `${base}/${encodeURIComponent(String(signature))}`;
  }

  function historyUrl(apiBase, signature) {
    return `${workspaceUrl(apiBase, signature)}/history`;
  }

  function emptyWorkspace(signature) {
    return {
      version: 2,
      dataset_signature: String(signature),
      decisions: {},
      annotations: {},
      queue_presets: [],
    };
  }

  async function responseJson(response) {
    let payload = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    return payload;
  }

  class Client {
    constructor({
      datasetSignature,
      apiBase = "/api/workspaces",
      actor = "anonymous",
      token = "",
      fetchFn = typeof fetch === "function" ? fetch.bind(globalThis) : null,
    } = {}) {
      this.datasetSignature = cleanText(datasetSignature);
      if (!this.datasetSignature) throw new Error("datasetSignature is required");
      this.apiBase = normalizeApiBase(apiBase);
      this.actor = cleanText(actor, "anonymous").slice(0, 80);
      this.token = String(token || "");
      this.fetchFn = fetchFn;
      if (!this.fetchFn) throw new Error("A fetch implementation is required.");
    }

    headers(includeJson = false) {
      const headers = { Accept: "application/json" };
      if (includeJson) headers["Content-Type"] = "application/json";
      if (this.token) headers.Authorization = `Bearer ${this.token}`;
      return headers;
    }

    async get() {
      const response = await this.fetchFn(workspaceUrl(this.apiBase, this.datasetSignature), {
        method: "GET",
        headers: this.headers(false),
        cache: "no-store",
      });
      const payload = await responseJson(response);
      if (response.status === 404) {
        return {
          exists: false,
          revision: 0,
          workspace: emptyWorkspace(this.datasetSignature),
          updated_by: "",
          updated_at: "",
        };
      }
      if (!response.ok) {
        throw new Error(payload?.error || `Shared workspace request failed: ${response.status}`);
      }
      return payload;
    }

    async history() {
      const response = await this.fetchFn(historyUrl(this.apiBase, this.datasetSignature), {
        method: "GET",
        headers: this.headers(false),
        cache: "no-store",
      });
      const payload = await responseJson(response);
      if (!response.ok) throw new Error(payload?.error || `Shared history request failed: ${response.status}`);
      return Array.isArray(payload?.history) ? payload.history : [];
    }

    async sync(workspace, { baseRevision = 0, strategy = "reject" } = {}) {
      const response = await this.fetchFn(workspaceUrl(this.apiBase, this.datasetSignature), {
        method: "PUT",
        headers: this.headers(true),
        cache: "no-store",
        body: JSON.stringify({
          actor: this.actor,
          base_revision: Math.max(0, Number(baseRevision) || 0),
          conflict_strategy: strategy,
          workspace,
        }),
      });
      const payload = await responseJson(response);
      if (response.status === 409) {
        throw new WorkspaceConflictError(
          `${Array.isArray(payload?.conflicts) ? payload.conflicts.length : 0} shared workspace conflicts`,
          payload,
        );
      }
      if (!response.ok) {
        throw new Error(payload?.error || `Shared workspace sync failed: ${response.status}`);
      }
      return payload;
    }
  }

  return {
    Client,
    WorkspaceConflictError,
    emptyWorkspace,
    historyUrl,
    normalizeApiBase,
    workspaceUrl,
  };
});
