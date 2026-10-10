/** Design: ../../docs/algorithms/verification-tooling.md */
import childProcess from "node:child_process";
import path from "node:path";

import * as browser from "./browser_environment.mjs";
import * as coverage from "./javascript_coverage.mjs";

const directory = await coverage.beginCoverage("browser");
const result = childProcess.spawnSync(process.execPath, [
  browser.playwrightCli, "test", ...process.argv.slice(2)
], {
  stdio: "inherit",
  env: {
    ...browser.browserEnvironment(),
    PERI_SCRIBE_COVERAGE_DIRECTORY: directory,
    PERI_SCRIBE_BROWSER_RESULTS: path.join(directory, "browser-results")
  }
});
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
if (result.status === 0) await coverage.readContribution(directory, "browser");
console.log(`Browser artifacts: ${directory}`);
