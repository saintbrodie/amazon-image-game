const assert = require("assert");
const fs = require("fs");
const { chromium } = require("playwright");

const BASE_URL = process.env.E2E_BASE_URL || "http://127.0.0.1:8000";
const manifest = JSON.parse(fs.readFileSync("data/rounds.manifest.json", "utf8"));
const signature = manifest.dataset_signature;

async function waitForCurator(page) {
  await page.waitForSelector("#content:not([hidden])");
  await page.waitForFunction(() => {
    const image = document.querySelector("#reviewImage");
    return image && image.complete && image.naturalWidth > 0;
  });
}

async function openShared(context, actor) {
  const page = await context.newPage();
  await page.goto(`${BASE_URL}/curate.html?shared=1&actor=${encodeURIComponent(actor)}`, {
    waitUntil: "domcontentloaded",
  });
  await waitForCurator(page);
  await page.waitForFunction(() => document.querySelector("#sharedStatus")?.textContent.includes("Shared"));
  return page;
}

async function serverWorkspace() {
  const response = await fetch(`${BASE_URL}/api/workspaces/${encodeURIComponent(signature)}`, { cache: "no-store" });
  assert.ok(response.ok, `shared workspace GET failed with ${response.status}`);
  return response.json();
}

async function waitForRevision(page, revision) {
  await page.waitForFunction(
    (target) => document.querySelector("#sharedStatus")?.textContent.includes(`r${target}`),
    revision,
    { timeout: 15000 },
  );
}

async function resolveVisibleConflict(page, selector) {
  await page.waitForSelector("#sharedConflictBox:not([hidden])", { timeout: 15000 });
  page.once("dialog", (dialog) => dialog.accept());
  await page.click(selector);
  await page.waitForFunction(
    () => document.querySelector("#sharedConflictBox")?.hidden === true,
    null,
    { timeout: 15000 },
  );
}

(async function run() {
  const browser = await chromium.launch({ headless: true });
  try {
    const aliceContext = await browser.newContext();
    const bobContext = await browser.newContext();
    const alice = await openShared(aliceContext, "Alice");
    const bob = await openShared(bobContext, "Bob");

    // Disjoint edits from revision zero must merge automatically.
    const firstId = await alice.locator("#roundId").textContent();
    await alice.click("#keepButton");
    await waitForRevision(alice, 1);

    await bob.click("#nextButton");
    const secondId = await bob.locator("#roundId").textContent();
    assert.notStrictEqual(secondId, firstId);
    await bob.click("#rejectButton");
    await waitForRevision(bob, 2);
    await waitForRevision(alice, 2);

    let remote = await serverWorkspace();
    assert.strictEqual(remote.workspace.decisions[firstId], "keep");
    assert.strictEqual(remote.workspace.decisions[secondId], "reject");
    assert.strictEqual(remote.revision, 2);

    // Both curators are now at revision two and should see the same first
    // undecided round. Make opposite decisions before the debounce fires.
    const conflictOneIdAlice = await alice.locator("#roundId").textContent();
    const conflictOneIdBob = await bob.locator("#roundId").textContent();
    assert.strictEqual(conflictOneIdAlice, conflictOneIdBob);
    await Promise.all([
      alice.click("#keepButton"),
      bob.click("#rejectButton"),
    ]);

    // Exactly one side should lose the optimistic race and show a conflict.
    await Promise.race([
      alice.waitForSelector("#sharedConflictBox:not([hidden])", { timeout: 15000 }),
      bob.waitForSelector("#sharedConflictBox:not([hidden])", { timeout: 15000 }),
    ]);
    const aliceConflict = await alice.locator("#sharedConflictBox").isVisible();
    const conflictPage = aliceConflict ? alice : bob;
    const winnerPage = aliceConflict ? bob : alice;
    const conflictingLocalValue = aliceConflict ? "keep" : "reject";

    // First conflict: explicitly preserve the losing curator's local edit.
    await resolveVisibleConflict(conflictPage, "#sharedPreferMineButton");
    remote = await serverWorkspace();
    assert.strictEqual(remote.workspace.decisions[conflictOneIdAlice], conflictingLocalValue);
    assert.strictEqual(remote.revision, 4);
    await waitForRevision(winnerPage, 4);

    // Create a second collision and resolve it in favor of the already-shared
    // winner, exercising the opposite conflict path.
    const conflictTwoIdAlice = await alice.locator("#roundId").textContent();
    const conflictTwoIdBob = await bob.locator("#roundId").textContent();
    assert.strictEqual(conflictTwoIdAlice, conflictTwoIdBob);
    await Promise.all([
      alice.click("#keepButton"),
      bob.click("#rejectButton"),
    ]);
    await Promise.race([
      alice.waitForSelector("#sharedConflictBox:not([hidden])", { timeout: 15000 }),
      bob.waitForSelector("#sharedConflictBox:not([hidden])", { timeout: 15000 }),
    ]);
    const secondAliceConflict = await alice.locator("#sharedConflictBox").isVisible();
    const secondConflictPage = secondAliceConflict ? alice : bob;
    const secondWinnerPage = secondAliceConflict ? bob : alice;
    const winnerValue = secondAliceConflict ? "reject" : "keep";
    await resolveVisibleConflict(secondConflictPage, "#sharedPreferSharedButton");

    remote = await serverWorkspace();
    assert.strictEqual(remote.workspace.decisions[conflictTwoIdAlice], winnerValue);
    assert.strictEqual(remote.revision, 6);
    await waitForRevision(secondWinnerPage, 6);
    await waitForRevision(secondConflictPage, 6);

    const history = await fetch(`${BASE_URL}/api/workspaces/${encodeURIComponent(signature)}/history`).then((r) => r.json());
    assert.ok(history.history.some((row) => row.updated_by === "Alice"));
    assert.ok(history.history.some((row) => row.updated_by === "Bob"));
    assert.match(await alice.locator("#sharedActivity").textContent(), /Alice|Bob/);

    await aliceContext.close();
    await bobContext.close();
    console.log("shared curator workspace e2e passed");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
