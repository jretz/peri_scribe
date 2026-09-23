import assert from "node:assert/strict";
import childProcess from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import url from "node:url";
import * as viewer from "./peri_scribe/updates_script.mjs";

const directory = await fs.mkdtemp(path.join(os.tmpdir(), "peri-scribe-viewer-"));
try {
  const { script, lineOffset } = await viewer.source();
  const filename = path.join(directory, "updates.js");
  await fs.writeFile(filename, script);
  const testDirectory = url.fileURLToPath(
    new URL("../tests/standard/peri_scribe/", import.meta.url));
  const tests = (await fs.readdir(testDirectory)).filter(
    name => /^test_updates_.*\.mjs$/.test(name)).sort().map(
    name => path.join(testDirectory, name));
  assert.ok(tests.length, "Viewer coverage requires at least one test file");
  const reporter = url.fileURLToPath(new URL("viewer_coverage.mjs", import.meta.url));
  const result = childProcess.spawnSync(process.execPath, [
    "--test", "--experimental-test-coverage",
    "--test-coverage-lines=100", "--test-coverage-branches=100",
    "--test-coverage-functions=100", `--test-coverage-include=${filename}`,
    `--test-reporter=${reporter}`, ...tests
  ], {
    stdio: "inherit",
    env: {
      ...process.env, PERI_SCRIBE_VIEWER_SCRIPT: filename,
      PERI_SCRIBE_VIEWER_LINE_OFFSET: String(lineOffset)
    }
  });
  if (result.error) throw result.error;
  process.exitCode = result.status ?? 1;
} finally {
  await fs.rm(directory, { recursive: true, force: true });
}
