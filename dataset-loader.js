(function initDatasetLoader(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.DatasetLoader = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function datasetLoaderFactory() {
  function cleanText(value, fallback = "") {
    return typeof value === "string" && value.trim() ? value.trim() : fallback;
  }

  function roundCategory(round) {
    return cleanText(round?.source_category)
      || cleanText(round?.product?.category)
      || "Other";
  }

  function normalizeInlinePayload(payload) {
    if (!payload || !Array.isArray(payload.rounds)) {
      throw new Error("Dataset must contain a rounds array.");
    }
    const rounds = payload.rounds.filter((round) => {
      return round
        && round.id
        && round.review_image
        && round.product?.title
        && Array.isArray(round.choices)
        && round.choices.length >= 2
        && round.choices.includes(round.product.title);
    });
    if (!rounds.length) throw new Error("Dataset does not contain any playable rounds.");
    return { ...payload, rounds };
  }

  function manifestLooksValid(manifest) {
    return Boolean(
      manifest
      && manifest.format === "amazon-image-game-sharded-pack"
      && Array.isArray(manifest.index)
      && Array.isArray(manifest.shards)
      && manifest.index.length
      && manifest.shards.length
      && manifest.dataset_signature,
    );
  }

  function sourceDirectory(source) {
    const value = String(source || "");
    const question = value.indexOf("?");
    const hash = value.indexOf("#");
    let end = value.length;
    if (question >= 0) end = Math.min(end, question);
    if (hash >= 0) end = Math.min(end, hash);
    const clean = value.slice(0, end);
    const slash = clean.lastIndexOf("/");
    return slash >= 0 ? clean.slice(0, slash + 1) : "";
  }

  function resolveRelativeSource(relative, manifestSource) {
    const path = String(relative || "");
    if (/^[a-z][a-z0-9+.-]*:/i.test(path) || path.startsWith("//")) return path;
    if (/^[a-z][a-z0-9+.-]*:/i.test(String(manifestSource || ""))) {
      return new URL(path, manifestSource).toString();
    }
    return `${sourceDirectory(manifestSource)}${path}`;
  }

  function uniqueCategoriesFromIndex(index) {
    return [...new Set(index.map((row) => cleanText(row.category, "Other")))]
      .sort((left, right) => left.localeCompare(right));
  }

  async function fetchJson(fetchFn, source) {
    const response = await fetchFn(source, { cache: "no-store" });
    if (!response || !response.ok) {
      const status = response?.status ?? "network";
      const error = new Error(`${source}: ${status}`);
      error.status = response?.status;
      throw error;
    }
    return response.json();
  }

  class InlineDataSource {
    constructor(payload, source) {
      this.type = "inline";
      this.source = source;
      this.payload = normalizeInlinePayload(payload);
      this.metadata = this.payload;
      this.roundMap = new Map(this.payload.rounds.map((round) => [String(round.id), round]));
      this.index = this.payload.rounds.map((round) => ({
        id: String(round.id),
        category: roundCategory(round),
        shard: null,
      }));
      this.roundCount = this.index.length;
      this.signature = null;
    }

    categories() {
      return uniqueCategoriesFromIndex(this.index);
    }

    async loadEntries(entries) {
      return entries.map((entry) => {
        const round = this.roundMap.get(String(entry.id));
        if (!round) throw new Error(`Round ${entry.id} is missing from inline dataset.`);
        return round;
      });
    }
  }

  class ShardedDataSource {
    constructor(manifest, source, fetchFn) {
      if (!manifestLooksValid(manifest)) throw new Error("Invalid sharded dataset manifest.");
      this.type = "sharded";
      this.source = source;
      this.manifest = manifest;
      this.metadata = manifest;
      this.fetchFn = fetchFn;
      this.index = manifest.index.map((row) => ({
        id: String(row.id),
        category: cleanText(row.category, "Other"),
        shard: String(row.shard),
      }));
      this.roundCount = Number(manifest.round_count) || this.index.length;
      this.signature = String(manifest.dataset_signature);
      this.shards = new Map(manifest.shards.map((row) => [String(row.id), row]));
      this.shardCache = new Map();
    }

    categories() {
      if (this.manifest.categories && typeof this.manifest.categories === "object") {
        return Object.keys(this.manifest.categories).sort((left, right) => left.localeCompare(right));
      }
      return uniqueCategoriesFromIndex(this.index);
    }

    async loadShard(shardId) {
      const key = String(shardId);
      if (this.shardCache.has(key)) return this.shardCache.get(key);
      const descriptor = this.shards.get(key);
      if (!descriptor) throw new Error(`Unknown dataset shard ${key}.`);
      const source = resolveRelativeSource(descriptor.path, this.source);
      const promise = fetchJson(this.fetchFn, source).then((payload) => {
        if (!payload || payload.format !== "amazon-image-game-shard" || !Array.isArray(payload.rounds)) {
          throw new Error(`Invalid dataset shard ${key}.`);
        }
        if (String(payload.dataset_signature || "") !== this.signature) {
          throw new Error(`Dataset signature mismatch in shard ${key}.`);
        }
        if (String(payload.shard?.id || "") !== key) {
          throw new Error(`Embedded shard ID mismatch in shard ${key}.`);
        }
        return new Map(payload.rounds.map((round) => [String(round.id), round]));
      }).catch((error) => {
        this.shardCache.delete(key);
        throw error;
      });
      this.shardCache.set(key, promise);
      return promise;
    }

    async loadEntries(entries) {
      const requested = entries.map((entry) => ({
        id: String(entry.id),
        shard: String(entry.shard),
      }));
      const shardIds = [...new Set(requested.map((entry) => entry.shard))];
      const maps = await Promise.all(shardIds.map(async (shardId) => [shardId, await this.loadShard(shardId)]));
      const roundMaps = new Map(maps);
      return requested.map((entry) => {
        const round = roundMaps.get(entry.shard)?.get(entry.id);
        if (!round) throw new Error(`Round ${entry.id} is missing from shard ${entry.shard}.`);
        return round;
      });
    }
  }

  async function open({
    manifestSource = "data/rounds.manifest.json",
    dataSources = ["data/rounds.json", "data/demo.json"],
    fetchFn = typeof fetch === "function" ? fetch.bind(globalThis) : null,
  } = {}) {
    if (!fetchFn) throw new Error("A fetch implementation is required.");

    try {
      const manifest = await fetchJson(fetchFn, manifestSource);
      if (!manifestLooksValid(manifest)) throw new Error("Invalid sharded dataset manifest.");
      return new ShardedDataSource(manifest, manifestSource, fetchFn);
    } catch (error) {
      if (error?.status !== 404 && error?.status !== 410) throw error;
    }

    let lastError = null;
    for (const source of dataSources) {
      try {
        const payload = await fetchJson(fetchFn, source);
        return new InlineDataSource(payload, source);
      } catch (error) {
        lastError = error;
      }
    }
    throw lastError || new Error("No game dataset could be loaded.");
  }

  return {
    InlineDataSource,
    ShardedDataSource,
    manifestLooksValid,
    normalizeInlinePayload,
    open,
    resolveRelativeSource,
    roundCategory,
  };
});
