import vm from "node:vm";
import { runScript } from "../../peri_scribe/updates_script.mjs";

/** Give the real viewer a deterministic DOM without browser or network dependencies. */
class Element {
  /** Keep node identity stable while the viewer reparents and reorders its rows. */
  constructor(document, tagName) {
    this.ownerDocument = document;
    this.tagName = tagName;
    this.children = [];
    this.parentElement = null;
    this.className = "";
    this.id = "";
    this.hidden = false;
    this.dataset = {};
    this.style = {};
    this.attributes = new Map();
    this.listeners = new Map();
    this.value = "";
    this.text = "";
    this.classList = {
      contains: name => this.className.split(/\s+/).includes(name),
      toggle: (name, force) => {
        const names = new Set(this.className.split(/\s+/).filter(Boolean));
        const enabled = force ?? !names.has(name);
        if (enabled) names.add(name);
        else names.delete(name);
        this.className = [...names].join(" ");
        return enabled;
      },
      add: (...names) => names.forEach(name => this.classList.toggle(name, true)),
      remove: (...names) => names.forEach(name => this.classList.toggle(name, false))
    };
  }

  /** Expose nested labels as users and accessibility tools read them. */
  get textContent() {
    return this.text + this.children.map(child => child.textContent).join("");
  }

  /** Match the browser's replacement of child nodes when assigning plain text. */
  set textContent(value) {
    this.children.forEach(child => { child.parentElement = null; });
    this.children = [];
    this.text = String(value);
  }

  /** Let reconciliation begin at the current visible list order. */
  get firstElementChild() {
    return this.children[0] ?? null;
  }

  /** Keep traversal correct after the viewer moves a row between parents. */
  get nextElementSibling() {
    const siblings = this.parentElement?.children ?? [];
    return siblings[siblings.indexOf(this) + 1] ?? null;
  }

  /** Distinguish retained records from nodes still present in the document. */
  get isConnected() {
    return this === this.ownerDocument.body || this === this.ownerDocument.head ||
      Boolean(this.parentElement?.isConnected);
  }

  /** Supply predictable text measurements for the responsive location logic. */
  get scrollWidth() {
    return this.textContent.length * 7;
  }

  /** Preserve browser reparenting semantics when assembling viewer sections. */
  append(...nodes) {
    nodes.forEach(node => this.insertBefore(node, null));
  }

  /** Allow reconciliation to reorder an existing node without copying it. */
  insertBefore(node, position) {
    node.remove();
    const index = position === null ? this.children.length :
      this.children.indexOf(position);
    if (index < 0) throw new Error("Insertion position is not a child.");
    this.children.splice(index, 0, node);
    node.parentElement = this;
    return node;
  }

  /** Keep detached rows available for departure animations and assertions. */
  remove() {
    if (!this.parentElement) return;
    const siblings = this.parentElement.children;
    siblings.splice(siblings.indexOf(this), 1);
    this.parentElement = null;
  }

  /** Retain accessibility attributes so tests can inspect control relationships. */
  setAttribute(name, value) {
    this.attributes.set(name, String(value));
    if (name === "id") this.id = String(value);
  }

  /** Expose missing attributes with the same sentinel as a browser. */
  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  /** Keep handlers attached to controls across snapshot replacements. */
  addEventListener(name, callback) {
    if (!this.listeners.has(name)) this.listeners.set(name, []);
    this.listeners.get(name).push(callback);
  }

  /** Exercise controls through their registered handlers rather than internals. */
  dispatch(name) {
    for (const callback of this.listeners.get(name) ?? []) {
      callback({ target: this, preventDefault() {} });
    }
  }

  /** Give tests the same entry point as activating a native button. */
  click() {
    this.dispatch("click");
  }

  /** Support the tag, class, and identifier selectors used by the viewer. */
  matches(selector) {
    if (selector.startsWith(".")) return this.classList.contains(selector.slice(1));
    if (selector.startsWith("#")) return this.id === selector.slice(1);
    return this.tagName === selector;
  }

  /** Resolve a row's current window after reparenting. */
  closest(selector) {
    if (this.matches(selector)) return this;
    return this.parentElement?.closest(selector) ?? null;
  }

