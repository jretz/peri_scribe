import assert from "node:assert/strict";
import fs from "node:fs";

import * as viewer from "../../helpers/doubles/peri_scribe/updates_page.mjs";

/** Replay checked TLC transactions against the shipped page script. */
async function replay(state, weakHeaders = {ETag: 'W/"collision"'}) {
  const headers = state.kind === "weak" ? weakHeaders :
    state.kind === "none" ? {} : {ETag: '"old"'};
  const page = await viewer.page(viewer.snapshot(), headers);
  if (state.initialAge === 2) await page.advance(270000);
  const server = state.kind === "unchanged" ? 1000 : 2000;
  const replacementHeaders = state.kind === "strong" ? {ETag: '"new"'} : headers;
  page.setSnapshot(viewer.snapshot(server), replacementHeaders,
    state.response === "get error" ? 503 : 200);
  page.setHeadStatus(state.response === "head error" ? 503 :
    state.response === "unsupported" ? 405 : 200);
  if (state.response === "invalid") {
    page.setJsonError(new SyntaxError("Incomplete response"));
  }
  const before = page.calls.length;
  if (state.skipped) {
    const held = page.holdNextRequest();
    const running = page.tick();
    await held.started;
    await page.tick();
    assert.equal(page.calls.length, before + 1, JSON.stringify(state));
    held.release();
    await running;
  } else {
    await page.tick();
  }
  assert.equal(page.calls.length - before, state.requests, JSON.stringify(state));
  assert.equal(page.rendered.at(-1).updates[0].mapped_area.value,
    1000 + 1000 * state.displayed, JSON.stringify(state));
  page.setHeadStatus(200);
  page.setJsonError(undefined);
  page.setSnapshot(viewer.snapshot(server), replacementHeaders);
  if (state.kind === "weak" && state.age === 2) {
    const downloaded = page.calls.filter(call => call.method === "GET").length;
    await page.advance(page.interval * (state.skipped ? 2 : 1));
    assert.equal(page.calls.filter(call => call.method === "GET").length,
      downloaded + 1, JSON.stringify(state));
    assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, server);
  }
  await page.advance(300000);
  assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, server);
}

const states = JSON.parse(fs.readFileSync(0, "utf8"));
for (const state of states) {
  await replay(state);
  if (state.kind === "weak") await replay(state, {
    "Last-Modified": "Sat, 26 Sep 2026 00:00:00 GMT", "Content-Length": "400"
  });
}
process.stdout.write(JSON.stringify({checked: states.length}) + "\n");
