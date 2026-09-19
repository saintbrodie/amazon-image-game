(function initCuratorScreening(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.CuratorScreening = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function curatorScreeningFactory() {
  function screening(round) {
    const value = round && round.screening;
    return value && typeof value === "object" ? value : null;
  }

  function riskScore(round) {
    const value = screening(round)?.risk_score;
    return typeof value === "number" && Number.isFinite(value) ? value : null;
  }

  function flags(round) {
    const value = screening(round)?.flags;
    return Array.isArray(value)
      ? value.filter((flag) => flag && typeof flag === "object" && typeof flag.name === "string")
      : [];
  }

  function needsReview(round) {
    const value = screening(round);
    if (!value) return false;
    return value.needs_review === true || flags(round).length > 0;
  }

  function highRisk(round) {
    const value = screening(round);
    if (!value) return false;
    return value.high_risk === true || flags(round).some((flag) => flag.severity === "high");
  }

  function matches(round, filter) {
    if (filter === "review") return needsReview(round);
    if (filter === "high") return highRisk(round);
    if (filter === "clear") return Boolean(screening(round)) && !needsReview(round);
    if (filter === "unscreened") return !screening(round);
    return true;
  }

  function statusLabel(round) {
    if (!screening(round)) return "Not screened";
    if (highRisk(round)) return "High risk";
    if (needsReview(round)) return "Review suggested";
    return "Clear";
  }

  function severityRank(value) {
    if (value === "high") return 3;
    if (value === "medium") return 2;
    if (value === "low") return 1;
    return 0;
  }

  function sortedFlags(round) {
    return [...flags(round)].sort((left, right) => {
      const severity = severityRank(right.severity) - severityRank(left.severity);
      if (severity) return severity;
      return String(left.name).localeCompare(String(right.name));
    });
  }

  return {
    flags,
    highRisk,
    matches,
    needsReview,
    riskScore,
    screening,
    sortedFlags,
    statusLabel,
  };
});
