import assert from "node:assert/strict";
import path from "node:path";
import istanbulReport from "istanbul-lib-report";
import istanbulReports from "istanbul-reports";

import * as coverage from "./javascript_coverage.mjs";

const directory = process.env.PERI_SCRIBE_COVERAGE_DIRECTORY;
assert.ok(directory,
  "Set PERI_SCRIBE_COVERAGE_DIRECTORY to a complete test invocation's directory");
const descriptor = await coverage.productionSource();
const entries = await coverage.readContributions(directory, descriptor);
const coverageMap = await coverage.coverageMap(entries, descriptor);
const context = istanbulReport.createContext({
  dir: path.join(directory, "report"), coverageMap
});
for (const format of ["json", "html", "lcovonly"]) {
  istanbulReports.create(format).execute(context);
}
try {
  coverage.checkCoverage(coverageMap);
  console.log("JavaScript coverage: 100% lines, branches, and functions " +
    "(Node + browser)");
} catch (error) {
  istanbulReports.create("text").execute(context);
  throw error;
}
