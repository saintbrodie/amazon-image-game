const assert = require("assert");
const DatasetLoader = require("../dataset-loader.js");

function response(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() { return payload; },
  };
}

function fakeFetch(routes, calls) {
  return async (source) => {
    calls.push(source);
    const route = routes[source];
    if (!route) return response(null, 404);
    if (route instanceof Error) throw route;
    return response(route.payload, route.status || 200);
  };
}

function round(id, category = "Beauty") {
  return {
    id,
    source_category: category,
    review_image: `https://example.test/${id}.jpg`,
    product: { title: `Product ${id}`, category },
    choices: [`Product ${id}`, "Wrong A", "Wrong B", "Wrong C"],
  };
}

(async function run() {
  {
    assert.strictEqual(
      DatasetLoader.resolveRelativeSource("shards/rounds-0001.json", "data/rounds.manifest.json"),
      "data/shards/rounds-0001.json",
    );
    assert.strictEqual(
      DatasetLoader.resolveRelativeSource(
        "shards/rounds-0001.json",
        "https://example.test/game/data/rounds.manifest.json",
      ),
      "https://example.test/game/data/shards/rounds-0001.json",
    );
  }

  {
    const delivery = DatasetLoader.normalizeReviewImageDelivery({
      path_prefix: "assets/review-cache/",
      base_url: "https://cdn.example.test/game-images/",
    });
    assert.deepStrictEqual(delivery, {
      path_prefix: "assets/review-cache/",
      base_url: "https://cdn.example.test/game-images/",
    });
    assert.strictEqual(
      DatasetLoader.resolveReviewImage("assets/review-cache/abc.jpg", delivery),
      "https://cdn.example.test/game-images/abc.jpg",
    );
    assert.strictEqual(
      DatasetLoader.resolveReviewImage("https://images.example.test/original.jpg", delivery),
      "https://images.example.test/original.jpg",
    );
    assert.strictEqual(
      DatasetLoader.resolveReviewImage("assets/demo/local.svg", delivery),
      "assets/demo/local.svg",
    );
    assert.strictEqual(
      DatasetLoader.resolveReviewImage("assets/review-cache/../escape.jpg", delivery),
      "assets/review-cache/../escape.jpg",
    );
    assert.strictEqual(
      DatasetLoader.normalizeReviewImageDelivery({
        path_prefix: "../review-cache/",
        base_url: "https://cdn.example.test/",
      }),
      null,
    );
    assert.strictEqual(
      DatasetLoader.normalizeReviewImageDelivery({
        path_prefix: "assets/review-cache/",
        base_url: "javascript:alert(1)",
      }),
      null,
    );
  }

  {
    const calls = [];
    const manifest = {
      version: 1,
      format: "amazon-image-game-sharded-pack",
      dataset_signature: "sig123",
      round_count: 3,
      categories: { Automotive: 1, Beauty: 2 },
      asset_delivery: {
        review_images: {
          path_prefix: "assets/review-cache/",
          base_url: "https://cdn.example.test/reviews/",
        },
      },
      shards: [
        { id: "0001", path: "shards/rounds-0001.json" },
        { id: "0002", path: "shards/rounds-0002.json" },
      ],
      index: [
        {
          id: "r1",
          category: "Beauty",
          shard: "0001",
          analysis: { curation_priority: 33, difficulty_score: 47, ignored: 999 },
          screening: {
            risk_score: 20,
            needs_review: true,
            high_risk: false,
            severity_counts: { medium: 1 },
            flags: [
              { name: "person_face_detected", severity: "medium", source: "drop-source" },
              { name: "person_face_detected", severity: "medium" },
              { name: "social_handle", severity: "low" },
              { name: "", severity: "high" },
            ],
          },
          ignored: "drop me",
        },
        { id: "r2", category: "Automotive", shard: "0002" },
        { id: "r3", category: "Beauty", shard: "0001" },
      ],
    };
    const r1 = round("r1");
    r1.review_image = "assets/review-cache/r1.jpg";
    const routes = {
      "data/rounds.manifest.json": { payload: manifest },
      "data/shards/rounds-0001.json": {
        payload: {
          format: "amazon-image-game-shard",
          dataset_signature: "sig123",
          shard: { id: "0001" },
          rounds: [r1, round("r3")],
        },
      },
      "data/shards/rounds-0002.json": {
        payload: {
          format: "amazon-image-game-shard",
          dataset_signature: "sig123",
          shard: { id: "0002" },
          rounds: [round("r2", "Automotive")],
        },
      },
    };
    const loader = await DatasetLoader.open({ fetchFn: fakeFetch(routes, calls) });
    assert.strictEqual(loader.type, "sharded");
    assert.strictEqual(loader.roundCount, 3);
    assert.strictEqual(loader.signature, "sig123");
    assert.deepStrictEqual(loader.categories(), ["Automotive", "Beauty"]);
    assert.deepStrictEqual(loader.index[0], {
      id: "r1",
      category: "Beauty",
      shard: "0001",
      analysis: { curation_priority: 33, difficulty_score: 47 },
      screening: {
        risk_score: 20,
        needs_review: true,
        high_risk: false,
        severity_counts: { medium: 1 },
        flags: [
          { name: "person_face_detected", severity: "medium" },
          { name: "social_handle", severity: "low" },
        ],
      },
    });

    const selected = [loader.index[2], loader.index[0], loader.index[1]];
    const loaded = await loader.loadEntries(selected);
    assert.deepStrictEqual(loaded.map((item) => item.id), ["r3", "r1", "r2"]);
    assert.strictEqual(loaded[1].review_image, "https://cdn.example.test/reviews/r1.jpg");
    assert.strictEqual(loaded[0].review_image, "https://example.test/r3.jpg");
    assert.strictEqual(calls.filter((value) => value === "data/shards/rounds-0001.json").length, 1);
    assert.strictEqual(calls.filter((value) => value === "data/shards/rounds-0002.json").length, 1);

    await loader.loadEntries([loader.index[0]]);
    assert.strictEqual(calls.filter((value) => value === "data/shards/rounds-0001.json").length, 1);
  }

  {
    const calls = [];
    const inlineRound = round("demo-1");
    inlineRound.review_image = "assets/review-cache/demo-1.webp";
    inlineRound.analysis = { curation_priority: 7, difficulty_score: 12, flags: ["ignored"] };
    inlineRound.screening = {
      risk_score: 50,
      needs_review: true,
      high_risk: true,
      severity_counts: { high: 1 },
      flags: [
        { name: "contact_email", severity: "high", source: "review_text" },
        { name: "contact_email", severity: "high" },
      ],
    };
    const demo = {
      version: 1,
      name: "Demo",
      asset_delivery: {
        review_images: {
          path_prefix: "assets/review-cache/",
          base_url: "https://cdn.example.test/inline/",
        },
      },
      rounds: [inlineRound],
    };
    const routes = {
      "data/rounds.manifest.json": { payload: null, status: 404 },
      "data/rounds.json": { payload: null, status: 404 },
      "data/demo.json": { payload: demo },
    };
    const loader = await DatasetLoader.open({ fetchFn: fakeFetch(routes, calls) });
    assert.strictEqual(loader.type, "inline");
    assert.strictEqual(loader.source, "data/demo.json");
    assert.deepStrictEqual(loader.index[0].analysis, { curation_priority: 7, difficulty_score: 12 });
    assert.deepStrictEqual(loader.index[0].screening, {
      risk_score: 50,
      needs_review: true,
      high_risk: true,
      severity_counts: { high: 1 },
      flags: [{ name: "contact_email", severity: "high" }],
    });
    const loaded = await loader.loadEntries(loader.index);
    assert.deepStrictEqual(loaded.map((item) => item.id), ["demo-1"]);
    assert.strictEqual(loaded[0].review_image, "https://cdn.example.test/inline/demo-1.webp");
  }

  {
    const calls = [];
    const routes = {
      "data/rounds.manifest.json": { payload: { format: "wrong" }, status: 200 },
      "data/demo.json": { payload: { version: 1, rounds: [round("should-not-load")] } },
    };
    await assert.rejects(
      () => DatasetLoader.open({ fetchFn: fakeFetch(routes, calls) }),
      /Invalid sharded dataset manifest/,
    );
    assert.deepStrictEqual(calls, ["data/rounds.manifest.json"]);
  }

  {
    const loader = new DatasetLoader.ShardedDataSource(
      {
        format: "amazon-image-game-sharded-pack",
        dataset_signature: "sig",
        round_count: 1,
        shards: [{ id: "0001", path: "shards/a.json" }],
        index: [{ id: "x", category: "Other", shard: "0001" }],
      },
      "data/rounds.manifest.json",
      async () => response({
        format: "amazon-image-game-shard",
        dataset_signature: "different",
        shard: { id: "0001" },
        rounds: [round("x")],
      }),
    );
    await assert.rejects(() => loader.loadEntries(loader.index), /signature mismatch/i);
  }

  console.log("dataset-loader tests passed");
})();
