import fs from "node:fs/promises";

import { test as base, expect } from "@playwright/test";

import { pagePath, source } from "../peri_scribe/updates_script.mjs";
export { update } from "../doubles/peri_scribe/updates_dom.mjs";
export { expect };

export const openedAt = new Date("2026-09-23T12:00:00Z");
const origin = "https://viewer.test";

export const test = base.extend({
  viewer: async ({ page, context }, use, testInfo) => {
    const unexpectedRequests = [];
    const pageErrors = [];
    const script = (await source()).script;
    const html = await fs.readFile(pagePath, "utf8");
    let records = [];
    let revision = 0;
    page.on("pageerror", error => pageErrors.push(error.message));
    await context.route("**/*", async route => {
      const request = route.request();
      if (request.method() === "GET" && request.url() === `${origin}/updates.html`) {
        await route.fulfill({ contentType: "text/html", body: html });
      } else if (request.method() === "GET" &&
        request.url() === `${origin}/updates.json`) {
        await route.fulfill({
          contentType: "application/json",
          headers: { ETag: `"revision-${revision}"` },
          json: {
            version: 1,
            generated_at: new Date(openedAt.getTime() + revision).toISOString(),
            updates: records
          }
        });
      } else if (request.method() === "GET" &&
        request.url() === `${origin}/favicon.ico`) {
        await route.fulfill({ status: 204 });
      } else {
        unexpectedRequests.push(`${request.method()} ${request.url()}`);
        await route.abort("blockedbyclient");
      }
    });
    await page.clock.install({ time: openedAt });
    await page.clock.pauseAt(openedAt);
    await page.coverage.startJSCoverage({ resetOnNavigation: false });
    const viewer = {
      page,
      /** Exercise the shipped document through intercepted fixture responses. */
      async open(initialRecords) {
        records = initialRecords;
        await page.goto(`${origin}/updates.html`);
        await expect(page.getByRole("searchbox")).toBeEnabled();
        await page.evaluate(() => document.fonts.ready.then(() => undefined));
        await page.clock.runFor(32);
      },
      /** Exercise refresh through the production fetch and validation path. */
      async replace(replacement) {
        records = replacement;
        revision += 1;
        const response = page.waitForResponse(`${origin}/updates.json`);
        await page.clock.fastForward(30000);
        await response;
        await expect(page.locator(".snapshot time")).toHaveAttribute(
          "datetime", new Date(openedAt.getTime() + revision).toISOString());
      },
      /** Locate the real row independently of transient departure copies. */
      row(name) {
        return page.locator(".update").filter({
          has: page.getByRole("heading", { name, exact: true, includeHidden: true })
        });
      },
      /** Each time window retains its own controls when its contents change. */
      group(index) {
        return page.locator(".section").nth(index);
      }
    };
    await use(viewer);
    const entries = (await page.coverage.stopJSCoverage()).filter(
      entry => entry.source === script);
    await testInfo.attach("viewer-v8-coverage", {
      body: Buffer.from(JSON.stringify(entries)),
      contentType: "application/json"
    });
    expect(unexpectedRequests, "All requests need explicit fixtures").toEqual([]);
    expect(pageErrors, "The viewer must not raise uncaught errors").toEqual([]);
    expect(entries, "Chromium must measure the production script").not.toEqual([]);
  }
});

/** Finish actual Web Animations without making tests wait for decorative durations. */
export async function finishAnimations(page) {
  await page.evaluate(async () => {
    const animations = document.getAnimations();
    for (const animation of animations) animation.finish();
    await Promise.all(animations.map(animation => animation.finished));
  });
}

/** Use fractional CSS layout widths, independent of platform-specific system fonts. */
export async function requiredHeadingWidth(row) {
  return row.locator(".fire-heading").evaluate(heading => {
    const name = heading.querySelector(".fire-name");
    const timestamp = heading.querySelector(".updated");
    const style = getComputedStyle(heading);
    return name.getBoundingClientRect().width +
      timestamp.getBoundingClientRect().width + parseFloat(style.columnGap);
  });
}

/** Resize the real layout and let the production ResizeObserver perform the refit. */
export async function resizeHeading(viewer, heading, width) {
  await heading.evaluate((node, value) => { node.style.width = `${value}px`; }, width);
  const viewport = viewer.page.viewportSize();
  await viewer.page.setViewportSize({
    ...viewport, width: viewport.width === 1100 ? 1099 : 1100
  });
  await viewer.page.evaluate(() => new Promise(resolve => {
    const observer = new ResizeObserver(() => {
      observer.disconnect();
      resolve();
    });
    observer.observe(document.querySelector("main"));
  }));
}
