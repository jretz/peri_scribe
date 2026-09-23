import assert from "node:assert/strict";
import test from "node:test";

import * as viewer from "../../../helpers/doubles/peri_scribe/updates_dom.mjs";

test("startPage leaves the favicon absent when no displayed update is recent",
  async () => {
    const page = await viewer.page([viewer.update("Old", 15),
      viewer.update("Future", -1)]);

    assert.equal(page.favicon(), null);
    assert.equal(page.faviconFrames.length, 0);
    await page.advance(30000);

    assert.equal(page.favicon(), null);
  });

test("startPage pulses a green circle six times and clears at thirty seconds",
  async () => {
    const page = await viewer.page([viewer.update("Timber", 0)]);
    const icon = page.favicon();
    assert.ok(icon, "A displayed recent update should create the favicon");
    assert.equal(icon.rel, "icon");
    assert.equal(icon.type, "image/png");
    assert.match(icon.href, /^data:image\/png;base64,/);
    assert.equal(viewer.faviconImage(page).opacity, 0);

    for (let cycle = 0; cycle < 6; cycle += 1) {
      await page.advance(2500);
      const peak = viewer.faviconImage(page);
      assert.equal(peak.width, 32);
      assert.equal(peak.height, 32);
      assert.equal(peak.opacity, 0.92);
      assert.ok(peak.color[1] > peak.color[0]);
      assert.ok(peak.color[1] > peak.color[2]);
      const [horizontal, vertical, radius, start, end] = peak.fills[0].path[0];
      assert.deepEqual([horizontal, vertical], [16, 16]);
      assert.ok(radius > 0 && radius < 16);
      assert.equal(start, 0);
      assert.equal(end, Math.PI * 2);
      await page.advance(2500);
      assert.equal(viewer.faviconImage(page).opacity, 0);
    }
    const frameCount = page.faviconFrames.length;
    await page.advance(60000);

    assert.equal(page.favicon(), icon);
    assert.equal(page.document.head.querySelectorAll("link").length, 1);
    assert.equal(page.faviconFrames.length, frameCount);
  });

for (const hidden of [false, true]) {
  test(`startPage notifies on new visible updates with the tab hidden=${hidden}`,
    async () => {
      const page = await viewer.page([], { hidden });

      page.replace([viewer.update("Timber", 1)]);
      await page.advance(2500);

      assert.equal(viewer.faviconImage(page).opacity, 0.92);
    });
}

test("startPage does not notify for additions excluded by the current name filter",
  async () => {
    const page = await viewer.page([]);
    page.filter("TIM");
    const iron = viewer.update("Iron", 1);

    page.replace([iron]);

    assert.equal(page.favicon(), null);
    page.replace([iron, viewer.update("Timber", 1)]);
    await page.advance(2500);

    assert.equal(viewer.faviconImage(page).opacity, 0.92);
  });

test("startPage does not notify for additions inside a collapsed window",
  async () => {
    const page = await viewer.page([]);
    page.group(0).querySelector(".group-toggle").click();

    page.replace([viewer.update("Timber", 1)]);
    await page.advance(2500);

    assert.equal(page.favicon(), null);
  });

test("startPage does not notify when filtering or expansion reveals an existing update",
  async () => {
    const page = await viewer.page([]);
    page.filter("Iron");
    page.group(0).querySelector(".group-toggle").click();
    const timber = viewer.update("Timber", 1);
    page.replace([timber]);

    page.filter("");
    page.group(0).querySelector(".group-toggle").click();
    page.replace([structuredClone(timber)]);

    assert.equal(page.favicon(), null);
  });

test("startPage does not notify for old or future additions to a snapshot",
  async () => {
    const page = await viewer.page([]);

    page.replace([viewer.update("Old", 15), viewer.update("Future", -1)]);
    await page.advance(60001);

    assert.ok(page.row("Future"));
    assert.equal(page.favicon(), null);
  });

test("startPage keeps the original notification deadline across unchanged snapshots",
  async () => {
    const timber = viewer.update("Timber", 1);
    const page = await viewer.page([timber]);
    await page.advance(10000);

    page.replace([structuredClone(timber)]);
    await page.advance(20000);

    assert.equal(viewer.faviconImage(page).opacity, 0);
    const frameCount = page.faviconFrames.length;
    await page.advance(2500);
    assert.equal(page.faviconFrames.length, frameCount);
  });

test("startPage keeps the notification deadline across sorting and view changes",
  async () => {
    const page = await viewer.page([viewer.update("Timber", 1)]);
    await page.advance(10000);

    page.group(0).querySelector(".sort-order").click();
    page.filter("missing");
    page.filter("");
    page.group(0).querySelector(".group-toggle").click();
    page.group(0).querySelector(".group-toggle").click();
    await page.advance(20000);

    assert.equal(viewer.faviconImage(page).opacity, 0);
    const frameCount = page.faviconFrames.length;
    await page.advance(2500);
    assert.equal(page.faviconFrames.length, frameCount);
  });

test("startPage restarts the thirty-second notification for another qualifying update",
  async () => {
    const timber = viewer.update("Timber", 1);
    const page = await viewer.page([timber]);
    const icon = page.favicon();
    await page.advance(20000);

    page.replace([timber, viewer.update("Timber", 0, 1200)]);
    await page.advance(12500);

    assert.equal(page.favicon(), icon);
    assert.equal(viewer.faviconImage(page).opacity, 0.92);
    await page.advance(17500);
    assert.equal(viewer.faviconImage(page).opacity, 0);
    const frameCount = page.faviconFrames.length;
    await page.advance(2500);
    assert.equal(page.faviconFrames.length, frameCount);
  });

test("startPage ignores new old records while an unchanged recent update is displayed",
  async () => {
    const timber = viewer.update("Timber", 1);
    const page = await viewer.page([timber]);
    await page.advance(20000);

    page.replace([structuredClone(timber), viewer.update("Old", 30)]);
    await page.advance(12500);

    assert.equal(viewer.faviconImage(page).opacity, 0);
  });

test("startPage uses a steady green notification when reduced motion is requested",
  async () => {
    const page = await viewer.page([viewer.update("Timber", 1)], {
      reducedMotion: true
    });

    assert.equal(viewer.faviconImage(page).opacity, 0.92);
    await page.advance(5000);
    assert.equal(viewer.faviconImage(page).opacity, 0.92);
    await page.advance(25000);
    assert.equal(viewer.faviconImage(page).opacity, 0);
  });

test("startPage clears an expired notification when a suspended tab becomes visible",
  async () => {
    const page = await viewer.page([viewer.update("Timber", 1)]);
    await page.advance(2500);
    page.visibility(true);
    page.adjustClock(30000);

    page.visibility(false);

    assert.equal(viewer.faviconImage(page).opacity, 0);
    const frameCount = page.faviconFrames.length;
    await page.advance(2500);
    assert.equal(page.faviconFrames.length, frameCount);
  });

test("startPage resumes a suspended notification at its current pulse position",
  async () => {
    const page = await viewer.page([viewer.update("Timber", 1)]);
    page.visibility(true);
    page.adjustClock(12500);

    page.visibility(false);

    assert.equal(viewer.faviconImage(page).opacity, 0.92);
    await page.advance(17500);
    assert.equal(viewer.faviconImage(page).opacity, 0);
  });
