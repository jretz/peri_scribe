import assert from "node:assert/strict";
import test from "node:test";

import * as viewer from "../../../helpers/doubles/peri_scribe/updates_dom.mjs";

test("startPage preserves distinct duplicate updates when replacing a snapshot",
  async () => {
    const timber = viewer.update("Timber", 10);
    const page = await viewer.page([timber, structuredClone(timber)]);
    const original = page.group(0).querySelectorAll(".update");

    page.replace([structuredClone(timber), structuredClone(timber),
      structuredClone(timber)]);
    const replaced = page.group(0).querySelectorAll(".update");

    assert.equal(replaced.length, 3);
    assert.equal(replaced[0], original[0]);
    assert.equal(replaced[1], original[1]);
    assert.notEqual(replaced[2], original[1]);
    assert.equal(page.group(0).querySelector(".sort-order").textContent,
      "1 fire ordered by time");
    assert.ok(page.animations.some(animation => animation.node === replaced[2] &&
      animation.keyframes[0].opacity === 0));
  });

test("startPage releases removed records and creates fresh rows if they return",
  async () => {
    const timber = viewer.update("Timber", 10);
    const page = await viewer.page([timber]);
    const original = page.row("Timber");

    page.replace([]);
    assert.equal(original.isConnected, false);
    assert.equal(page.document.querySelectorAll(".departing-update").length, 1);
    await page.finishAnimations();
    page.replace([timber]);

    assert.notEqual(page.row("Timber"), original);
    assert.equal(page.document.querySelectorAll(".departing-update").length, 0);
    assert.ok(page.animations.some(animation => animation.node === page.row("Timber")));
  });

test("startPage formats missing acreage and changes smaller than one tenth acre",
  async () => {
    const first = { ...viewer.update("First", 10, 123), previous_mapped_area: null };
    const increase = viewer.update("Increase", 10, 1000);
    increase.previous_mapped_area.value = 999.98;
    const decrease = viewer.update("Decrease", 10, 1000);
    decrease.previous_mapped_area.value = 1000.02;
    const page = await viewer.page([first, increase, decrease]);

    const firstValues = page.row("First").querySelectorAll("dd");
    assert.deepEqual(firstValues.map(node => node.textContent),
      ["—", "+123.0", "123.0"]);
    assert.equal(firstValues[0].getAttribute("aria-label"), "No previous log entry");
    assert.equal(page.row("Increase").querySelector(".increase").textContent,
      "+<0.1");
    assert.equal(page.row("Decrease").querySelector(".decrease").textContent,
      "−<0.1");
  });

test("startPage counts unnamed identifiers by name while retaining separate IDs",
  async () => {
    const unnamed = {
      ...viewer.update("Timber", 10), identifier: null, location: null
    };
    const older = { ...unnamed, timestamp: viewer.update("Timber", 20).timestamp };
    const page = await viewer.page([unnamed, older, viewer.update("Timber", 30)]);

    assert.equal(page.group(0).querySelectorAll(".update").length, 3);
    assert.equal(page.group(0).querySelector(".sort-order").textContent,
      "2 fires ordered by time");
    assert.equal(page.row("Timber").querySelector(".location").textContent, "");
  });

for (const [identifier, identity] of [
  [null, ["name", "Timber"]],
  ["2026-timber", ["id", "2026-timber"]]
]) {
  test(`startPage counts a renamed ${identity[0]} fire once with retained history`,
    async () => {
      const original = { ...viewer.update("Timber", 20), identifier };
      const renamed = {
        ...viewer.update("Timber Complex", 10), identifier, log_identity: identity
      };

      const page = await viewer.page([original, renamed]);

      assert.equal(page.group(0).querySelectorAll(".update").length, 2);
      assert.equal(page.group(0).querySelector(".sort-order").textContent,
        "1 fire ordered by time");
    });
}

test("startPage applies identity corrections when visible record values are unchanged",
  async () => {
    const original = { ...viewer.update("Timber", 20), identifier: null };
    const renamed = {
      ...viewer.update("Timber Complex", 10), identifier: null,
      log_identity: ["name", "Timber Complex"]
    };
    const page = await viewer.page([original, renamed]);
    assert.equal(page.group(0).querySelector(".sort-order").textContent,
      "2 fires ordered by time");

    page.replace([original, { ...renamed, log_identity: ["name", "Timber"] }]);

    assert.equal(page.group(0).querySelector(".sort-order").textContent,
      "1 fire ordered by time");
  });

