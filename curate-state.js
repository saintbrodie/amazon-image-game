(function initCuratorState(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.CuratorState = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function curatorStateFactory() {
  function cleanText(value) {
    return typeof value === "string" ? value.trim() : "";
  }

  function normalizeTags(value) {
    const source = Array.isArray(value) ? value : typeof value === "string" ? value.split(",") : [];
    const seen = new Set();
    const result = [];
    for (const item of source) {
      const tag = cleanText(item).replace(/\s+/g, " ");
      if (!tag) continue;
      const key = tag.toLocaleLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      result.push(tag.slice(0, 48));
      if (result.length >= 16) break;
    }
    return result;
  }

  function normalizeAnnotation(value) {
    if (!value || typeof value !== "object") return { note: "", tags: [] };
    return {
      note: cleanText(value.note).slice(0, 4000),
      tags: normalizeTags(value.tags),
    };
  }

  function normalizeAnnotations(value, validIds = null) {
    const result = {};
    if (!value || typeof value !== "object") return result;
    for (const [id, raw] of Object.entries(value)) {
      if (!id || (validIds && !validIds.has(id))) continue;
      const annotation = normalizeAnnotation(raw);
      if (annotation.note || annotation.tags.length) result[id] = annotation;
    }
    return result;
  }

  function allTags(annotations) {
    const labels = new Map();
    for (const annotation of Object.values(annotations || {})) {
      for (const tag of normalizeTags(annotation?.tags)) {
        const key = tag.toLocaleLowerCase();
        if (!labels.has(key)) labels.set(key, tag);
      }
    }
    return [...labels.entries()]
      .sort((left, right) => left[1].localeCompare(right[1]))
      .map(([key, label]) => ({ key, label }));
  }

  function hasTag(annotation, tagKey) {
    if (!tagKey || tagKey === "all") return true;
    return normalizeTags(annotation?.tags).some((tag) => tag.toLocaleLowerCase() === tagKey);
  }

  function presetKey(name) {
    return cleanText(name).toLocaleLowerCase();
  }

  function normalizePreset(value) {
    if (!value || typeof value !== "object") return null;
    const name = cleanText(value.name).slice(0, 60);
    if (!name) return null;
    const numericPriority = Number(value.maxPriority);
    const threshold = Number.isFinite(numericPriority)
      ? Math.max(0, Math.min(100, Math.round(numericPriority)))
      : 20;
    return {
      name,
      category: cleanText(value.category) || "all",
      status: cleanText(value.status) || "undecided",
      screening: cleanText(value.screening) || "all",
      signal: cleanText(value.signal) || "all",
      tag: cleanText(value.tag) || "all",
      sort: cleanText(value.sort) || "priority",
      maxPriority: threshold,
    };
  }

  function normalizePresets(value) {
    const result = [];
    const seen = new Set();
    if (!Array.isArray(value)) return result;
    for (const raw of value) {
      const preset = normalizePreset(raw);
      if (!preset) continue;
      const key = presetKey(preset.name);
      if (seen.has(key)) continue;
      seen.add(key);
      result.push(preset);
      if (result.length >= 30) break;
    }
    return result.sort((left, right) => left.name.localeCompare(right.name));
  }

  function upsertPreset(presets, rawPreset) {
    const preset = normalizePreset(rawPreset);
    if (!preset) return normalizePresets(presets);
    const key = presetKey(preset.name);
    const next = normalizePresets(presets).filter((item) => presetKey(item.name) !== key);
    next.push(preset);
    return normalizePresets(next);
  }

  function deletePreset(presets, name) {
    const key = presetKey(name);
    return normalizePresets(presets).filter((item) => presetKey(item.name) !== key);
  }

  return {
    allTags,
    deletePreset,
    hasTag,
    normalizeAnnotation,
    normalizeAnnotations,
    normalizePreset,
    normalizePresets,
    normalizeTags,
    presetKey,
    upsertPreset,
  };
});
