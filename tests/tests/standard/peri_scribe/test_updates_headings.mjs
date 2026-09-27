import assert from "node:assert/strict";
import test from "node:test";

import * as viewer from "../../../helpers/doubles/peri_scribe/updates_dom.mjs";

test("startPage fits and restores sort wording at both line wrapping boundaries",
  async () => {
    const page = await viewer.page([viewer.update("Timber", 1500)]);
    const toggle = page.group(4).querySelector(".group-toggle");
    const sort = page.group(4).querySelector(".sort-order");
    const fullWidth = toggle.getBoundingClientRect().width + 16 +
      sort.getBoundingClientRect().width;

    page.resizeHeadings({ 4: fullWidth });
    assert.equal(sort.textContent, "1 fire ordered by time");
    assert.ok(sort.getBoundingClientRect().top < toggle.getBoundingClientRect().bottom);

    page.resizeHeadings({ 4: fullWidth - 1 });
    assert.equal(sort.textContent, "1 fire by time");
    assert.ok(sort.getBoundingClientRect().top < toggle.getBoundingClientRect().bottom);
    const compactWidth = toggle.getBoundingClientRect().width + 16 +
      sort.getBoundingClientRect().width;

    page.resizeHeadings({ 4: compactWidth });
    assert.equal(sort.textContent, "1 fire by time");
    assert.ok(sort.getBoundingClientRect().top < toggle.getBoundingClientRect().bottom);

    page.resizeHeadings({ 4: compactWidth - 1 });
    assert.equal(sort.textContent, "1 fire ordered by time");
    assert.ok(sort.getBoundingClientRect().top > toggle.getBoundingClientRect().bottom);
    assert.equal(sort.getBoundingClientRect().left,
      toggle.getBoundingClientRect().left);

    page.resizeHeadings({ 4: compactWidth });
    assert.equal(sort.textContent, "1 fire by time");
    page.resizeHeadings({ 4: fullWidth });
    assert.equal(sort.textContent, "1 fire ordered by time");
  });

test("startPage fits each time window independently on its initial render",
  async () => {
    const page = await viewer.page([viewer.update("Timber", 1500)], {
      headingWidths: { 0: 275, 4: 160 }
    });

    assert.equal(page.group(0).querySelector(".sort-order").textContent,
      "0 fires by time");
    assert.equal(page.group(1).querySelector(".sort-order").textContent,
      "0 fires ordered by time");
    assert.equal(page.group(4).querySelector(".sort-order").textContent,
      "1 fire ordered by time");
    const toggle = page.group(4).querySelector(".group-toggle").getBoundingClientRect();
    const sort = page.group(4).querySelector(".sort-order").getBoundingClientRect();
    assert.ok(sort.top > toggle.bottom);
    assert.equal(sort.left, toggle.left);
  });

test("startPage preserves the current count and sort order while fitting changed data",
  async () => {
    const records = Array.from({ length: 10 }, (_, index) =>
      viewer.update(`Fire ${index}`, 1500));
    const page = await viewer.page(records.slice(0, 9), {
      headingWidths: { 4: 254 }
    });
    const sort = page.group(4).querySelector(".sort-order");

    assert.equal(sort.textContent, "9 fires by time");
    page.replace(records);
    assert.equal(sort.textContent, "10 fires ordered by time");
    page.filter("Fire 0");
    assert.equal(sort.textContent, "1 fire by time");
    sort.click();
    assert.equal(sort.textContent, "1 fire by name");
    page.filter("");
    assert.equal(sort.textContent, "10 fires ordered by name");
    page.replace(records.slice(0, 9));
    assert.equal(sort.textContent, "9 fires by name");
  });

test("startPage refits headings when fonts finish loading", async () => {
  let finishFonts;
  const fontsReady = new Promise(resolve => { finishFonts = resolve; });
  const page = await viewer.page([viewer.update("Timber", 1500)], { fontsReady });
  const sort = page.group(4).querySelector(".sort-order");
  assert.equal(sort.textContent, "1 fire ordered by time");

  page.document.headingWidths.set("4", 255);
  finishFonts();
  await Promise.resolve();

  assert.equal(sort.textContent, "1 fire by time");
});

test("startPage retains compact wording while scrolling anchors a later time window",
  async () => {
    const page = await viewer.page([viewer.update("Timber", 1500),
      viewer.update("Austin", 1600)], { headingWidths: { 0: 275 } });
    const firstSort = page.group(0).querySelector(".sort-order");
    const lastHeading = page.group(4).querySelector(".section-heading");
    assert.equal(firstSort.textContent, "0 fires by time");
    page.anchorGroup(4);
    const anchoredTop = lastHeading.getBoundingClientRect().top;

    page.group(4).querySelector(".sort-order").click();

    assert.equal(lastHeading.getBoundingClientRect().top, anchoredTop);
    assert.equal(firstSort.textContent, "0 fires by time");
    assert.deepEqual(page.group(4).querySelectorAll(".fire-name").map(
      node => node.textContent), ["Austin", "Timber"]);
  });
