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
    const calls = [];
    const manifest = {
      version: 1,
      format: "amazon-image-game-sharded-pack",
      dataset_signature: "sig123",
      round_count: 3,
      categories: { Automotive: 1, Beauty: 2 },
      shards: [
        { id: "0001", path: "shards/rounds-0001.json" },
        { id: "0002", path: "shards/rounds-0002.json" },
      ],
      index: [
        { id: "r1", category: "Beauty", shard: "0001" },
        { id: "r2", category: "Automotive", shard: "0002" },
        { id: "r3", category: "Beauty", shard: "0001" },
      ],
    };
    const routes = {
      "data/rounds.manifest.json": { payload: manifest },
      "data/shards/rounds-0001.json": {
        payload: {
          format: "amazon-image-game-shard",
          dataset_signature: "sig123",
          shard: { id: "0001" },
          rounds: [round("r1"), round("r3")],
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

    const selected = [loader.index[2], loader.index[0], loader.index[1]];
    const loaded = await loader.loadEntries(selected);
    assert.deepStrictEqual(loaded.map((item) => item.id), ["r3", "r1", "r2"]);
    assert.strictEqual(calls.filter((value) => value === "data/shards/rounds-0001.json").length, 1);
    assert.strictEqual(calls.filter((value) => value === "data/shards/rounds-0002.json").length, 1);

    await loader.loadEntries([loader.index[0]]);
    assert.strictEqual(calls.filter((value) => value === "data/shards/rounds-0001.json").length, 1);
  }

  {
    const calls = [];
    const demo = { version: 1, name: "Demo", rounds: [round("demo-1")] };
    const routes = {
      "data/rounds.manifest.json": { payload: null, status: 404 },
      "data/rounds.json": { payload: null, status: 404 },
      "data/demo.json": { payload: demo },
    };
    const loader = await DatasetLoader.open({ fetchFn: fakeFetch(routes, calls) });
    assert.strictEqual(loader.type, "inline");
    assert.strictEqual(loader.source, "data/demo.json");
    assert.deepStrictEqual((await loader.loadEntries(loader.index)).map((item) => item.id), ["demo-1"]);
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