test("startPage counts distinct local namesakes separately across repeated updates",
  async () => {
    const original = {
      ...viewer.update("Timber", 30), identifier: null, log_identity: ["name", "Timber"]
    };
    const newer = {
      ...viewer.update("Timber", 20), identifier: null,
      log_identity: ["local", "new-timber"]
    };
    const latest = { ...newer, timestamp: viewer.update("Timber", 10).timestamp };

    const page = await viewer.page([original, newer, latest]);

    assert.equal(page.group(0).querySelectorAll(".update").length, 3);
    assert.equal(page.group(0).querySelector(".sort-order").textContent,
      "2 fires ordered by time");
  });

test("startPage fits and restores each location according to its row's space",
  async () => {
    const page = await viewer.page([viewer.update("Timber", 10),
      viewer.update("Austin", 10), viewer.update("Iron", 10),
      { ...viewer.update("River", 10), location: "Near the river" }]);
    const timber = page.row("Timber").querySelector(".location");
    const austin = page.row("Austin").querySelector(".location");
    const iron = page.row("Iron").querySelector(".location");
    const river = page.row("River").querySelector(".location");

    page.resize({ Timber: 100, Austin: 50, Iron: 630, River: 80 });

    assert.equal(timber.textContent, "CA");
    assert.equal(timber.hidden, false);
    assert.equal(austin.hidden, true);
    assert.equal(iron.textContent, "21 mi SW of Soledad, CA");
    assert.equal(iron.hidden, false);
    assert.equal(river.hidden, true);
    page.resize({});

    for (const location of [timber, austin, iron]) {
      assert.equal(location.textContent, "21 mi SW of Soledad, CA");
      assert.equal(location.hidden, false);
    }
    assert.equal(river.textContent, "Near the river");
    assert.equal(river.hidden, false);
  });

test("startPage begins freshness highlighting after paint and ends at fifteen minutes",
  async () => {
    const page = await viewer.page([viewer.update("Timber", 14)], {
      deferFrames: true
    });
    const row = page.row("Timber");
    assert.equal(row.classList.contains("recent"), false);

    page.flushFrames();
    assert.equal(row.classList.contains("recent"), true);
    await page.advance(60001);

    assert.equal(row.classList.contains("recent"), false);
    assert.equal(row.querySelector("time").textContent, "15 minutes ago");
  });

test("startPage does not highlight a timestamp made future by a clock correction",
  async () => {
    const page = await viewer.page([viewer.update("Timber", 1)], { deferFrames: true });
    page.adjustClock(-120000);
    page.flushFrames();

    assert.equal(page.row("Timber").classList.contains("recent"), false);
  });

test("startPage updates singular minute labels without replacing the row", async () => {
  const page = await viewer.page([viewer.update("Timber", 0)]);
  const row = page.row("Timber");
  assert.equal(row.querySelector("time").textContent, "0 minutes ago");

  await page.advance(60001);
  assert.equal(page.row("Timber"), row);
  assert.equal(row.querySelector("time").textContent, "1 minute ago");
  await page.advance(60000);

  assert.equal(row.querySelector("time").textContent, "2 minutes ago");
});

test("startPage excludes future and expired updates from every time window",
  async () => {
    const page = await viewer.page([viewer.update("Future", -1),
      viewer.update("Expired", 2880)]);

    assert.equal(page.document.querySelectorAll(".update").length, 0);
    assert.equal(page.document.getElementById("sort-status").textContent,
      "0 updates shown.");
    await page.advance(60001);

    assert.equal(page.row("Future").querySelector("time").textContent,
      "0 minutes ago");
    assert.equal(page.row("Expired"), undefined);
  });

test("startPage reorders repeated fire names chronologically in either ordering",
  async () => {
    const page = await viewer.page([viewer.update("Timber", 30),
      viewer.update("Austin", 20), viewer.update("Timber", 10)]);
    const group = page.group(0);
    const original = group.querySelectorAll(".update");
    const sort = group.querySelector(".sort-order");

    sort.click();
    assert.deepEqual(group.querySelectorAll(".update"),
      [original[1], original[0], original[2]]);
    assert.equal(page.document.getElementById("sort-status").textContent,
      "0–60 minutes ago: ordered by name.");
    sort.click();

    assert.deepEqual(group.querySelectorAll(".update"), original);
    assert.equal(sort.textContent, "2 fires ordered by time");
  });

