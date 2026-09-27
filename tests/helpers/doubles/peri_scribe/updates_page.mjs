import assert from "node:assert/strict";
import timers from "node:timers/promises";
import vm from "node:vm";
import { runScript } from "../../peri_scribe/updates_script.mjs";

/** Exercise the shipped refresh script without a browser or network access. */
export async function page(snapshot, headers = {}, response = {}) {
  const calls = [];
  const rendered = [];
  const errors = [];
  const intervals = [];
  const timeouts = new Map();
  const requestTimeouts = [];
  const openedAt = Date.parse("2026-09-23T12:00:00Z");
  let timeoutIdentifier = 0;
  let elapsed = 0;
  let server = { snapshot, headers, status: 200, headStatus: 200, ...response };
  let pendingRequest;
  const attributes = new Map();
  const status = {
    hidden: false,
    setAttribute: (name, value) => attributes.set(name, value),
    getAttribute: name => attributes.get(name)
  };
  const responseStatus = { hidden: true, textContent: "" };
  /** Schedule request and response deadlines on the same controllable clock. */
  function setTimeout(callback, delay) {
    timeouts.set(++timeoutIdentifier, { callback, at: elapsed + delay });
    return timeoutIdentifier;
  }
  const context = vm.createContext({
    document: {
      getElementById: identifier => identifier === "response-status" ?
        responseStatus : status
    },
    Date: class extends Date {
      /** Keep displayed response times independent of the test runner's clock. */
      constructor(...values) {
        super(...(values.length ? values : [openedAt + elapsed]));
      }
      /** Track elapsed response deadlines with the test's wall clock. */
      static now() { return openedAt + elapsed; }
    },
    performance: { now: () => elapsed },
    AbortSignal: {
      /** Let stalled fetches exercise the browser's real abort signal contract. */
      timeout(milliseconds) {
        requestTimeouts.push(milliseconds);
        const controller = new AbortController();
        setTimeout(() => controller.abort(
          new DOMException("The request timed out.", "TimeoutError")), milliseconds);
        return controller.signal;
      }
    },
    console: { error: error => errors.push(error) },
    setTimeout,
    clearTimeout: identifier => timeouts.delete(identifier),
    setInterval: (callback, delay) => intervals.push({ callback, delay }),
    fetch: async (url, options) => {
      calls.push({ url, ...options });
      const current = server;
      if (pendingRequest) {
        const pending = pendingRequest;
        pendingRequest = undefined;
        pending.started();
        if (pending.respectTimeout) {
          await Promise.race([pending.promise, new Promise((resolve, reject) => {
            options.signal.addEventListener("abort",
              () => reject(options.signal.reason), { once: true });
          })]);
        } else {
          await pending.promise;
        }
      }
      if (current.requestError) throw current.requestError;
      return {
        status: options.method === "HEAD" ? current.headStatus : current.status,
        ok: (options.method === "HEAD" ? current.headStatus : current.status) === 200,
        headers: new Headers(current.headers),
        json: async () => {
          if (current.jsonError) throw current.jsonError;
          return current.snapshot;
        }
      };
    }
  });
  await runScript(context);
  // Isolate refresh behavior from layout while preserving the renderer callback.
  context.startPage = data => {
    rendered.push(data);
    return replacement => rendered.push(replacement);
  };
  await timers.setImmediate();
  assert.equal(intervals.length, 1);
  let nextInterval = intervals[0].delay;
  /** Exercise elapsed polling intervals without waiting on wall-clock time. */
  async function advance(milliseconds, { waitForRequests = true } = {}) {
    const end = elapsed + milliseconds;
    while (true) {
      const next = [...timeouts.entries()].filter(([, timeout]) =>
        timeout.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
      if (next && next[1].at <= nextInterval) {
        const [identifier, timeout] = next;
        elapsed = Math.max(elapsed, timeout.at);
        timeouts.delete(identifier);
        timeout.callback();
        await timers.setImmediate();
      } else if (nextInterval <= end) {
        elapsed = Math.max(elapsed, nextInterval);
        nextInterval += intervals[0].delay;
        const request = intervals[0].callback();
        if (waitForRequests) await request;
        else await timers.setImmediate();
      } else {
        break;
      }
    }
    elapsed = Math.max(elapsed, end);
  }
  return {
    calls, rendered, errors, status, responseStatus, requestTimeouts,
    interval: intervals[0].delay,
    advance,
    /** Model a published replacement independently of the last displayed snapshot. */
    setSnapshot(data, responseHeaders = headers, responseStatus = 200) {
      server = {
        ...server, snapshot: data, headers: responseHeaders, status: responseStatus
      };
    },
    /** Model unsupported or unsuccessful metadata requests separately from downloads. */
    setHeadStatus(value) {
      server = { ...server, headStatus: value };
    },
    /** Model network failures and recovery without opening a connection. */
    setRequestError(value) {
      server = { ...server, requestError: value };
    },
    /** Model malformed response bodies independently of transport failures. */
    setJsonError(value) {
      server = { ...server, jsonError: value };
    },
    /** Keep a request pending so polling overlap can be tested deterministically. */
    holdNextRequest({ respectTimeout = false } = {}) {
      let started;
      let release;
      const waiting = new Promise(resolve => { started = resolve; });
      const promise = new Promise(resolve => { release = resolve; });
      pendingRequest = { started, promise, respectTimeout };
      return { started: waiting, release };
    },
    /** Exercise one polling interval without depending on its configured duration. */
    async tick() {
      await advance(intervals[0].delay);
    }
  };
}

/** Keep replacements the same byte length and within one HTTP date second. */
export function snapshot(acreage = 1000, milliseconds = 100) {
  return {
    version: 1,
    generated_at: `2026-09-23T00:00:00.${milliseconds}Z`,
    updates: [{
      timestamp: "2026-09-22T23:59:00Z",
      identifier: "2026-calpf-002271",
      name: "Timber",
      location: "21 mi SW of Soledad, CA",
      mapped_area: { value: acreage, units: "acre" },
      previous_mapped_area: null
    }]
  };
}
