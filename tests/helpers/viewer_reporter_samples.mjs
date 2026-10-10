import childProcess from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import url from "node:url";

/** Real runner events expose reporter loading and preserve process exit behavior. */
export async function run(context, source) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "viewer-reporter-"));
  context.after(() => fs.rm(directory, { recursive: true, force: true }));
  const filename = path.join(directory, "test_sample.mjs");
  await fs.writeFile(filename, `import test from "node:test";
import assert from "node:assert/strict";
${source}
`);
  const reporter = url.fileURLToPath(new URL("viewer_coverage.mjs", import.meta.url));
  const environment = { ...process.env };
  delete environment.NODE_TEST_CONTEXT;
  return childProcess.spawnSync(process.execPath, [
    "--test", `--test-reporter=${reporter}`, filename
  ], {
    encoding: "utf8", timeout: 10000,
    env: environment
  });
}