  /** Preserve document order when locating rows, headers, and nested labels. */
  querySelectorAll(selector) {
    const result = [];
    const selectors = selector.split(",").map(part => part.trim().split(/\s+/));
    const visit = node => {
      if (selectors.some(parts => {
        if (!node.matches(parts.at(-1))) return false;
        let parent = node.parentElement;
        for (const ancestor of parts.slice(0, -1).reverse()) {
          while (parent && !parent.matches(ancestor)) parent = parent.parentElement;
          if (!parent) return false;
          parent = parent.parentElement;
        }
        return true;
      })) result.push(node);
      node.children.forEach(visit);
    };
    this.children.forEach(visit);
    return result;
  }

  /** Mirror the browser's null result when a requested descendant is absent. */
  querySelector(selector) {
    return this.querySelectorAll(selector)[0] ?? null;
  }

  /** Make hidden ancestors suppress their descendants' visible geometry. */
  getClientRects() {
    if (!this.isConnected || this.hidden ||
        this.parentElement && !this.parentElement.getClientRects().length) return [];
    return [this.getBoundingClientRect()];
  }

  /** Let every measurement reflect the latest collapse and row arrangement. */
  getBoundingClientRect() {
    return this.ownerDocument.bounds(this);
  }

  /** Let departing ghosts retain their labels without sharing live child nodes. */
  cloneNode(deep) {
    const clone = this.ownerDocument.createElement(this.tagName);
    Object.assign(clone, {
      className: this.className, text: this.text, dataset: { ...this.dataset },
      style: { ...this.style }, attributes: new Map(this.attributes)
    });
    if (deep) clone.append(...this.children.map(child => child.cloneNode(true)));
    return clone;
  }

  /** Record observable motion and let tests settle its cleanup deterministically. */
  animate(keyframes, options) {
    let finish;
    let reject;
    const animation = {
      node: this, keyframes, options,
      finished: new Promise((resolve, fail) => { finish = resolve; reject = fail; }),
      cancel: () => { animation.cancelled = true; reject(new Error("Cancelled")); },
      finish: () => finish()
    };
    this.ownerDocument.animations.push(animation);
    return animation;
  }
}

/** Record canvas images so favicon tests can inspect visible pixels and timing. */
class Canvas extends Element {
  /** Keep drawing state local to each independently created image surface. */
  constructor(document) {
    super(document, "canvas");
    this.fills = [];
    this.path = [];
    this.context = {
      fillStyle: "#000000", globalAlpha: 1,
      clearRect: () => { this.fills = []; },
      beginPath: () => { this.path = []; },
      arc: (...values) => { this.path.push(values); },
      fill: () => this.fills.push({
        color: this.context.fillStyle, opacity: this.context.globalAlpha,
        path: structuredClone(this.path)
      })
    };
  }

  /** Provide the same persistent drawing state on each context request. */
  getContext() {
    return this.context;
  }

  /** Represent generated images in memory without relying on a PNG encoder. */
  toDataURL(type) {
    const frame = {
      type, width: this.width, height: this.height,
      fills: structuredClone(this.fills)
    };
    this.ownerDocument.canvasFrames.push(frame);
    const encoded = Buffer.from(JSON.stringify(frame)).toString("base64");
    return `data:${type};base64,${encoded}`;
  }
}

/** Model normal document flow so collapsing a group moves all following groups. */
class Document {
  /** Provide the static page elements that exist before the renderer starts. */
  constructor() {
    this.animations = [];
    this.canvasFrames = [];
    this.hidden = false;
    this.listeners = new Map();
    this.identityWidths = new Map();
    this.fonts = { ready: Promise.resolve() };
    this.head = this.createElement("head");
    this.body = this.createElement("body");
    const main = this.createElement("main");
    this.body.append(main);
    for (const [tag, identifier, className] of [
      ["input", "name-filter", "name-filter"],
      ["p", "load-status", "empty"],
      ["div", "update-groups", ""],
      ["p", "sort-status", "screen-reader"],
      ["footer", "", "snapshot"]
    ]) {
      const node = this.createElement(tag);
      node.id = identifier;
      node.className = className;
      main.append(node);
      if (tag === "footer") node.append(this.createElement("time"));
    }
  }

  /** Associate dynamically created rows and ghosts with this document's layout. */
  createElement(tag) {
    return tag === "canvas" ? new Canvas(this) : new Element(this, tag);
  }

  /** Resolve live controls without maintaining a separate identifier cache. */
  getElementById(identifier) {
    return this.querySelector(`#${identifier}`);
  }

  /** Keep global queries consistent with subtree queries. */
  querySelector(selector) {
    return this.head.querySelector(selector) ?? this.body.querySelector(selector);
  }

  /** Include ghosts appended outside the main viewer in global queries. */
  querySelectorAll(selector) {
    return [...this.head.querySelectorAll(selector),
      ...this.body.querySelectorAll(selector)];
  }

