import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/tests/browser",
  testMatch: "test_*.mjs",
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  outputDir: process.env.PERI_SCRIBE_BROWSER_RESULTS ??
    fs.mkdtempSync(path.join(os.tmpdir(), "peri-scribe-browser-")),
  reporter: [
    ["list"],
    ["./tests/helpers/browser/coverage_reporter.mjs"]
  ],
  use: {
    channel: "chromium",
    viewport: { width: 1100, height: 900 },
    locale: "en-US",
    timezoneId: "America/Los_Angeles",
    serviceWorkers: "block",
    screenshot: "only-on-failure"
  }
});
