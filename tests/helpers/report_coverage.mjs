import assert from "node:assert/strict";
import childProcess from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

import * as coverage from "./javascript_coverage.mjs";

let directory = process.env.PERI_SCRIBE_COVERAGE_DIRECTORY;
if (!directory) {
  const latest = JSON.parse(await fs.readFile(".coverage/latest-run.json", "utf8"));
  directory = latest.directory;
  const session = await coverage.readSession(directory);
  assert.equal(session.runId, latest.runId, "Coverage pointer belongs to another run");
}
await coverage.readSession(directory);
const environment = { ...process.env, PERI_SCRIBE_COVERAGE_DIRECTORY: directory };
const python = childProcess.spawnSync(path.resolve(".venv/bin/python"), [
  "-m", "coverage", "json", "--quiet", "--fail-under=100",
  "-o", path.join(directory, "python-coverage.json")
], {
  stdio: "inherit",
  env: { ...environment, COVERAGE_FILE: path.join(directory, "python-data") }
});
if (python.error) throw python.error;
const javascript = childProcess.spawnSync(process.execPath, [
  "tests/helpers/report_javascript_coverage.mjs"
], { stdio: "inherit", env: environment });
if (javascript.error) throw javascript.error;
process.exitCode = python.status === 0 && javascript.status === 0 ? 0 : 1;
if (!process.exitCode) console.log("Python coverage: 100% lines and branches");
