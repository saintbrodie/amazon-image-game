(function initCuratorActions(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.CuratorActions = api;
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
  };
});