  /** Retain document events for background-tab and clock-resume scenarios. */
  addEventListener(name, callback) {
    if (!this.listeners.has(name)) this.listeners.set(name, []);
    this.listeners.get(name).push(callback);
  }

  /** Exercise registered lifecycle handlers without reaching into the renderer. */
  dispatch(name) {
    for (const callback of this.listeners.get(name) ?? []) callback();
  }

  /** Reflow following windows so endpoint checks catch misplaced parent offsets. */
  bounds(node) {
    const rectangle = (left, top, width, height) => ({
      left, top, width, height, right: left + width, bottom: top + height,
      x: left, y: top
    });
    if (node.classList.contains("departing-update")) {
      return rectangle(...["left", "top", "width", "height"].map(
        name => Number.parseFloat(node.style[name]) || 0));
    }
    const positions = new Map();
    let top = 100;
    for (const section of this.querySelectorAll(".section")) {
      const heading = section.querySelector(".section-heading");
      const body = section.querySelector(".group-body");
      const list = section.querySelector(".updates");
      const height = body.hidden ? 0 : list.children.reduce((sum, child) =>
        sum + (child.classList.contains("update") ? 96 : 52), 2);
      positions.set(section, rectangle(36, top, 800, 38 + height));
      positions.set(heading, rectangle(36, top, 800, 28));
      positions.set(body, rectangle(36, top + 38, 800, height));
      positions.set(list, rectangle(36, top + 38, 800, height));
      positions.set(section.querySelector(".group-surface"),
        rectangle(36, top + 38, 800, height));
      let rowTop = top + 39;
      for (const row of list.children) {
        const rowHeight = row.classList.contains("update") ? 96 : 52;
        positions.set(row, rectangle(37, rowTop, 798, rowHeight));
        rowTop += rowHeight;
      }
      if (!section.hidden) top += 62 + height;
    }
    positions.set(this.querySelector(".snapshot"), rectangle(36, top, 800, 24));
    if (positions.has(node)) return positions.get(node);
    const row = node.closest(".update");
    if (row && row !== node) {
      const bounds = positions.get(row);
      if (node.classList.contains("identity")) {
        const name = row.querySelector(".fire-name").textContent;
        const width = this.identityWidths.get(name) ?? 630;
        return rectangle(bounds.left + 16, bounds.top + 14, width, 24);
      }
      return rectangle(bounds.left + 16, bounds.top + 14, node.scrollWidth, 24);
    }
    const heading = node.closest(".section-heading");
    if (heading) return positions.get(heading);
    return rectangle(0, 0, 900, 1000);
  }
}

