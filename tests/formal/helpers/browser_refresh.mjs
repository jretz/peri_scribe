import assert from "node:assert/strict";
import fs from "node:fs";

import * as viewer from "../../helpers/doubles/peri_scribe/updates_page.mjs";

/** Replay checked TLC transactions against the shipped page script. */
async function replay(state, prefix) {
  const headers = state.kind === "none" ? {} : {ETag: `${prefix}"old"`};
  const page = await viewer.page(viewer.snapshot(), headers);
  const server = state.kind === "unchanged" ? 1000 : 2000;
  const replacementHeaders = state.kind === "changed" ?
    {ETag: `${prefix}"new"`} : headers;
  page.setSnapshot(viewer.snapshot(server), replacementHeaders,
    state.response === "get error" ? 503 : state.response === "not modified" ? 304 : 200);
  page.setIgnoreConditional(["ignored condition", "invalid"].includes(state.response));
  if (state.response === "network error") {
    page.setRequestError(new Error("Connection failed"));
  }
  if (state.response === "invalid") {
    page.setJsonError(new SyntaxError("Incomplete response"));
  }
  const before = page.calls.length;
  const beforeBodies = page.jsonCalls.length;
  const beforeErrors = page.errors.length;
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
  assert.equal(page.calls.at(-1).method, "GET", JSON.stringify(state));
  assert.equal(page.calls.at(-1).headers["If-None-Match"],
    state.conditional ? headers.ETag : undefined, JSON.stringify(state));
  assert.equal(page.jsonCalls.length - beforeBodies, state.bodyReads,
    JSON.stringify(state));
  assert.equal(page.errors.length - beforeErrors, state.failures, JSON.stringify(state));
  assert.equal(page.rendered.at(-1).updates[0].mapped_area.value,
    1000 + 1000 * state.displayed, JSON.stringify(state));
  page.setIgnoreConditional(false);
  page.setRequestError(undefined);
  page.setJsonError(undefined);
  page.setSnapshot(viewer.snapshot(server), replacementHeaders);
  await page.tick();
  const retainedHeaders = state.validator === 1 ? replacementHeaders : headers;
  assert.equal(page.calls.at(-1).headers["If-None-Match"],
    retainedHeaders.ETag, JSON.stringify(state));
  assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, server);
  const retryCalls = page.calls.length;
  await page.advance(page.interval * 20);
  for (const call of page.calls.slice(retryCalls)) {
    assert.equal(call.headers["If-None-Match"], replacementHeaders.ETag,
      JSON.stringify(state));
  }
  assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, server);
}

const states = JSON.parse(fs.readFileSync(0, "utf8"));
for (const state of states) {
  await replay(state, "");
  await replay(state, "W/");
}
process.stdout.write(JSON.stringify({checked: states.length * 2}) + "\n");
