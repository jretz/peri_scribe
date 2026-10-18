import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import test from "node:test";

import * as coverage from "../../../helpers/javascript_coverage.mjs";
import * as samples from "../../../helpers/coverage_path_samples.mjs";

test("run_test_suite preserves an existing Python coverage file", async context => {
  const directory = await samples.workspace(context);
  await samples.stubMise(directory);
  const result = samples.run(directory, [samples.helperPath("run_test_suite.mjs")]);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(await fs.readFile(path.join(directory, ".coverage"), "utf8"),
    samples.legacyData);
  const invocation = JSON.parse(await fs.readFile(
    path.join(directory, "invocation.json"), "utf8"));
  assert.deepEqual(invocation.arguments, ["run", "test-checks"]);
  const session = await coverage.readSession(invocation.directory);
  assert.equal(invocation.pythonFile, path.join(invocation.directory, "python-data"));
  const latest = JSON.parse(await fs.readFile(path.join(
    path.dirname(path.dirname(invocation.directory)), "latest-run.json"), "utf8"));
  assert.deepEqual(latest, { directory: invocation.directory, runId: session.runId });
  assert.ok(result.stdout.includes(invocation.directory));
});
