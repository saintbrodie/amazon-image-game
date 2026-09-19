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
      || cleanText(round?.category)
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

  function normalizeReviewImageDelivery(value) {
    if (!value || typeof value !== "object") return null;
    const rawPrefix = cleanText(value.path_prefix);
    const rawBase = cleanText(value.base_url);
    if (!rawPrefix || !rawBase || rawPrefix.startsWith("/") || rawPrefix.includes("\\")) return null;
    const prefixParts = rawPrefix.split("/").filter(Boolean);
    if (!prefixParts.length || prefixParts.some((part) => part === "." || part === "..")) return null;
    let parsed;
    try {
      parsed = new URL(rawBase);
    } catch {
      return null;
    }
    if (!['http:', 'https:'].includes(parsed.protocol)) return null;
    parsed.search = "";
    parsed.hash = "";
    const pathPrefix = `${prefixParts.join("/")}/`;
    const baseUrl = `${parsed.toString().replace(/\/+$/, "")}/`;
    return { path_prefix: pathPrefix, base_url: baseUrl };
  }

  function resolveReviewImage(reviewImage, delivery) {
    const path = cleanText(reviewImage);
    if (!path || !delivery) return reviewImage;
    if (/^[a-z][a-z0-9+.-]*:/i.test(path) || path.startsWith("//")) return path;
    if (!path.startsWith(delivery.path_prefix)) return path;
    const suffix = path.slice(delivery.path_prefix.length);
    if (!suffix || suffix.startsWith("/") || suffix.includes("\\")) return path;
    const parts = suffix.split("/");
    if (parts.some((part) => !part || part === "." || part === "..")) return path;
    try {
      return new URL(suffix, delivery.base_url).toString();
    } catch {
      return path;
    }
  }

  function applyReviewImageDelivery(round, delivery) {
    if (!round || typeof round !== "object" || !delivery) return round;
    const resolved = resolveReviewImage(round.review_image, delivery);
    if (resolved === round.review_image) return round;
    return { ...round, review_image: resolved };
  }

  function uniqueCategoriesFromIndex(index) {
    return [...new Set(index.map((row) => cleanText(row.category, "Other")))]
      .sort((left, right) => left.localeCompare(right));
  }

  function finiteNumber(value) {
    return typeof value === "number" && Number.isFinite(value) ? value : null;
  }

  function compactAnalysis(value) {
    if (!value || typeof value !== "object") return null;
    const result = {};
    const priority = finiteNumber(value.curation_priority);
    const difficulty = finiteNumber(value.difficulty_score);
    if (priority !== null) result.curation_priority = priority;
    if (difficulty !== null) result.difficulty_score = difficulty;
    return Object.keys(result).length ? result : null;
  }

  function compactScreeningFlags(value) {
    if (!Array.isArray(value)) return [];
    const seen = new Set();
    const flags = [];
    value.forEach((flag) => {
      if (!flag || typeof flag !== "object") return;
      const name = cleanText(flag.name);
      if (!name) return;
      const severity = ["low", "medium", "high"].includes(flag.severity) ? flag.severity : null;
      const key = `${name}\u0000${severity || ""}`;
      if (seen.has(key)) return;
      seen.add(key);
      const item = { name };
      if (severity) item.severity = severity;
      flags.push(item);
    });
    return flags.sort((left, right) => {
      const nameOrder = left.name.localeCompare(right.name);
      return nameOrder || String(left.severity || "").localeCompare(String(right.severity || ""));
    });
  }

  function compactScreening(value) {
    if (!value || typeof value !== "object") return null;
    const result = {};
    const risk = finiteNumber(value.risk_score);
    if (risk !== null) result.risk_score = risk;
    if (typeof value.needs_review === "boolean") result.needs_review = value.needs_review;
    if (typeof value.high_risk === "boolean") result.high_risk = value.high_risk;
    if (value.severity_counts && typeof value.severity_counts === "object") {
      const counts = {};
      ["low", "medium", "high"].forEach((severity) => {
        const count = value.severity_counts[severity];
        if (Number.isInteger(count) && count >= 0) counts[severity] = count;
      });
      if (Object.keys(counts).length) result.severity_counts = counts;
    }
    const flags = compactScreeningFlags(value.flags);
    if (flags.length) result.flags = flags;
    return Object.keys(result).length ? result : null;
  }

  function indexEntry(row, shard = null) {
    const entry = {
      id: String(row.id),
      category: roundCategory(row),
      shard,
    };
    const analysis = compactAnalysis(row.analysis);
    const screening = compactScreening(row.screening);
    if (analysis) entry.analysis = analysis;
    if (screening) entry.screening = screening;
    return entry;
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
      this.reviewImageDelivery = normalizeReviewImageDelivery(this.payload.asset_delivery?.review_images);
      this.roundMap = new Map(this.payload.rounds.map((round) => [String(round.id), round]));
      this.index = this.payload.rounds.map((round) => indexEntry(round, null));
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
        return applyReviewImageDelivery(round, this.reviewImageDelivery);
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
      this.index = manifest.index.map((row) => indexEntry(row, String(row.shard)));
      this.roundCount = Number(manifest.round_count) || this.index.length;
      this.signature = String(manifest.dataset_signature);
      this.reviewImageDelivery = normalizeReviewImageDelivery(manifest.asset_delivery?.review_images);
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
        return new Map(payload.rounds.map((round) => {
          const delivered = applyReviewImageDelivery(round, this.reviewImageDelivery);
          return [String(delivered.id), delivered];
        }));
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
    applyReviewImageDelivery,
    compactAnalysis,
    compactScreening,
    compactScreeningFlags,
    indexEntry,
    manifestLooksValid,
    normalizeInlinePayload,
    normalizeReviewImageDelivery,
    open,
    resolveRelativeSource,
    resolveReviewImage,
    roundCategory,
  };
});
