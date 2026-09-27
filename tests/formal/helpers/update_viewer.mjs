import assert from "node:assert/strict";
import fs from "node:fs";

import * as viewer from "../../helpers/doubles/peri_scribe/updates_dom.mjs";

const acreage = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 1, maximumFractionDigits: 1
});

/** Every displayed quantity must still belong to this exact selected record. */
function checkRecord(node, record) {
  assert.equal(node.querySelector(".fire-name").textContent, record.name);
  assert.equal(node.querySelector(".location").dataset.full, record.location ?? "");
  assert.equal(node.dataset.timestamp, record.timestamp);
  assert.equal(node.querySelector("time").dateTime, record.timestamp);
  const previous = record.previous_mapped_area?.value;
  const difference = record.mapped_area.value - (previous ?? 0);
  const rounded = Math.round(Math.abs(difference) * 10) / 10;
  const change = `${difference > 0 ? "+" : "−"}` +
    (rounded === 0 ? "<0.1" : acreage.format(rounded));
  assert.deepEqual(node.querySelectorAll("dd").map(value => value.textContent), [
    previous === undefined ? "—" : acreage.format(previous), change,
    acreage.format(record.mapped_area.value)
  ]);
  assert.equal(node.querySelectorAll("dd")[1].className,
    difference > 0 ? "increase" : "decrease");
}

/** Apply full snapshot changes and real user events to one live viewer instance. */
async function replay(steps) {
  const page = await viewer.page(steps[0].records, { reducedMotion: true });
  let priorNodes = [];
  let prior = { elapsed: 0, query: "", collapsed: Array(5).fill(false),
    nameOrder: Array(5).fill(false) };
  for (const [position, step] of steps.entries()) {
    if (position > 0) {
      if (step.timer) {
        assert.deepEqual(step.records, prior.records);
        await page.advance(step.elapsed - prior.elapsed);
      } else {
        page.adjustClock(step.elapsed - prior.elapsed);
        page.replace(step.records);
      }
    }
    if (step.query !== prior.query) page.filter(step.query);
    for (let index = 0; index < 5; index += 1) {
      if (step.collapsed[index] !== prior.collapsed[index]) {
        page.group(index).querySelector(".group-toggle").click();
      }
      if (step.nameOrder[index] !== prior.nameOrder[index]) {
        page.group(index).querySelector(".sort-order").click();
      }
    }
    await page.finishAnimations();
    const nodes = step.reuse.map(previous =>
      previous < 0 ? null : priorNodes[previous]);
    const displayed = [];
    for (let index = 0; index < 5; index += 1) {
      const group = page.group(index);
      const [count, length, ...indices] = step.groups[index];
      const actual = group.querySelectorAll(".update");
      assert.equal(actual.length, length);
      assert.equal(group.querySelector(".group-body").hidden, step.collapsed[index]);
      assert.equal(group.querySelector(".group-toggle").getAttribute("aria-expanded"),
        String(!step.collapsed[index]));
      assert.equal(group.hidden, false);
      const empty = group.querySelectorAll(".empty");
      assert.equal(empty.length, length === 0 ? 1 : 0);
      if (empty.length) {
        assert.equal(empty[0].textContent, step.query ?
          "No matching updates in this time range." : "No updates in this time range.");
      }
      assert.equal(group.querySelector(".sort-order").textContent,
        `${count} ${count === 1 ? "fire" : "fires"} ordered by ` +
          (step.nameOrder[index] ? "name" : "time"),
        "viewer history ownership disagrees with checked projection");
      for (const [offset, recordIndex] of indices.entries()) {
        const node = actual[offset];
        checkRecord(node, step.records[recordIndex]);
        if (nodes[recordIndex]) assert.equal(node, nodes[recordIndex]);
        else nodes[recordIndex] = node;
        displayed.push(node);
      }
    }
    assert.equal(new Set(displayed).size, displayed.length);
    for (const node of priorNodes.filter(Boolean)) {
      assert.equal(node.isConnected, displayed.includes(node));
    }
    for (const node of nodes.filter(Boolean)) {
      assert.equal(node.isConnected, displayed.includes(node));
    }
    priorNodes = nodes;
    prior = step;
  }
}

const cases = JSON.parse(fs.readFileSync(0, "utf8"));
for (const steps of cases) await replay(steps);
const checked = cases.reduce((count, steps) => count + steps.length, 0);
console.log(JSON.stringify({ checked }));
