const assert = require("assert");
const fs = require("fs");
const { chromium } = require("playwright");

const BASE_URL = process.env.E2E_BASE_URL || "http://127.0.0.1:8000";
const manifest = JSON.parse(fs.readFileSync("data/rounds.manifest.json", "utf8"));

async function waitForCurator(page) {
  await page.waitForSelector("#content:not([hidden])");
  await page.waitForFunction(() => {
    const image = document.querySelector("#reviewImage");
    return image && image.complete && image.naturalWidth > 0;
  });
}

async function workspace(page) {
  return page.evaluate((signature) => {
    const raw = localStorage.getItem(`mystery-cart-curation:${signature}`);
    return raw ? JSON.parse(raw) : null;
  }, manifest.dataset_signature);
}

(async function run() {
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.addInitScript(() => localStorage.clear());
    await page.goto(`${BASE_URL}/curate.html`, { waitUntil: "domcontentloaded" });
    await waitForCurator(page);

    const firstId = await page.locator("#roundId").textContent();
    assert.ok(firstId, "curator should expose the displayed round ID");

    await page.locator("#tagsInput").fill("Funny, Needs Check");
    await page.locator("#tagsInput").blur();
    await page.locator("#noteInput").fill("Great image, double-check the product title.");
    await page.locator("#noteInput").blur();

    await page.waitForFunction(
      ({ signature, roundId }) => {
        const raw = localStorage.getItem(`mystery-cart-curation:${signature}`);
        if (!raw) return false;
        const parsed = JSON.parse(raw);
        return parsed.annotations?.[roundId]?.tags?.includes("Funny")
          && parsed.annotations?.[roundId]?.note?.includes("double-check");
      },
      { signature: manifest.dataset_signature, roundId: firstId },
    );

    assert.ok(
      await page.locator('#tagSelect option[value="funny"]').count(),
      "saved tags should immediately become curator queue filters",
    );
    await page.selectOption("#tagSelect", "funny");
    await page.waitForFunction((roundId) => document.querySelector("#roundId")?.textContent === roundId, firstId);

    await page.locator("#bulkPriorityInput").fill("0");
    page.once("dialog", async (dialog) => {
      assert.strictEqual(dialog.type(), "prompt");
      await dialog.accept("Funny queue");
    });
    await page.click("#savePresetButton");
    await page.waitForSelector('#presetSelect option[value="funny queue"]', { state: "attached" });

    let stored = await workspace(page);
    assert.strictEqual(stored.presets.length, 1);
    assert.strictEqual(stored.presets[0].tag, "funny");
    assert.strictEqual(stored.presets[0].maxPriority, 0, "queue presets must preserve an explicit zero threshold");

    await page.selectOption("#tagSelect", "all");
    await page.locator("#bulkPriorityInput").fill("20");
    await page.selectOption("#presetSelect", "funny queue");
    await page.click("#applyPresetButton");
    assert.strictEqual(await page.locator("#tagSelect").inputValue(), "funny");
    assert.strictEqual(await page.locator("#bulkPriorityInput").inputValue(), "0");

    const actionsPayload = await page.evaluate(() => actionsDecisionPayload());
    assert.strictEqual(actionsPayload.version, 1);
    assert.ok(!Object.prototype.hasOwnProperty.call(actionsPayload, "annotations"));
    assert.ok(!Object.prototype.hasOwnProperty.call(actionsPayload, "queue_presets"));

    const downloadPromise = page.waitForEvent("download");
    await page.click("#exportButton");
    const download = await downloadPromise;
    const downloadPath = await download.path();
    assert.ok(downloadPath, "workspace export should produce a download");
    const exported = JSON.parse(fs.readFileSync(downloadPath, "utf8"));
    assert.strictEqual(exported.version, 2);
    assert.deepStrictEqual(exported.annotations[firstId].tags, ["Funny", "Needs Check"]);
    assert.match(exported.annotations[firstId].note, /double-check/);
    assert.strictEqual(exported.queue_presets[0].name, "Funny queue");
    assert.strictEqual(exported.queue_presets[0].maxPriority, 0);

    await page.reload({ waitUntil: "domcontentloaded" });
    await waitForCurator(page);
    assert.strictEqual(await page.locator("#roundId").textContent(), firstId);
    assert.strictEqual(await page.locator("#tagsInput").inputValue(), "Funny, Needs Check");
    assert.match(await page.locator("#noteInput").inputValue(), /double-check/);
    assert.ok(await page.locator('#presetSelect option[value="funny queue"]').count());

    stored = await workspace(page);
    assert.strictEqual(stored.annotations[firstId].note, "Great image, double-check the product title.");

    await context.close();
    console.log("curator productivity e2e passed");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
