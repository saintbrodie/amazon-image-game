(function sharedCuratorWorkspace() {
  const shared = {
    client: null,
    connected: false,
    revision: 0,
    dirty: false,
    syncing: false,
    conflict: null,
    syncTimer: null,
    pollTimer: null,
  };

  const els = {
    actor: document.querySelector("#sharedActorInput"),
    apiBase: document.querySelector("#sharedApiInput"),
    token: document.querySelector("#sharedTokenInput"),
    autoSync: document.querySelector("#sharedAutoSync"),
    connect: document.querySelector("#sharedConnectButton"),
    sync: document.querySelector("#sharedSyncButton"),
    disconnect: document.querySelector("#sharedDisconnectButton"),
    status: document.querySelector("#sharedStatus"),
    message: document.querySelector("#sharedMessage"),
    activity: document.querySelector("#sharedActivity"),
    conflictBox: document.querySelector("#sharedConflictBox"),
    conflictCount: document.querySelector("#sharedConflictCount"),
    preferMine: document.querySelector("#sharedPreferMineButton"),
    preferShared: document.querySelector("#sharedPreferSharedButton"),
  };

  if (!els.connect || typeof WorkspaceSync === "undefined") return;

  let applyingShared = false;
  let originalSaveWorkspace = null;

  function configKey() {
    return "mystery-cart-shared-config";
  }

  function tokenKey() {
    return "mystery-cart-shared-token";
  }

  function curatorReady() {
    return typeof state !== "undefined"
      && typeof saveWorkspace === "function"
      && typeof rebuildFilter === "function"
      && Boolean(state.datasetSignature)
      && Array.isArray(state.rounds)
      && state.rounds.length > 0;
  }

  function validIds() {
    return new Set(state.rounds.map((round) => String(round.id)));
  }

  function snapshot() {
    const ids = validIds();
    const decisions = {};
    Object.entries(state.decisions || {}).forEach(([id, value]) => {
      if (ids.has(id) && (value === "keep" || value === "reject")) decisions[id] = value;
    });
    return {
      version: 2,
      dataset_signature: state.datasetSignature,
      decisions,
      annotations: CuratorState.normalizeAnnotations(state.annotations, ids),
      queue_presets: CuratorState.normalizePresets(state.presets),
    };
  }

  function applySharedWorkspace(workspace) {
    if (!workspace || workspace.dataset_signature !== state.datasetSignature) {
      throw new Error("Shared workspace dataset signature does not match this curator dataset.");
    }
    const ids = validIds();
    const decisions = {};
    Object.entries(workspace.decisions || {}).forEach(([id, value]) => {
      if (ids.has(id) && (value === "keep" || value === "reject")) decisions[id] = value;
    });
    state.decisions = decisions;
    state.annotations = CuratorState.normalizeAnnotations(workspace.annotations, ids);
    state.presets = CuratorState.normalizePresets(workspace.queue_presets || workspace.presets);
    clearBulkUndo();

    applyingShared = true;
    try {
      originalSaveWorkspace();
    } finally {
      applyingShared = false;
    }
    populateTags();
    populatePresets();
    rebuildFilter({ preserveRoundId: currentRound()?.id || null });
  }

  function installWorkspaceHook() {
    originalSaveWorkspace = saveWorkspace;
    saveWorkspace = function sharedAwareSaveWorkspace(...args) {
      const result = originalSaveWorkspace(...args);
      if (!applyingShared) {
        document.dispatchEvent(new CustomEvent("curator:workspace-changed", {
          detail: { source: "local" },
        }));
      }
      return result;
    };
  }

  function apiHash(apiBase) {
    return GameCore.hashString(String(apiBase)).toString(16);
  }

  function metaKey(apiBase) {
    return `mystery-cart-shared-meta:${state.datasetSignature}:${apiHash(apiBase)}`;
  }

  function normalizeObject(value) {
    if (Array.isArray(value)) return value.map(normalizeObject);
    if (!value || typeof value !== "object") return value;
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, normalizeObject(value[key])]),
    );
  }

  function fingerprint(workspace) {
    return GameCore.hashString(JSON.stringify(normalizeObject(workspace))).toString(16);
  }

  function workspaceHasContent(workspace) {
    return Boolean(
      Object.keys(workspace?.decisions || {}).length
      || Object.keys(workspace?.annotations || {}).length
      || (workspace?.queue_presets || []).length,
    );
  }

  function loadConfig() {
    try {
      const parsed = JSON.parse(localStorage.getItem(configKey()) || "{}");
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
      return {};
    }
  }

  function saveConfig() {
    localStorage.setItem(configKey(), JSON.stringify({
      actor: els.actor.value.trim(),
      apiBase: els.apiBase.value.trim() || "/api/workspaces",
      autoSync: els.autoSync.checked,
    }));
    if (els.token.value) sessionStorage.setItem(tokenKey(), els.token.value);
    else sessionStorage.removeItem(tokenKey());
  }

  function loadMeta(apiBase) {
    try {
      const parsed = JSON.parse(localStorage.getItem(metaKey(apiBase)) || "{}");
      return {
        revision: Math.max(0, Number(parsed.revision) || 0),
        fingerprint: typeof parsed.fingerprint === "string" ? parsed.fingerprint : "",
      };
    } catch {
      return { revision: 0, fingerprint: "" };
    }
  }

  function saveMeta(workspace) {
    if (!shared.client) return;
    localStorage.setItem(metaKey(shared.client.apiBase), JSON.stringify({
      revision: shared.revision,
      fingerprint: fingerprint(workspace),
    }));
  }

  function setStatus(label, className = "") {
    els.status.textContent = label;
    els.status.className = `shared-status ${className}`.trim();
  }

  function setMessage(message = "") {
    els.message.textContent = message;
  }

  function renderControls() {
    els.connect.disabled = shared.connected || shared.syncing;
    els.sync.disabled = !shared.connected || shared.syncing || Boolean(shared.conflict);
    els.disconnect.disabled = !shared.connected;
    els.actor.disabled = shared.connected;
    els.apiBase.disabled = shared.connected;
    els.token.disabled = shared.connected;
    els.conflictBox.hidden = !shared.conflict;
    if (shared.conflict) {
      els.conflictCount.textContent = String(shared.conflict.conflicts?.length || 0);
    }
  }

  function formatActivity(rows) {
    if (!rows.length) return "No shared revisions yet.";
    return rows.slice(0, 5).map((row) => {
      const actor = row.updated_by || "anonymous";
      const date = row.updated_at ? new Date(row.updated_at).toLocaleString() : "";
      return `r${row.revision} ${actor}${date ? ` · ${date}` : ""}`;
    }).join("  ·  ");
  }

  async function refreshActivity() {
    if (!shared.client || !shared.connected) return;
    try {
      els.activity.textContent = formatActivity(await shared.client.history());
    } catch (error) {
      els.activity.textContent = `Could not load activity: ${error.message}`;
    }
  }

  function rememberSuccessfulSync(workspace, result) {
    shared.revision = Number(result.revision) || 0;
    shared.dirty = false;
    shared.conflict = null;
    applySharedWorkspace(workspace);
    saveMeta(workspace);
    const actor = result.updated_by || "shared workspace";
    const changed = result.changed === false ? "up to date" : `synced as revision ${shared.revision}`;
    setStatus(`Shared · r${shared.revision}`, "connected");
    setMessage(`${changed} · last update ${actor}`);
    renderControls();
    refreshActivity();
  }

  async function syncNow(strategy = "reject") {
    if (!shared.client || !shared.connected || shared.syncing) return;
    shared.syncing = true;
    renderControls();
    setStatus(`Syncing r${shared.revision}…`, "syncing");
    try {
      const result = await shared.client.sync(snapshot(), {
        baseRevision: shared.revision,
        strategy,
      });
      rememberSuccessfulSync(result.workspace, result);
    } catch (error) {
      if (error instanceof WorkspaceSync.WorkspaceConflictError) {
        shared.conflict = error.payload;
        setStatus(`Conflict · shared r${error.revision}`, "conflict");
        setMessage(`${error.conflicts.length} overlapping edits need a curator choice. Non-overlapping changes are preserved either way.`);
      } else {
        setStatus("Shared sync error", "error");
        setMessage(error.message);
      }
    } finally {
      shared.syncing = false;
      renderControls();
    }
  }

  function scheduleSync() {
    clearTimeout(shared.syncTimer);
    if (!shared.connected || !els.autoSync.checked || shared.conflict) return;
    shared.syncTimer = setTimeout(() => syncNow(), 700);
  }

  async function pollShared() {
    if (!shared.client || !shared.connected || shared.syncing || shared.conflict) return;
    try {
      const remote = await shared.client.get();
      if ((Number(remote.revision) || 0) > shared.revision) await syncNow();
    } catch (error) {
      setStatus("Shared connection issue", "error");
      setMessage(error.message);
    }
  }

  function startPolling() {
    clearInterval(shared.pollTimer);
    shared.pollTimer = setInterval(pollShared, 7000);
  }

  function stopPolling() {
    clearInterval(shared.pollTimer);
    shared.pollTimer = null;
    clearTimeout(shared.syncTimer);
    shared.syncTimer = null;
  }

  async function connect() {
    const actor = els.actor.value.trim();
    if (!actor) {
      els.actor.focus();
      setMessage("Enter an operator name before connecting.");
      return;
    }

    saveConfig();
    let client;
    try {
      client = new WorkspaceSync.Client({
        datasetSignature: state.datasetSignature,
        apiBase: els.apiBase.value.trim() || "/api/workspaces",
        actor,
        token: els.token.value,
      });
    } catch (error) {
      setMessage(error.message);
      return;
    }

    shared.client = client;
    shared.syncing = true;
    renderControls();
    setStatus("Connecting…", "syncing");
    try {
      const remote = await client.get();
      const meta = loadMeta(client.apiBase);
      shared.revision = meta.revision <= (Number(remote.revision) || 0) ? meta.revision : 0;
      shared.connected = true;
      shared.conflict = null;
      const local = snapshot();
      shared.dirty = !meta.fingerprint
        || fingerprint(local) !== meta.fingerprint
        || (workspaceHasContent(local) && meta.revision === 0);
      setStatus(`Shared · server r${Number(remote.revision) || 0}`, "connected");
      setMessage(remote.exists ? "Connected. Merging local and shared workspace…" : "Connected. Creating the first shared revision…");
    } catch (error) {
      shared.client = null;
      shared.connected = false;
      setStatus("Local only", "");
      setMessage(`Could not connect: ${error.message}`);
      shared.syncing = false;
      renderControls();
      return;
    }
    shared.syncing = false;
    renderControls();
    startPolling();
    await syncNow();
  }

  function disconnect() {
    stopPolling();
    shared.client = null;
    shared.connected = false;
    shared.revision = 0;
    shared.dirty = false;
    shared.conflict = null;
    setStatus("Local only", "");
    setMessage("Shared synchronization disconnected. Local workspace is still saved in this browser.");
    els.activity.textContent = "";
    renderControls();
  }

  async function resolveConflict(strategy) {
    if (!shared.conflict) return;
    const label = strategy === "prefer_local" ? "your edits" : "shared edits";
    if (!window.confirm(`Resolve ${shared.conflict.conflicts?.length || 0} overlapping edits using ${label}? Non-conflicting changes from both curators will still be merged.`)) return;
    await syncNow(strategy);
  }

  function initializeFields() {
    installWorkspaceHook();
    const config = loadConfig();
    const params = new URLSearchParams(window.location.search);
    els.actor.value = params.get("actor") || config.actor || "";
    els.apiBase.value = params.get("workspace_api") || config.apiBase || "/api/workspaces";
    els.autoSync.checked = config.autoSync !== false;
    els.token.value = sessionStorage.getItem(tokenKey()) || "";
    setStatus("Local only", "");
    renderControls();
    if (params.get("shared") === "1" && els.actor.value.trim()) connect();
  }

  els.connect.addEventListener("click", connect);
  els.disconnect.addEventListener("click", disconnect);
  els.sync.addEventListener("click", () => syncNow());
  els.preferMine.addEventListener("click", () => resolveConflict("prefer_local"));
  els.preferShared.addEventListener("click", () => resolveConflict("prefer_remote"));
  els.autoSync.addEventListener("change", () => {
    saveConfig();
    if (els.autoSync.checked && shared.dirty) scheduleSync();
  });

  document.addEventListener("curator:workspace-changed", () => {
    shared.dirty = true;
    if (shared.connected) {
      setStatus(`Shared · r${shared.revision} · local changes`, "dirty");
      scheduleSync();
    }
  });

  function waitForCurator() {
    if (curatorReady()) {
      initializeFields();
      return;
    }
    setTimeout(waitForCurator, 50);
  }

  waitForCurator();
})();
