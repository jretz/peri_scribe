import assert from "node:assert/strict";
import test from "node:test";

import * as viewer from "../../../helpers/doubles/peri_scribe/updates_dom.mjs";

test("startPage exposes an independent accessible collapse control per window",
  async () => {
    const page = await viewer.page([viewer.update("Timber", 10)]);
    const group = page.group(0);
    const toggle = group.querySelector(".group-toggle");
    const body = group.querySelector(".group-body");

    assert.equal(toggle.tagName, "button");
    assert.equal(toggle.getAttribute("aria-expanded"), "true");
    assert.equal(toggle.getAttribute("aria-controls"), body.id);
    toggle.click();

    assert.equal(toggle.getAttribute("aria-expanded"), "false");
    assert.equal(body.hidden, true);
    assert.equal(page.group(1).querySelector(".group-body").hidden, false);
    toggle.click();

    assert.equal(toggle.getAttribute("aria-expanded"), "true");
    assert.equal(body.hidden, false);
  });

test("startPage retains collapsed state and sorting across filtering and replacement",
  async () => {
    const records = [viewer.update("Timber", 10), viewer.update("Austin", 20)];
    const page = await viewer.page(records);
    const group = page.group(0);
    const body = group.querySelector(".group-body");
    group.querySelector(".group-toggle").click();
    group.querySelector(".sort-order").click();
    page.replace([...records, viewer.update("Zinc", 30)]);

    assert.equal(body.hidden, true);
    assert.equal(group.querySelector(".sort-order").textContent,
      "3 fires ordered by name");
    assert.deepEqual(group.querySelectorAll(".fire-name").map(node => node.textContent),
      ["Austin", "Timber", "Zinc"]);
    page.filter("TIM");

    assert.equal(body.hidden, true);
    assert.equal(group.querySelector(".sort-order").textContent,
      "1 fire ordered by name");
    page.filter("");

    assert.equal(body.hidden, true);
    assert.equal(group.querySelector(".sort-order").textContent,
      "3 fires ordered by name");
  });

test("startPage moves an aging row between two open windows continuously", async () => {
  const page = await viewer.page([viewer.update("Timber", 59.9)]);
  const row = page.row("Timber");
  const originalCenter = viewer.center(row);
  await page.advance(6001);

  assert.equal(row.closest(".section"), page.group(1));
  const animation = page.animations.find(candidate => candidate.node === row);
  assert.ok(animation);
  assert.deepEqual(viewer.animatedCenter(animation, 0, page.animations),
    originalCenter);
  assert.deepEqual(viewer.animatedCenter(animation, -1, page.animations),
    viewer.center(row));
  assert.equal(page.document.querySelectorAll(".departing-update").length, 0);
});

test("startPage sends an aging row into a closed header", async () => {
  const page = await viewer.page([viewer.update("Timber", 59.9)]);
  page.group(1).querySelector(".group-toggle").click();
  await page.finishAnimations();
  const row = page.row("Timber");
  const originalCenter = viewer.center(row);
  await page.advance(6001);

  assert.equal(row.closest(".section"), page.group(1));
  assert.equal(row.getClientRects().length, 0);
  const ghost = page.document.querySelector(".departing-update");
  assert.ok(ghost);
  const animation = page.animations.find(candidate => candidate.node === ghost);
  assert.deepEqual(viewer.animatedCenter(animation, 0), originalCenter);
  assert.deepEqual(viewer.animatedCenter(animation, -1),
    viewer.center(page.group(1).querySelector(".section-heading")));
  assert.equal(animation.keyframes.at(-1).opacity, 0);
  await page.finishAnimations();

  assert.equal(page.document.querySelectorAll(".departing-update").length, 0);
});

test("startPage brings an aging row from a closed header into an open window",
  async () => {
    const page = await viewer.page([viewer.update("Timber", 59.9)]);
    page.group(0).querySelector(".group-toggle").click();
    await page.finishAnimations();
    const row = page.row("Timber");
    const originalHeader = viewer.center(
      page.group(0).querySelector(".section-heading"));
    await page.advance(6001);

    assert.equal(row.closest(".section"), page.group(1));
    const animation = page.animations.find(candidate => candidate.node === row);
    assert.ok(animation);
    assert.deepEqual(viewer.animatedCenter(animation, 0, page.animations),
      originalHeader);
    assert.deepEqual(viewer.animatedCenter(animation, -1, page.animations),
      viewer.center(row));
    assert.equal(animation.keyframes[0].opacity, 0);
    assert.equal(animation.keyframes.at(-1).opacity, 1);
  });

test("startPage moves rows between closed windows without exposing or animating them",
  async () => {
    const page = await viewer.page([viewer.update("Timber", 59.9)]);
    page.group(0).querySelector(".group-toggle").click();
    page.group(1).querySelector(".group-toggle").click();
    await page.finishAnimations();
    const row = page.row("Timber");
    await page.advance(6001);

    assert.equal(row.closest(".section"), page.group(1));
    assert.equal(row.getClientRects().length, 0);
    assert.equal(page.animations.some(animation => animation.node === row), false);
    assert.equal(page.document.querySelectorAll(".departing-update").length, 0);
    assert.equal(page.group(0).querySelector(".sort-order").textContent,
      "0 fires ordered by time");
    assert.equal(page.group(1).querySelector(".sort-order").textContent,
      "1 fire ordered by time");
  });

test("startPage expires a row inside a closed window without a departure ghost",
  async () => {
    const page = await viewer.page([viewer.update("Timber", 2879.9)]);
    page.group(4).querySelector(".group-toggle").click();
    await page.finishAnimations();
    const row = page.row("Timber");
    await page.advance(6001);

    assert.equal(row.isConnected, false);
    assert.equal(page.animations.some(animation => animation.node === row), false);
    assert.equal(page.document.querySelectorAll(".departing-update").length, 0);
  });

test("startPage honors reduced motion while rows move through collapsed windows",
  async () => {
    const page = await viewer.page([viewer.update("Timber", 59.9)], {
      reducedMotion: true
    });
    page.group(1).querySelector(".group-toggle").click();
    await page.advance(6001);

    assert.equal(page.row("Timber").closest(".section"), page.group(1));
    assert.equal(page.animations.length, 0);
    assert.equal(page.document.querySelectorAll(".departing-update").length, 0);
  });
