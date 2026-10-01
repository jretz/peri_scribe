import assert from "node:assert/strict";
import test from "node:test";
import * as viewer from "../../../helpers/doubles/peri_scribe/updates_dom.mjs";

const firstPreview = "data:image/webp;base64,UklGRg==";
const nextPreview = "data:image/webp;base64,UklGRgAB";

test("startPage leads each update with its native-size accessible preview", async () => {
  const record = { ...viewer.update("Timber", 10), preview: firstPreview };
  const page = await viewer.page([record]);
  const row = page.row("Timber");
  const image = row.querySelector(".perimeter-preview");
  assert.equal(row.firstElementChild, image);
  assert.equal(image.tagName, "img");
  assert.equal(image.src, firstPreview);
  assert.equal(image.width, 128);
  assert.equal(image.height, 72);
  assert.equal(image.hidden, false);
  assert.match(image.alt, /Timber perimeter preview.*white, yellow, then red.*north/);
});

test("startPage replaces only the preview without restarting a retained row", async () => {
  const record = { ...viewer.update("Timber", 10), preview: firstPreview };
  const page = await viewer.page([record]);
  const row = page.row("Timber");
  const image = row.querySelector(".perimeter-preview");
  await page.finishAnimations();
  const animationCount = page.animations.length;
  page.replace([{ ...record, preview: nextPreview }]);
  assert.equal(page.row("Timber"), row);
  assert.equal(row.querySelector(".perimeter-preview"), image);
  assert.equal(image.src, nextPreview);
  assert.equal(page.animations.length, animationCount);
  page.replace([{ ...record, preview: null }]);
  assert.equal(page.row("Timber"), row);
  assert.equal(image.hidden, true);
  assert.equal(row.classList.contains("without-preview"), true);
  page.replace([record]);
  assert.equal(image.hidden, false);
  assert.equal(image.src, firstPreview);
  assert.equal(row.classList.contains("without-preview"), false);
});

test("startPage keeps text-only rows compatible with missing preview fields", async () => {
  const page = await viewer.page([viewer.update("Timber", 10)]);
  const row = page.row("Timber");
  assert.equal(row.querySelector(".perimeter-preview").hidden, true);
  assert.equal(row.classList.contains("without-preview"), true);
});

for (const preview of [firstPreview, null]) {
  test(`startPage preserves the departing row's preview layout (${preview !== null})`,
    async () => {
      const page = await viewer.page([{ ...viewer.update("Timber", 10), preview }]);
      const row = page.row("Timber");
      page.group(0).querySelector(".group-toggle").click();
      const ghost = page.document.querySelector(".departing-update");
      assert.equal(ghost.classList.contains("update"), false);
      assert.equal(ghost.classList.contains("without-preview"),
        row.classList.contains("without-preview"));
      assert.equal(ghost.querySelectorAll("dd").length, 3);
      await page.finishAnimations();
      assert.equal(ghost.isConnected, false);
    });
}