test("startPage filters case insensitively and recovers from no matching names",
  async () => {
    const page = await viewer.page([viewer.update("Timber", 10),
      viewer.update("Austin", 100)]);
    page.filter("IM");

    assert.equal(page.group(0).hidden, false);
    assert.equal(page.group(1).hidden, true);
    assert.equal(page.document.getElementById("sort-status").textContent,
      "1 updates shown.");
    page.filter("missing");

    const empty = page.document.querySelectorAll(".empty").find(
      node => node.textContent === "No matching fires.");
    assert.equal(empty.hidden, false);
    page.filter("");

    assert.equal(empty.hidden, true);
    assert.equal(page.group(0).hidden, false);
    assert.equal(page.group(1).hidden, false);
  });

test("startPage cancels active movement and departure ghosts on motion changes",
  async () => {
    const page = await viewer.page([viewer.update("Timber", 10),
      viewer.update("Austin", 20)]);
    page.replace([viewer.update("Timber", 10)]);
    assert.equal(page.document.querySelectorAll(".departing-update").length, 1);
    const animations = [...page.animations];

    page.reduceMotion(true);
    await Promise.resolve();

    assert.ok(animations.length > 0);
    assert.ok(animations.every(animation => animation.cancelled));
    assert.equal(page.document.querySelectorAll(".departing-update").length, 0);
    page.replace([viewer.update("Iron", 10)]);
    assert.equal(page.animations.length, animations.length);
  });

test("startPage removes cancelled ghosts when filtering during a replacement",
  async () => {
    const page = await viewer.page([viewer.update("Timber", 10)]);
    page.replace([]);
    assert.equal(page.document.querySelectorAll(".departing-update").length, 1);

    page.filter("Timber");
    await Promise.resolve();

    assert.equal(page.document.querySelectorAll(".departing-update").length, 0);
    assert.equal(page.document.querySelectorAll(".update").length, 0);
  });

test("startPage refreshes aged rows when returning to a visible tab without motion",
  async () => {
    const page = await viewer.page([viewer.update("Timber", 59.9)]);
    const row = page.row("Timber");
    page.visibility(true);
    page.adjustClock(10000);

    assert.equal(row.closest(".section"), page.group(0));
    page.visibility(false);

    assert.equal(row.closest(".section"), page.group(1));
    assert.equal(page.animations.length, 0);
  });

test("startPage avoids motion for updates replaced while the tab is hidden",
  async () => {
    const page = await viewer.page([viewer.update("Timber", 10)]);
    page.visibility(true);
    page.replace([viewer.update("Austin", 10)]);

    assert.equal(page.animations.length, 0);
    assert.equal(page.row("Austin").isConnected, true);
    assert.equal(page.document.querySelectorAll(".departing-update").length, 0);
  });

test("startPage keeps newly arriving updates hidden inside a collapsed window",
  async () => {
    const page = await viewer.page([]);
    page.group(0).querySelector(".group-toggle").click();
    await page.finishAnimations();

    page.replace([viewer.update("Timber", 10)]);

    const row = page.row("Timber");
    assert.equal(row.getClientRects().length, 0);
    assert.equal(page.animations.some(animation => animation.node === row), false);
    assert.equal(page.document.querySelectorAll(".departing-update").length, 0);
    assert.equal(page.group(0).querySelector(".sort-order").textContent,
      "1 fire ordered by time");
  });

for (const [minutes, destination] of [[240, 2], [720, 3], [1440, 4]]) {
  test(`startPage moves older updates at the ${minutes}-minute boundary`, async () => {
    const page = await viewer.page([viewer.update("Timber", minutes - 0.1)]);
    const row = page.row("Timber");
    assert.equal(row.closest(".section"), page.group(destination - 1));

    await page.advance(6001);

    assert.equal(row.closest(".section"), page.group(destination));
    assert.ok(page.animations.some(animation => animation.node === row));
  });
}

test("startPage fades expired updates out of an open window", async () => {
  const page = await viewer.page([viewer.update("Timber", 2879.9)]);
  const row = page.row("Timber");

  await page.advance(6001);

  assert.equal(row.isConnected, false);
  const ghost = page.document.querySelector(".departing-update");
  const animation = page.animations.find(candidate => candidate.node === ghost);
  assert.equal(animation.keyframes[0].opacity, 1);
  assert.equal(animation.keyframes.at(-1).opacity, 0);
  await page.finishAnimations();

  assert.equal(page.document.querySelectorAll(".departing-update").length, 0);
});
