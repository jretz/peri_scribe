import fs from "node:fs/promises";

import { recordCoverage } from "../javascript_coverage.mjs";

/** Publish a contribution only after every browser test and fixture has passed. */
export default class CoverageReporter {
  entries = [];

  /** Retain each isolated page's measurements before Playwright removes its context. */
  async onTestEnd(test, result) {
    for (const attachment of result.attachments) {
      if (attachment.name !== "viewer-v8-coverage") continue;
      const body = attachment.body ?? await fs.readFile(attachment.path);
      this.entries.push(...JSON.parse(body.toString()));
    }
  }

  /** Failed suites must never replace the missing-contributor error with old data. */
  async onEnd(result) {
    if (result.status === "passed") {
      await recordCoverage("browser", this.entries);
    }
  }
}
