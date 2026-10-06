import assert from "node:assert/strict";
import childProcess from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import url from "node:url";
import * as coverage from "./javascript_coverage.mjs";
import * as viewer from "./peri_scribe/updates_script.mjs";

await coverage.beginCoverage("node");
const directory = await fs.mkdtemp(path.join(os.tmpdir(), "peri-scribe-viewer-"));
try {
  const { script } = await viewer.source();
  const filename = path.join(directory, "updates.js");
  await fs.writeFile(filename, script);
  const testDirectory = url.fileURLToPath(
    new URL("../tests/standard/peri_scribe/", import.meta.url));
  const tests = (await fs.readdir(testDirectory)).filter(
    name => /^test_updates_.*\.mjs$/.test(name)).sort().map(
    name => path.join(testDirectory, name));
  const toolsDirectory = url.fileURLToPath(
    new URL("../tests/standard/tools/", import.meta.url));
  tests.push(...(await fs.readdir(toolsDirectory)).filter(
    name => /^test_.*\.mjs$/.test(name)).sort().map(
    name => path.join(toolsDirectory, name)));
  assert.ok(tests.length, "Viewer coverage requires at least one test file");
  const reporter = url.fileURLToPath(new URL("viewer_coverage.mjs", import.meta.url));
  const result = childProcess.spawnSync(process.execPath, [
    "--test", `--test-reporter=${reporter}`, ...tests
  ], {
    stdio: "inherit",
    env: {
      ...process.env, PERI_SCRIBE_VIEWER_SCRIPT: filename,
      NODE_V8_COVERAGE: path.join(directory, "raw")
    }
  });
  if (result.error) throw result.error;
  process.exitCode = result.status ?? 1;
  if (result.status === 0) {
    const entries = [];
    for (const name of await fs.readdir(path.join(directory, "raw"))) {
      const raw = JSON.parse(await fs.readFile(path.join(directory, "raw", name)));
      entries.push(...raw.result.filter(entry =>
        entry.url === filename || entry.url === url.pathToFileURL(filename).href).map(
        entry => ({ ...entry, source: script })));
    }
    await coverage.recordCoverage("node", entries);
  }
} finally {
  await fs.rm(directory, { recursive: true, force: true });
}
