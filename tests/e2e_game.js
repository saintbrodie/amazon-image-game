const assert = require("assert");
const fs = require("fs");
const { chromium } = require("playwright");

const BASE_URL = process.env.E2E_BASE_URL || "http://127.0.0.1:8000";
const DAILY_DATE = "2026-09-18";
const manifest = JSON.parse(fs.readFileSync("data/rounds.manifest.json", "utf8"));

function trackShardRequests(page) {
  const requests = new Set();
  page.on("request", (request) => {
    const url = request.url();
    if (/\/data\/shards\/rounds-\d+\.json(?:[?#]|$)/.test(url)) requests.add(url);
  });
  return requests;
}

async function waitForPlayableGame(page) {
  await page.waitForSelector("#gameContent:not([hidden])");
  await page.waitForFunction(() => {
    const image = document.querySelector("#reviewImage");
    return image && image.complete && image.naturalWidth > 0;
  });
}

(async function run() {
  const browser = await chromium.launch({ headless: true });
  try {
    {
      const context = await browser.newContext();
      const page = await context.newPage();
      const shardRequests = trackShardRequests(page);
      await page.addInitScript(() => {
        localStorage.clear();
        localStorage.setItem("mystery-cart-round-count", "5");
      });
      await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });
      await waitForPlayableGame(page);

      const note = await page.locator("#datasetNote").textContent();
      assert.match(note, /40 playable rounds/);
      assert.match(note, /lazy-loaded shards/);
      assert.strictEqual(await page.locator("#roundStatus").textContent(), "1 / 5");
      assert.ok(shardRequests.size >= 1, "normal game should fetch at least one shard");
      assert.ok(shardRequests.size <= 5, `five selected rounds fetched ${shardRequests.size} shards`);
      assert.ok(
        shardRequests.size < manifest.shards.length,
        `lazy game fetched all ${manifest.shards.length} shards instead of only selected shards`,
      );
      await context.close();
    }

    {
      const context = await browser.newContext();
      const page = await context.newPage();
      const shardRequests = trackShardRequests(page);
      await page.addInitScript(
        ({ signature, date }) => {
          localStorage.clear();
          localStorage.setItem(
            `mystery-cart-daily:${signature}:${date}`,
            JSON.stringify({
              score: 420,
              correct: 4,
              skipped: 0,
              outcomes: ["correct", "wrong", "correct", "correct", "correct"],
            }),
          );
        },
        { signature: manifest.dataset_signature, date: DAILY_DATE },
      );
      await page.goto(`${BASE_URL}/?daily=${DAILY_DATE}`, { waitUntil: "domcontentloaded" });
      await page.waitForSelector("#finishCard:not([hidden])");

      assert.strictEqual(await page.locator("#finishHeadline").textContent(), "Today's result");
      assert.strictEqual(await page.locator("#finishScore").textContent(), "420");
      assert.strictEqual(await page.locator("#resultSquares").textContent(), "🟩🟥🟩🟩🟩");
      assert.strictEqual(
        shardRequests.size,
        0,
        "restoring an already-completed daily result should not download round shards",
      );
      await context.close();
    }

    {
      const context = await browser.newContext();
      const page = await context.newPage();
      const shardRequests = trackShardRequests(page);
      await page.addInitScript(() => localStorage.clear());
      await page.goto(`${BASE_URL}/?daily=${DAILY_DATE}`, { waitUntil: "domcontentloaded" });
      await waitForPlayableGame(page);

      assert.strictEqual(await page.locator("#roundStatus").textContent(), "1 / 5");
      assert.strictEqual(await page.locator("#challengeDate").textContent(), DAILY_DATE);
      assert.ok(shardRequests.size >= 1 && shardRequests.size <= 5);
      assert.ok(shardRequests.size < manifest.shards.length);
      await context.close();
    }

    console.log(
      `browser e2e passed: ${manifest.round_count} rounds across ${manifest.shards.length} shards`,
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