/** Use absolute event times to exercise minute and bucket boundaries exactly. */
export async function page(records, options = {}) {
  const document = new Document();
  document.hidden = options.hidden ?? false;
  let now = Date.parse("2026-09-23T12:00:00Z");
  let timerIdentifier = 0;
  const timers = new Map();
  const frames = [];
  const resizeCallbacks = [];
  const motionListeners = [];
  const motion = {
    matches: options.reducedMotion ?? false,
    /** Model changes to the operating system accessibility preference. */
    addEventListener(name, callback) { motionListeners.push(callback); }
  };
  const context = vm.createContext({
    document, Intl, AbortSignal, console,
    Date: class extends Date {
      /** Tie freshness and group membership to the test's controllable clock. */
      static now() { return now; }
    },
    scrollX: 0, scrollY: 0,
    performance: { now: () => now },
    matchMedia: () => motion,
    ResizeObserver: class {
      /** Keep resize measurements connected to the same observer as the browser. */
      constructor(callback) { resizeCallbacks.push(callback); }
      /** Observation is recorded by the constructor's callback for manual resize. */
      observe() {}
    },
    getComputedStyle: () => ({
      columnGap: "16px", backgroundColor: "white", padding: "13px 16px",
      borderTop: "1px solid gray"
    }),
    requestAnimationFrame: callback => options.deferFrames ?
      frames.push(callback) : callback(),
    /** Schedule aging and highlight work without waiting for wall-clock time. */
    setTimeout(callback, delay) {
      timers.set(++timerIdentifier, { callback, at: now + delay });
      return timerIdentifier;
    },
    clearTimeout: identifier => timers.delete(identifier),
    /** Snapshot replacements are explicit so these tests isolate rendering. */
    setInterval() {},
    fetch: () => new Promise(() => {})
  });
  await runScript(context);
  const snapshot = updates => ({
    version: 1, generated_at: new Date(now).toISOString(), updates
  });
  const replaceSnapshot = context.startPage(snapshot(records));
  await Promise.resolve();
  return {
    document,
    animations: document.animations,
    faviconFrames: document.canvasFrames,
    favicon: () => document.head.querySelector("link"),
    group: index => document.querySelectorAll(".section")[index],
    row: name => document.querySelectorAll(".update").find(
      row => row.querySelector(".fire-name").textContent === name),
    replace: updates => replaceSnapshot(snapshot(updates)),
    /** Re-measure each row independently after its available width changes. */
    resize(widths) {
      document.identityWidths = new Map(Object.entries(widths));
      resizeCallbacks.forEach(callback => callback());
    },
    /** Resume the same document after time passes while its tab is hidden. */
    visibility(hidden) {
      document.hidden = hidden;
      document.dispatch("visibilitychange");
    },
    /** Model clock correction independently of elapsed timer deadlines. */
    adjustClock(milliseconds) { now += milliseconds; },
    /** Expose initial paint boundaries for the highlight fade. */
    flushFrames() {
      while (frames.length) frames.shift()();
    },
    /** Apply a user preference change while layout animations are active. */
    reduceMotion(matches) {
      motion.matches = matches;
      motionListeners.forEach(callback => callback());
    },
    /** Exercise case-insensitive filtering through its input control. */
    filter(query) {
      const input = document.getElementById("name-filter");
      input.value = query;
      input.dispatch("input");
    },
    /** Let the viewer's own timers trigger each crossed aging boundary. */
    async advance(milliseconds) {
      const destination = now + milliseconds;
      while (true) {
        const next = [...timers.entries()].filter(([, timer]) =>
          timer.at <= destination).sort((a, b) => a[1].at - b[1].at)[0];
        if (!next) break;
        const [identifier, timer] = next;
        now = timer.at;
        timers.delete(identifier);
        timer.callback();
        await Promise.resolve();
      }
      now = destination;
    },
    /** Isolate the next transition after cleanup from prior interactions settles. */
    async finishAnimations() {
      document.animations.forEach(animation => animation.finish());
      await Promise.resolve();
      document.animations.length = 0;
    }
  };
}

/** Keep timestamps relative to the shared fixed clock, including exact boundaries. */
export function update(name, minutesAgo, acreage = 1000) {
  return {
    timestamp: new Date(Date.parse("2026-09-23T12:00:00Z") -
      minutesAgo * 60000).toISOString(),
    identifier: name.toLowerCase(), name,
    location: "21 mi SW of Soledad, CA",
    mapped_area: { value: acreage, units: "acre" },
    previous_mapped_area: { value: acreage - 100, units: "acre" }
  };
}

/** Decode the current generated favicon so assertions reflect the tab's image. */
export function faviconImage(page) {
  const source = page.favicon()?.href;
  if (!source) return null;
  const frame = JSON.parse(Buffer.from(source.split(",")[1], "base64").toString());
  const fill = frame.fills.at(-1);
  const color = fill.color.match(/[\d.]+/g).map(Number);
  return { ...frame, color: color.slice(0, 3), opacity: color[3] * fill.opacity };
}

/** Read the center shown by an animation, including its moving containing section. */
export function animatedCenter(animation, frameIndex, animations = []) {
  const bounds = animation.node.getBoundingClientRect();
  const translation = frame => {
    const transform = frame.transform ?? "";
    const pair = transform.match(/translate\(([-\d.]+)p?x?,\s*([-\d.]+)p?x?\)/);
    if (pair) return [Number(pair[1]), Number(pair[2])];
    const vertical = transform.match(/translateY\(([-\d.]+)p?x?\)/);
    return [0, vertical ? Number(vertical[1]) : 0];
  };
  const [horizontal, vertical] = translation(animation.keyframes.at(frameIndex));
  const section = animation.node.closest(".section");
  const parentAnimation = animations.find(candidate => candidate.node === section);
  const [parentHorizontal, parentVertical] = parentAnimation ?
    translation(parentAnimation.keyframes.at(frameIndex)) : [0, 0];
  return [bounds.left + bounds.width / 2 + horizontal + parentHorizontal,
    bounds.top + bounds.height / 2 + vertical + parentVertical];
}

/** Describe an endpoint independently of the renderer's choice of keyframes. */
export function center(node) {
  const bounds = node.getBoundingClientRect();
  return [bounds.left + bounds.width / 2, bounds.top + bounds.height / 2];
}
