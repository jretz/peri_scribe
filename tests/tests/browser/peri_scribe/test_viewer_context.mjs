import assert from "node:assert/strict";

import { expect, test } from "@playwright/test";

import { installViewerClock, openedAt } from "../../../helpers/browser/updates.mjs";

const address = "https://viewer.test/context-reset";

/** Identify the Chromium tab across Playwright's case boundary. */
async function tabIdentity(context, page) {
  const connection = await context.newCDPSession(page);
  try {
    return (await connection.send("Target.getTargetInfo")).targetInfo.targetId;
  } finally {
    await connection.detach();
  }
}

test.use({ reuseContext: true });

test.describe("viewer context reset", () => {
  test.describe.configure({ mode: "serial" });
  let original;
  let routeCalls = 0;

  test("exercises the state each viewer case can change", async ({ context, page }) => {
    original = {
      tab: await tabIdentity(context, page),
      viewport: page.viewportSize(),
      reducedMotion: await page.evaluate(() =>
        matchMedia("(prefers-reduced-motion: reduce)").matches)
    };
    await context.route(address, route => {
      routeCalls += 1;
      return route.fulfill({
        contentType: "text/html",
        body: "<input aria-label='Search'><button>Submit</button>"
      });
    });
    await context.route("https://viewer.test/favicon.ico",
      route => route.fulfill({ status: 204 }));
    await installViewerClock(page);
    await page.setViewportSize({ width: 320, height: 740 });
    await page.emulateMedia({
      reducedMotion: original.reducedMotion ? "no-preference" : "reduce"
    });
    await page.goto(address);
    await page.getByRole("textbox").focus();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("button")).toBeFocused();
    await page.evaluate(() => { globalThis.viewerTestState = true; });
    await page.clock.fastForward(30_000);
    assert.deepEqual(await page.evaluate(() => [
      Date.now(), matchMedia("(prefers-reduced-motion: reduce)").matches,
      innerWidth, innerHeight, globalThis.viewerTestState
    ]), [openedAt.getTime() + 30_000, !original.reducedMotion, 320, 740, true]);
  });

  test("clears the previous case's state on the same tab", async ({ context, page }) => {
    assert.ok(original, "Run both viewer context reset cases together");
    assert.equal(await tabIdentity(context, page), original.tab);
    assert.equal(page.url(), "about:blank");
    assert.deepEqual(await page.evaluate(() => [
      matchMedia("(prefers-reduced-motion: reduce)").matches, innerWidth, innerHeight,
      globalThis.viewerTestState, document.activeElement === document.body,
      document.querySelector("input, button")
    ]), [original.reducedMotion, original.viewport.width, original.viewport.height,
      undefined, true, null]);
    const before = Date.now();
    const browserNow = await page.evaluate(() => Date.now());
    assert.ok(before - 1_000 <= browserNow && browserNow <= Date.now() + 1_000);

    // Offline navigation distinguishes a missing route from an old fixture response.
    await context.setOffline(true);
    try {
      await assert.rejects(page.goto(address), /ERR_INTERNET_DISCONNECTED/);
      assert.equal(routeCalls, 1, "The prior context route survived reset");
    } finally {
      await context.setOffline(false);
    }
  });
});
