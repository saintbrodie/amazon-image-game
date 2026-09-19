(function initCuratorActions(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) {
    root.CuratorActions = api;
    root.CuratorState = api.state;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function curatorActionsFactory() {
  function screening(round) {
    const value = round && round.screening;
    return value && typeof value === "object" ? value : null;
  }

  function flags(round) {
    const value = screening(round)?.flags;
    return Array.isArray(value)
      ? value.filter((flag) => flag && typeof flag === "object" && typeof flag.name === "string" && flag.name.trim())
      : [];
  }

  function highRisk(round) {
    const value = screening(round);
    if (!value) return false;
    return value.high_risk === true || flags(round).some((flag) => flag.severity === "high");
  }

  function needsReview(round) {
    const value = screening(round);
    if (!value) return false;
    return value.needs_review === true || flags(round).length > 0;
  }

  function signalNames(rounds) {
    const names = new Set();
    for (const round of rounds || []) {
      for (const flag of flags(round)) names.add(flag.name.trim());
    }
    return [...names].sort((left, right) => left.localeCompare(right));
  }

  function matchesSignal(round, signal) {
    if (!signal || signal === "all") return true;
    return flags(round).some((flag) => flag.name === signal);
  }

  function priority(round) {
    const value = round?.analysis?.curation_priority;
    return typeof value === "number" && Number.isFinite(value) ? value : null;
  }

  function bulkCandidates(rounds, decisions, action, options = {}) {
    const decisionMap = decisions && typeof decisions === "object" ? decisions : {};
    const maxPriority = Number.isFinite(Number(options.maxPriority)) ? Number(options.maxPriority) : 20;
    return (rounds || []).filter((round) => {
      if (!round?.id || decisionMap[round.id]) return false;
      if (action === "reject-high") return highRisk(round);
      if (action === "keep-clear") {
        const value = screening(round);
        const score = priority(round);
        return Boolean(value) && !needsReview(round) && score !== null && score <= maxPriority;
      }
      return false;
    });
  }

  function applyBulk(decisions, rounds, value) {
    const next = { ...(decisions || {}) };
    const previous = {};
    for (const round of rounds || []) {
      if (!round?.id) continue;
      previous[round.id] = Object.prototype.hasOwnProperty.call(next, round.id) ? next[round.id] : null;
      next[round.id] = value;
    }
    return { next, previous };
  }

  function restoreBulk(decisions, previous) {
    const next = { ...(decisions || {}) };
    for (const [id, value] of Object.entries(previous || {})) {
      if (value === null || value === undefined) delete next[id];
      else next[id] = value;
    }
    return next;
  }

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
    const rawPriority = Number(value.maxPriority);
    const threshold = Math.max(0, Math.min(100, Math.round(Number.isFinite(rawPriority) ? rawPriority : 20)));
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

  const state = {
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

  return {
    applyBulk,
    bulkCandidates,
    flags,
    highRisk,
    matchesSignal,
    needsReview,
    priority,
    restoreBulk,
    signalNames,
    state,
  };
});
