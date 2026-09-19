const assert = require("assert");
const CuratorState = require("../curate-state.js");

(function run() {
  assert.deepStrictEqual(
    CuratorState.normalizeTags(" Funny, needs check, funny ,  "),
    ["Funny", "needs check"],
  );

  assert.deepStrictEqual(
    CuratorState.normalizeAnnotation({ note: "  check product title  ", tags: ["Odd", "odd", "Face"] }),
    { note: "check product title", tags: ["Odd", "Face"] },
  );

  const validIds = new Set(["a", "b"]);
  assert.deepStrictEqual(
    CuratorState.normalizeAnnotations({
      a: { note: "good", tags: ["Funny"] },
      b: { note: "", tags: [] },
      c: { note: "wrong dataset", tags: ["Skip"] },
    }, validIds),
    { a: { note: "good", tags: ["Funny"] } },
  );

  const annotations = {
    a: { note: "", tags: ["Funny", "Face"] },
    b: { note: "", tags: ["funny", "Needs Check"] },
  };
  assert.deepStrictEqual(CuratorState.allTags(annotations), [
    { key: "face", label: "Face" },
    { key: "funny", label: "Funny" },
    { key: "needs check", label: "Needs Check" },
  ]);
  assert.strictEqual(CuratorState.hasTag(annotations.a, "face"), true);
  assert.strictEqual(CuratorState.hasTag(annotations.b, "face"), false);
  assert.strictEqual(CuratorState.hasTag(null, "all"), true);

  const preset = CuratorState.normalizePreset({
    name: " Faces ",
    category: "Beauty",
    status: "undecided",
    screening: "review",
    signal: "person_face_detected",
    tag: "funny",
    sort: "screening",
    maxPriority: 150,
  });
  assert.deepStrictEqual(preset, {
    name: "Faces",
    category: "Beauty",
    status: "undecided",
    screening: "review",
    signal: "person_face_detected",
    tag: "funny",
    sort: "screening",
    maxPriority: 100,
  });
  assert.strictEqual(CuratorState.normalizePreset({ name: "Zero", maxPriority: 0 }).maxPriority, 0);

  let presets = CuratorState.upsertPreset([], preset);
  presets = CuratorState.upsertPreset(presets, { ...preset, name: "faces", sort: "priority" });
  assert.strictEqual(presets.length, 1, "preset names should be case-insensitively unique");
  assert.strictEqual(presets[0].sort, "priority");
  presets = CuratorState.upsertPreset(presets, { name: "High Risk", screening: "high" });
  assert.deepStrictEqual(presets.map((item) => item.name), ["faces", "High Risk"]);
  presets = CuratorState.deletePreset(presets, "FACES");
  assert.deepStrictEqual(presets.map((item) => item.name), ["High Risk"]);

  console.log("curate-state tests passed");
})();
