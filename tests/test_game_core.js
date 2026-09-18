const assert = require("node:assert/strict");
const GameCore = require("../game-core.js");

const rounds = [
  { id: "alpha" },
  { id: "bravo" },
  { id: "charlie" },
  { id: "delta" },
  { id: "echo" },
  { id: "foxtrot" },
];

const first = GameCore.dailyRounds(rounds, "2026-09-18", 5).map((round) => round.id);
const second = GameCore.dailyRounds([...rounds].reverse(), "2026-09-18", 5).map((round) => round.id);
assert.deepEqual(first, second, "daily rounds should not depend on source order");
assert.equal(first.length, 5);

const otherDay = GameCore.dailyRounds(rounds, "2026-09-19", 5).map((round) => round.id);
assert.notDeepEqual(first, otherDay, "a different date should normally produce a different ordering");

const choices = ["One", "Two", "Three", "Four"];
assert.deepEqual(
  GameCore.dailyChoices(choices, "2026-09-18", "alpha"),
  GameCore.dailyChoices([...choices].reverse(), "2026-09-18", "alpha"),
  "daily answer order should not depend on source order",
);

assert.equal(GameCore.utcDateKey(new Date("2026-09-18T23:59:59Z")), "2026-09-18");
assert.equal(GameCore.isDateKey("2026-09-18"), true);
assert.equal(GameCore.isDateKey("2026-02-31"), false);
assert.equal(GameCore.isDateKey("today"), false);

assert.equal(GameCore.resultSquares(["correct", "wrong", "skipped"]), "🟩🟥⬜");
assert.equal(
  GameCore.buildDailyShare({
    dateKey: "2026-09-18",
    correct: 4,
    total: 5,
    score: 480,
    outcomes: ["correct", "wrong", "correct", "correct", "correct"],
    url: "https://example.test/?daily=2026-09-18",
  }),
  "What Did They Buy? Daily 2026-09-18\n4/5 · 480 pts\n🟩🟥🟩🟩🟩\nhttps://example.test/?daily=2026-09-18",
);

console.log("game-core tests passed");
