(function initGameCore(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.GameCore = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function gameCoreFactory() {
  function hashString(value) {
    let hash = 2166136261;
    const text = String(value);
    for (let index = 0; index < text.length; index += 1) {
      hash ^= text.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
  }

  function stableRank(items, seed, keyFn) {
    return [...items]
      .map((item, index) => ({
        item,
        index,
        rank: hashString(`${seed}|${keyFn(item)}`),
      }))
      .sort((left, right) => left.rank - right.rank || left.index - right.index)
      .map((entry) => entry.item);
  }

  function dailyRounds(rounds, dateKey, count = 5) {
    return stableRank(rounds, `daily:${dateKey}`, (round) => round.id).slice(0, Math.max(0, count));
  }

  function dailyChoices(choices, dateKey, roundId) {
    return stableRank(choices, `choices:${dateKey}:${roundId}`, (choice) => choice);
  }

  function utcDateKey(date = new Date()) {
    return date.toISOString().slice(0, 10);
  }

  function isDateKey(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value))) return false;
    const parsed = new Date(`${value}T00:00:00Z`);
    return !Number.isNaN(parsed.getTime()) && utcDateKey(parsed) === value;
  }

  function resultSquares(outcomes) {
    return outcomes.map((outcome) => {
      if (outcome === "correct") return "🟩";
      if (outcome === "wrong") return "🟥";
      return "⬜";
    }).join("");
  }

  function buildDailyShare({ dateKey, correct, total, score, outcomes, url }) {
    const lines = [
      `What Did They Buy? Daily ${dateKey}`,
      `${correct}/${total} · ${score} pts`,
      resultSquares(outcomes),
    ];
    if (url) lines.push(url);
    return lines.join("\n");
  }

  return {
    buildDailyShare,
    dailyChoices,
    dailyRounds,
    hashString,
    isDateKey,
    resultSquares,
    stableRank,
    utcDateKey,
  };
});
