const assert = require("assert");
const CuratorActions = require("../curate-actions.js");

function round(id, { priority = 20, screening = null } = {}) {
  return {
    id,
    analysis: { curation_priority: priority },
    screening,
  };
}

(function run() {
  const clear = round("clear", {
    priority: 12,
    screening: { risk_score: 0, needs_review: false, high_risk: false, flags: [] },
  });
  const medium = round("medium", {
    priority: 60,
    screening: {
      risk_score: 35,
      needs_review: true,
      high_risk: false,
      flags: [{ name: "person_face_detected", severity: "medium" }],
    },
  });
  const high = round("high", {
    priority: 80,
    screening: {
      risk_score: 90,
      needs_review: true,
      high_risk: true,
      flags: [{ name: "email_address", severity: "high" }],
    },
  });
  const tooHighPriority = round("clear-but-needs-manual", {
    priority: 35,
    screening: { risk_score: 0, needs_review: false, high_risk: false, flags: [] },
  });

  assert.deepStrictEqual(
    CuratorActions.signalNames([high, medium, clear]),
    ["email_address", "person_face_detected"],
  );
  assert.strictEqual(CuratorActions.matchesSignal(medium, "person_face_detected"), true);
  assert.strictEqual(CuratorActions.matchesSignal(medium, "email_address"), false);
  assert.strictEqual(CuratorActions.matchesSignal(clear, "all"), true);

  assert.deepStrictEqual(
    CuratorActions.bulkCandidates([clear, medium, high], {}, "reject-high").map((item) => item.id),
    ["high"],
  );
  assert.deepStrictEqual(
    CuratorActions.bulkCandidates([clear, tooHighPriority, medium], {}, "keep-clear", { maxPriority: 20 })
      .map((item) => item.id),
    ["clear"],
  );
  assert.deepStrictEqual(
    CuratorActions.bulkCandidates([clear, high], { high: "keep" }, "reject-high").map((item) => item.id),
    [],
    "bulk actions must preserve existing manual decisions",
  );

  const applied = CuratorActions.applyBulk({ medium: "keep" }, [clear, high], "reject");
  assert.deepStrictEqual(applied.next, { medium: "keep", clear: "reject", high: "reject" });
  assert.deepStrictEqual(applied.previous, { clear: null, high: null });
  assert.deepStrictEqual(CuratorActions.restoreBulk(applied.next, applied.previous), { medium: "keep" });

  console.log("curate-actions tests passed");
})();
