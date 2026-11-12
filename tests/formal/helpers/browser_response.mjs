import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

import * as viewer from "../../helpers/peri_scribe/updates_script.mjs";

const { script, lineOffset } = await viewer.source();
// Each invocation starts a new page closure with its own browser objects and timers.
const initializePage = vm.compileFunction(`${script}\nreturn requestSnapshot;`, [
  "document", "Date", "Intl", "performance", "AbortSignal", "fetch",
  "setTimeout", "clearTimeout", "setInterval"
], { filename: viewer.pagePath, lineOffset, parsingContext: vm.createContext() });
const openedAt = Date.parse("2026-09-23T12:00:00Z");
const interval = 30000;
const format = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/Los_Angeles", month: "short", day: "numeric",
  hour: "numeric", minute: "2-digit", second: "2-digit", timeZoneName: "short"
});

/** Replay independent response and timer events without a real browser scheduler. */
async function replay(state, status) {
  let elapsed = 0;
  let identifier = 0;
  const timers = new Map();
  const responseStatus = { hidden: true, textContent: "" };
  const document = { getElementById: name => name === "response-status" ?
    responseStatus : {} };
  const clock = class extends Date {
    /** Keep displayed evidence time separate from the timer scheduler. */
    static now() { return openedAt + elapsed; }
  };
  function setTimeout(callback, delay) {
    timers.set(++identifier, { callback, at: elapsed + delay });
    return identifier;
  }
  /** Keep the initial download pending until a modeled request is issued. */
  let respond = () => new Promise(() => {});
  const requestSnapshot = initializePage(
    document, clock, Intl, { now: () => elapsed }, { timeout: () => undefined },
    (...args) => respond(...args), setTimeout, timer => timers.delete(timer), () => {}
  );
  /** A suspended tab can dispatch a due callback after its requested deadline. */
  function dispatch() {
    for (const [timerIdentifier, timer] of [...timers]) {
      if (timer.at <= elapsed) {
        timers.delete(timerIdentifier);
        timer.callback();
      }
    }
  }
  for (const event of state.trace) {
    switch (event) {
      case "response":
        respond = async () => ({ status, ok: status === 200 });
        await requestSnapshot({});
        break;
      case "reject":
        respond = async () => { throw new TypeError("offline"); };
        await assert.rejects(requestSnapshot({}), /offline/);
        break;
      case "advance":
        elapsed += interval;
        dispatch();
        break;
      case "delay":
        elapsed += interval;
        break;
      case "dispatch":
        dispatch();
        break;
      default:
        assert.fail(`Unknown checked event: ${event}`);
    }
  }
  assert.equal(elapsed, state.clock * interval, JSON.stringify(state));
  assert.equal(responseStatus.hidden, !state.warning, JSON.stringify(state));
  if (state.warning) {
    const time = format.format(openedAt + Math.max(state.lastResponse, 0) * interval);
    const expected = state.lastResponse < 0 ?
      `No response from updates server since this page opened at ${time}.` :
      `No response from updates server since ${time}.`;
    assert.equal(responseStatus.textContent, expected, JSON.stringify(state));
  }
}

const states = JSON.parse(fs.readFileSync(0, "utf8"));
let checked = 0;
for (const state of states) {
  // A trace without a response never reads the selected HTTP status.
  const statuses = state.trace.includes("response") ? [200, 304, 503] : [200];
  for (const status of statuses) {
    await replay(state, status);
    checked += 1;
  }
}
process.stdout.write(JSON.stringify({ checked }) + "\n");
