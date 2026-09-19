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

function shardIdsFromRequests(requests) {
  return new Set([...requests].map((url) => {
    const match = url.match(/\/data\/shards\/rounds-(\d+)\.json(?:[?#]|$)/);
    return match?.[1] || null;
  }).filter(Boolean));
}

function assertRequestedOnly(requests, expectedShardIds, message) {
  assert.deepStrictEqual(
    [...shardIdsFromRequests(requests)].sort(),
    [...expectedShardIds].sort(),
    message,
  );
}

function curatorPriorityOrder(entries) {
  const original = new Map(manifest.index.map((entry, index) => [entry.id, index]));
  return [...entries].sort((left, right) => {
    const leftValue = left.analysis?.curation_priority ?? -1;
    const rightValue = right.analysis?.curation_priority ?? -1;
    if (rightValue !== leftValue) return rightValue - leftValue;
    return original.get(left.id) - original.get(right.id);
  });
}

function hasSignal(entry, name) {
  return (entry.screening?.flags || []).some((flag) => flag.name === name);
}

async function waitForPlayableGame(page) {
  await page.waitForSelector("#gameContent:not([hidden])");
  await page.waitForFunction(() => {
    const image = document.querySelector("#reviewImage");
    return image && image.complete && image.naturalWidth > 0;
  });
}

async function waitForCuratorRound(page, roundId) {
  await page.waitForFunction(
    (expected) => {
      const content = document.querySelector("#content");
      const id = document.querySelector("#roundId");
      const image = document.querySelector("#reviewImage");
      return content && !content.hidden
        && id?.textContent === expected
        && image && image.complete && image.naturalWidth > 0;
    },
    roundId,
  );
}

async function readCuratorDecisions(page) {
  return page.evaluate((signature) => {
    const raw = localStorage.getItem(`mystery-cart-curation:${signature}`);
    return raw ? JSON.parse(raw).decisions : {};
  }, manifest.dataset_signature);
}

async function acceptNextDialog(page) {
  page.once("dialog", async (dialog) => dialog.accept());
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

    {
      const context = await browser.newContext();
      const page = await context.newPage();
      const shardRequests = trackShardRequests(page);
      await page.addInitScript(() => localStorage.clear());

      const ordered = curatorPriorityOrder(manifest.index);
      const first = ordered[0];
      await page.goto(`${BASE_URL}/curate.html`, { waitUntil: "domcontentloaded" });
      await waitForCuratorRound(page, first.id);

      const note = await page.locator("#datasetNote").textContent();
      assert.match(note, /40 rounds/);
      assert.match(note, /40 scored/);
      assert.match(note, /40 screened/);
      assert.match(note, /lazy sharded/);
      assertRequestedOnly(
        shardRequests,
        new Set([first.shard]),
        "curator startup should fetch only the shard containing the displayed round",
      );

      const highEntries = curatorPriorityOrder(manifest.index.filter((entry) => entry.screening?.high_risk));
      assert.ok(highEntries.length >= 2, "fixture should include multiple high-risk curator rows");
      const firstHigh = highEntries[0];
      await page.selectOption("#screeningSelect", "high");
      await waitForCuratorRound(page, firstHigh.id);
      assert.strictEqual(await page.locator("#screeningStatus").textContent(), "High risk");
      assert.match(await page.locator("#screeningFlags").textContent(), /fixture high risk/i);

      const expectedAfterFilter = new Set([first.shard, firstHigh.shard]);
      assertRequestedOnly(
        shardRequests,
        expectedAfterFilter,
        "screening filter should select from manifest summaries without preloading unrelated shards",
      );

      const secondHigh = highEntries[1];
      await page.click("#nextButton");
      await waitForCuratorRound(page, secondHigh.id);
      const expectedAfterNext = new Set([first.shard, firstHigh.shard, secondHigh.shard]);
      assertRequestedOnly(
        shardRequests,
        expectedAfterNext,
        "curator navigation should fetch only the newly displayed round's shard",
      );
      assert.ok(shardRequests.size < manifest.shards.length, "curator should not bulk-load every shard");

      await page.selectOption("#screeningSelect", "clear");
      const clearFirst = curatorPriorityOrder(manifest.index.filter((entry) => entry.screening?.needs_review === false))[0];
      await waitForCuratorRound(page, clearFirst.id);
      assert.strictEqual(await page.locator("#screeningStatus").textContent(), "Clear");
      await context.close();
    }

    {
      const context = await browser.newContext();
      const page = await context.newPage();
      const shardRequests = trackShardRequests(page);
      await page.addInitScript(() => localStorage.clear());

      const ordered = curatorPriorityOrder(manifest.index);
      const first = ordered[0];
      await page.goto(`${BASE_URL}/curate.html`, { waitUntil: "domcontentloaded" });
      await waitForCuratorRound(page, first.id);

      const faceEntries = curatorPriorityOrder(manifest.index.filter((entry) => hasSignal(entry, "person_face_detected")));
      assert.ok(faceEntries.length >= 2, "fixture should expose face signal rows in compact manifest summaries");
      assert.ok(
        await page.locator('#signalSelect option[value="person_face_detected"]').count(),
        "face signal queue should be offered without loading every shard",
      );
      await page.selectOption("#signalSelect", "person_face_detected");
      await waitForCuratorRound(page, faceEntries[0].id);
      assert.match(await page.locator("#screeningFlags").textContent(), /person face detected/i);
      assertRequestedOnly(
        shardRequests,
        new Set([first.shard, faceEntries[0].shard]),
        "signal queue filter should not preload unrelated shards",
      );

      const highEntries = curatorPriorityOrder(manifest.index.filter((entry) => entry.screening?.high_risk));
      await page.selectOption("#signalSelect", "all");
      await page.selectOption("#screeningSelect", "high");
      await waitForCuratorRound(page, highEntries[0].id);
      await page.click("#keepButton");

      const expectedRejectCount = highEntries.length - 1;
      assert.strictEqual(
        Number((await page.locator("#rejectHighCount").textContent()).replaceAll(",", "")),
        expectedRejectCount,
      );
      await acceptNextDialog(page);
      await page.click("#rejectHighButton");

      let decisions = await readCuratorDecisions(page);
      assert.strictEqual(decisions[highEntries[0].id], "keep", "bulk reject must preserve manual keep");
      highEntries.slice(1).forEach((entry) => assert.strictEqual(decisions[entry.id], "reject"));
      assert.match(await page.locator("#bulkStatus").textContent(), /bulk action applied/i);

      await page.click("#undoBulkButton");
      decisions = await readCuratorDecisions(page);
      assert.strictEqual(decisions[highEntries[0].id], "keep", "undo must preserve earlier manual decision");
      highEntries.slice(1).forEach((entry) => assert.strictEqual(decisions[entry.id], undefined));
      assert.match(await page.locator("#bulkStatus").textContent(), /undid bulk action/i);
      await context.close();
    }

    {
      const context = await browser.newContext();
      const page = await context.newPage();
      await page.addInitScript(() => localStorage.clear());
      await page.goto(`${BASE_URL}/curate.html`, { waitUntil: "domcontentloaded" });
      await page.waitForSelector("#content:not([hidden])");

      const clearLowPriority = manifest.index.filter((entry) => (
        entry.screening?.needs_review === false
        && typeof entry.analysis?.curation_priority === "number"
        && entry.analysis.curation_priority <= 20
      ));
      assert.ok(clearLowPriority.length > 0, "fixture should include conservative auto-keep candidates");
      assert.strictEqual(
        Number((await page.locator("#keepClearCount").textContent()).replaceAll(",", "")),
        clearLowPriority.length,
      );

      await acceptNextDialog(page);
      await page.click("#keepClearButton");
      let decisions = await readCuratorDecisions(page);
      clearLowPriority.forEach((entry) => assert.strictEqual(decisions[entry.id], "keep"));

      await page.click("#undoBulkButton");
      decisions = await readCuratorDecisions(page);
      clearLowPriority.forEach((entry) => assert.strictEqual(decisions[entry.id], undefined));
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
