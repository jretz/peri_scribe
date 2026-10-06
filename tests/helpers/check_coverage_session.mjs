import assert from "node:assert/strict";

import * as coverage from "./javascript_coverage.mjs";

const directory = process.env.PERI_SCRIBE_COVERAGE_DIRECTORY;
assert.ok(directory, "Run mise test to create a fresh coverage session");
await coverage.readSession(directory);
