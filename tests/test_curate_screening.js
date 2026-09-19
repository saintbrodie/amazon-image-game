const assert = require("assert");
const Screening = require("../curate-screening.js");

const clear = { screening: { risk_score: 0, needs_review: false, high_risk: false, flags: [] } };
const face = {
  screening: {
    risk_score: 20,
    needs_review: true,
    high_risk: false,
    flags: [{ name: "person_face_detected", severity: "medium", source: "image" }],
  },
};
const high = {
  screening: {
    risk_score: 70,
    needs_review: true,
    high_risk: true,
    flags: [
      { name: "social_handle", severity: "medium", source: "review_text" },
      { name: "contact_email", severity: "high", source: "review_text" },
    ],
  },
};
const unscreened = {};

assert.equal(Screening.statusLabel(clear), "Clear");
assert.equal(Screening.statusLabel(face), "Review suggested");
assert.equal(Screening.statusLabel(high), "High risk");
assert.equal(Screening.statusLabel(unscreened), "Not screened");

assert.equal(Screening.matches(face, "review"), true);
assert.equal(Screening.matches(clear, "review"), false);
assert.equal(Screening.matches(high, "high"), true);
assert.equal(Screening.matches(face, "high"), false);
assert.equal(Screening.matches(clear, "clear"), true);
assert.equal(Screening.matches(unscreened, "clear"), false);
assert.equal(Screening.matches(unscreened, "unscreened"), true);
assert.equal(Screening.matches(face, "all"), true);

assert.equal(Screening.riskScore(face), 20);
assert.equal(Screening.riskScore(unscreened), null);
assert.deepEqual(
  Screening.sortedFlags(high).map((flag) => flag.name),
  ["contact_email", "social_handle"],
);

console.log("curator screening helpers: OK");
