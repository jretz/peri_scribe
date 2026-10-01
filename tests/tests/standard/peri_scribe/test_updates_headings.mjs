import assert from "node:assert/strict";
import test from "node:test";

import * as viewer from "../../../helpers/doubles/peri_scribe/updates_dom.mjs";

test("startPage preserves fractional name widths at the stacking boundary",
  async () => {
    const name = "East South Fork Trinity River Lightning Complex";
    const page = await viewer.page([viewer.update(name, 1500)], {
      textWidths: { [name]: 324.4375 }
    });
    const row = page.row(name);
    const heading = row.querySelector(".fire-heading");
    const fireName = row.querySelector(".fire-name");
    fireName.style.flexShrink = "0.5";
    const timeAndGap = row.querySelector(".updated").getBoundingClientRect().width + 16;
    page.resizeFireHeadings({ [name]: 324.4375 + timeAndGap });
    assert.equal(heading.classList.contains("stacked-heading"), false);
    page.resizeFireHeadings({ [name]: 324.015625 + timeAndGap });
    assert.equal(heading.classList.contains("stacked-heading"), true);
    assert.equal(fireName.style.flexShrink, "0.5");
    page.resizeFireHeadings({ [name]: 324.4375 + timeAndGap });
    assert.equal(heading.classList.contains("stacked-heading"), false);
  });

for (const [scale, stacked] of [[1.05, true], [0.1, false]]) {
  test(`startPage keeps its heading fit during and after expansion at scale ${scale}`,
    async () => {
      const name = "East South Fork Trinity River Lightning Complex";
      const page = await viewer.page([viewer.update(name, 1500)]);
      const row = page.row(name);
      const heading = row.querySelector(".fire-heading");
      const required = row.querySelector(".fire-name").scrollWidth +
        row.querySelector(".updated").getBoundingClientRect().width + 16;
      const width = required + (stacked ? -0.5 : 0.5);
      page.resizeFireHeadings({ [name]: width });
      assert.equal(heading.classList.contains("stacked-heading"), stacked);
      page.group(4).querySelector(".group-toggle").click();
      await page.finishAnimations();
      page.group(4).querySelector(".group-toggle").click();
      page.scaleRows({ [name]: scale });
      assert.equal(heading.classList.contains("stacked-heading"), stacked);
      await page.finishAnimations();
      assert.equal(heading.classList.contains("stacked-heading"), stacked);
      assert.equal(page.row(name), row);
    });
}

test("startPage moves the timestamp beneath the complete name only when needed",
  async () => {
    const page = await viewer.page([viewer.update("Timber", 1500)]);
    const row = page.row("Timber");
    const heading = row.querySelector(".fire-heading");
    const name = row.querySelector(".fire-name");
    const timestamp = row.querySelector(".updated");
    const combinedWidth =
      name.scrollWidth + timestamp.getBoundingClientRect().width + 16;

    page.resizeFireHeadings({ Timber: combinedWidth });
    assert.equal(heading.classList.contains("stacked-heading"), false);
    page.resizeFireHeadings({ Timber: combinedWidth - 1 });
    assert.equal(heading.classList.contains("stacked-heading"), true);
    assert.equal(name.textContent, "Timber");
    page.resizeFireHeadings({ Timber: combinedWidth });
    assert.equal(heading.classList.contains("stacked-heading"), false);
    assert.equal(page.row("Timber"), row);
  });

test("startPage fits names independently of optional locations and other fires",
  async () => {
    const page = await viewer.page([viewer.update("Dome", 120),
      viewer.update("Big Grass Complex", 120)], {
      fireHeadingWidths: { Dome: 200, "Big Grass Complex": 200 }
    });
    assert.equal(page.row("Dome").querySelector(".fire-heading")
      .classList.contains("stacked-heading"), false);
    assert.equal(page.row("Big Grass Complex").querySelector(".fire-heading")
      .classList.contains("stacked-heading"), true);
    assert.equal(page.row("Dome").querySelector(".location").hidden, false);
    assert.equal(page.row("Dome").querySelector(".location").textContent, "CA");
  });

test("startPage refits a retained name when relative age becomes a date and time",
  async () => {
    const page = await viewer.page([viewer.update("Timber", 59)]);
    const row = page.row("Timber");
    const heading = row.querySelector(".fire-heading");
    const combinedWidth = row.querySelector(".fire-name").scrollWidth +
      row.querySelector(".updated").getBoundingClientRect().width + 16;
    page.resizeFireHeadings({ Timber: combinedWidth });
    assert.equal(heading.classList.contains("stacked-heading"), false);
    await page.advance(60001);
    assert.equal(page.row("Timber"), row);
    assert.equal(heading.classList.contains("stacked-heading"), true);
    assert.match(row.querySelector("time").textContent, /Sep 23/);
  });

test("startPage preserves a departing heading while live rows refit",
  async () => {
    const page = await viewer.page([viewer.update("Timber", 120)]);
    const heading = page.row("Timber").querySelector(".fire-heading");
    assert.equal(heading.classList.contains("stacked-heading"), false);
    page.group(1).querySelector(".group-toggle").click();
    const ghostHeading = page.document.querySelector(".departing-update")
      .querySelector(".fire-heading");
    page.resizeFireHeadings({ Timber: 80 });
    assert.equal(ghostHeading.classList.contains("stacked-heading"), false);
    await page.finishAnimations();
  });

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
