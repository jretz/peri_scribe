import assert from "node:assert/strict";
import test from "node:test";

import * as samples from "../../../helpers/viewer_reporter_samples.mjs";

test("reporter loads in the test runner and keeps passing output compact",
  async context => {
    const result = await samples.run(context,
      'test("passing fixture", () => {});');
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /node:test ran 1 test in \d+ ms  ·  ✓1 ✗0/);
    assert.doesNotMatch(result.stdout, /passing fixture/);
  });

test("reporter retains failure details and the failing exit status", async context => {
  const result = await samples.run(context,
    'test("failing fixture", () => assert.fail("reporter failure detail"));');
  assert.equal(result.status, 1, result.stderr);
  assert.match(result.stdout, /failing fixture/);
  assert.match(result.stdout, /reporter failure detail/);
  assert.match(result.stdout, /node:test ran 1 test in \d+ ms  ·  ✓0/);
  assert.match(result.stdout, /✗1/);
});

test("reporter retains test diagnostics and skipped counts", async context => {
  const result = await samples.run(context, `
test("diagnostic fixture", context => context.diagnostic("fixture diagnostic"));
test.skip("skipped fixture", () => {});
`);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /fixture diagnostic/);
  assert.match(result.stdout, /node:test ran 2 tests in \d+ ms  ·  ✓1 ✗0/);
  assert.match(result.stdout, /skipped 1/);
});
