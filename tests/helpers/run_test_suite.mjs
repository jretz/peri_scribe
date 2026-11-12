/** Design: ../../docs/algorithms/verification-tooling.md */
import childProcess from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

import * as coverage from "./javascript_coverage.mjs";

const javascriptDirectory = path.join(coverage.coverageDirectory, "javascript");
await fs.mkdir(javascriptDirectory, { recursive: true });
const directory = await fs.mkdtemp(path.join(javascriptDirectory, "run-"));
const session = await coverage.createCoverageSession(directory);
const temporary = path.join(coverage.coverageDirectory, `latest-${session.runId}.tmp`);
const pytestDirectory = path.join(directory, "pytest-temp");
await fs.writeFile(temporary, JSON.stringify({ directory, runId: session.runId }));
await fs.rename(temporary, path.join(coverage.coverageDirectory, "latest-run.json"));
const workers = process.env.PERI_SCRIBE_TEST_WORKERS;
const result = childProcess.spawnSync("mise", ["run", "test-checks"], {
  stdio: "inherit",
  env: {
    ...process.env,
    PERI_SCRIBE_COVERAGE_DIRECTORY: directory,
    COVERAGE_FILE: path.join(directory, "python-data"),
    PYTEST_ADDOPTS: [
      !workers && "-n 5",
      process.env.PYTEST_ADDOPTS,
      workers && `-n ${workers}`,
      `--basetemp=${JSON.stringify(pytestDirectory)}`
    ].filter(Boolean).join(" "),
    RAYON_NUM_THREADS: "1"
  }
});
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
if (result.status === 0) await fs.rm(pytestDirectory, { recursive: true, force: true });
console.log(`Test artifacts: ${directory}`);
