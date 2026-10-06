import childProcess from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

import * as coverage from "./javascript_coverage.mjs";

await fs.mkdir(".coverage/javascript", { recursive: true });
const directory = await fs.mkdtemp(path.resolve(".coverage/javascript/run-"));
const session = await coverage.createCoverageSession(directory);
const temporary = path.resolve(".coverage", `latest-${session.runId}.tmp`);
await fs.writeFile(temporary, JSON.stringify({ directory, runId: session.runId }));
await fs.rename(temporary, ".coverage/latest-run.json");
const result = childProcess.spawnSync("mise", ["run", "test-checks"], {
  stdio: "inherit",
  env: {
    ...process.env,
    PERI_SCRIBE_COVERAGE_DIRECTORY: directory,
    COVERAGE_FILE: path.join(directory, "python-data")
  }
});
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
console.log(`Test artifacts: ${directory}`);
