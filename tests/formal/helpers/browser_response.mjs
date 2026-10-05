import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

import * as viewer from "../../helpers/peri_scribe/updates_script.mjs";

const script = new vm.Script((await viewer.source()).script);
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
  const context = vm.createContext({
    document: { getElementById: name => name === "response-status" ?
      responseStatus : {} },
    Date: class extends Date {
      /** Keep displayed evidence time separate from the timer scheduler. */
      static now() { return openedAt + elapsed; }
    },
    Intl, performance: { now: () => elapsed },
    AbortSignal: { timeout: () => undefined },
    /** Keep the initial download pending until a modeled request is issued. */
    fetch: () => new Promise(() => {}),
    setTimeout(callback, delay) {
      timers.set(++identifier, { callback, at: elapsed + delay });
      return identifier;
    },
    clearTimeout: timer => timers.delete(timer),
    setInterval() {}
  });
  script.runInContext(context);
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
        context.fetch = async () => ({ status, ok: status === 200 });
        await context.requestSnapshot({});
        break;
      case "reject":
        context.fetch = async () => { throw new TypeError("offline"); };
        await assert.rejects(context.requestSnapshot({}), /offline/);
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
for (const state of states) {
  await replay(state, 200);
  await replay(state, 304);
  await replay(state, 503);
}
process.stdout.write(JSON.stringify({ checked: states.length * 3 }) + "\n");
