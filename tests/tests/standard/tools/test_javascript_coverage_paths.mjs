import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import url from "node:url";

import * as coverage from "../../../helpers/javascript_coverage.mjs";
import * as samples from "../../../helpers/coverage_path_samples.mjs";

for (const contributor of ["node", "browser"]) {
  test(`beginCoverage ${contributor} preserves an existing Python coverage file`,
    async context => {
      const directory = await samples.workspace(context);
      const moduleUrl = url.pathToFileURL(samples.helperPath(
        "javascript_coverage.mjs")).href;
      const result = samples.run(directory, ["--input-type=module", "--eval", `
import * as coverage from ${JSON.stringify(moduleUrl)};
console.log(await coverage.beginCoverage(${JSON.stringify(contributor)}));
`]);
      assert.equal(result.status, 0, result.stderr);
      assert.equal(await fs.readFile(path.join(directory, ".coverage"), "utf8"),
        samples.legacyData);
      const collectionDirectory = result.stdout.trim();
      const session = await coverage.readSession(collectionDirectory);
      assert.equal(session.directory, collectionDirectory);
      assert.equal(path.relative(directory, collectionDirectory).startsWith(".."),
        false);
      await assert.rejects(fs.access(path.join(path.dirname(
        path.dirname(collectionDirectory)), "latest-run.json")), /ENOENT/);
    });
}
