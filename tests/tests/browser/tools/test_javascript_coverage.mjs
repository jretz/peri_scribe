import assert from "node:assert/strict";
import os from "node:os";
import path from "node:path";

import { test } from "@playwright/test";

import * as coverage from "../../../helpers/javascript_coverage.mjs";
import * as samples from "../../../helpers/javascript_coverage_samples.mjs";

test("coverageMap combines only branches exercised in Node and Chromium",
  async ({ page }) => {
    const script = "function choose(value) { return value ? 1 : 2; }\n";
    const descriptor = {
      script, filename: path.join(os.tmpdir(), "coverage-branch-check.js"),
      lineOffset: 0
    };
    const node = await samples.collectCoverage(script, "choose(false)",
      descriptor.filename);
    const unexpectedRequests = [];
    const origin = "https://coverage.test";
    await page.route("**/*", async route => {
      if (route.request().url() === `${origin}/fixture.html`) {
        await route.fulfill({
          contentType: "text/html", body: `<script>${script}</script>`
        });
      } else if (route.request().url() === `${origin}/favicon.ico`) {
        await route.fulfill({ status: 204 });
      } else {
        unexpectedRequests.push(route.request().url());
        await route.abort("blockedbyclient");
      }
    });
    for (const argument of [false, true]) {
      await page.coverage.startJSCoverage();
      await page.goto(`${origin}/fixture.html`);
      await page.evaluate(value => globalThis.choose(value), argument);
      const browser = (await page.coverage.stopJSCoverage()).filter(
        entry => entry.source === script);
      assert.equal(browser.length, 1, "Chromium must report the complete toy script");
      const combined = await coverage.coverageMap([...node, ...browser], descriptor);
      if (argument) {
        coverage.checkCoverage(combined);
      } else {
        assert.equal(combined.getCoverageSummary().lines.pct, 100);
        assert.equal(combined.getCoverageSummary().functions.pct, 100);
        assert.throws(() => coverage.checkCoverage(combined), /branches.*100%/);
      }
    }
    assert.deepEqual(unexpectedRequests, []);
  });
