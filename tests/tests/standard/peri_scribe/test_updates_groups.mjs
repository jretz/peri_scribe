import assert from "node:assert/strict";
import test from "node:test";

import * as viewer from "../../../helpers/doubles/peri_scribe/updates_dom.mjs";

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
