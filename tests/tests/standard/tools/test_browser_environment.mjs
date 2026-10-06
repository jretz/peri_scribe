import assert from "node:assert/strict";
import path from "node:path";
import { test } from "node:test";

import { browserEnvironment } from "../../../helpers/browser_environment.mjs";

test("browser cache separates platforms, architectures, and releases", () => {
  const options = {
    environment: { PERI_SCRIBE_PLAYWRIGHT_CACHE_ROOT: "/tool-cache/playwright/test" },
    platform: "linux", architecture: "x64", version: "1.2.3"
  };
  const original = browserEnvironment(options);
  assert.equal(original.PLAYWRIGHT_BROWSERS_PATH,
    "/tool-cache/playwright/test/linux/x64/1.2.3");
  assert.equal(original.PLAYWRIGHT_SKIP_BROWSER_GC, "1");
  assert.deepEqual(browserEnvironment(options), original);
  for (const difference of [
    { platform: "darwin" }, { architecture: "arm64" }, { version: "1.2.4" }
  ]) {
    assert.notEqual(browserEnvironment({ ...options, ...difference })
      .PLAYWRIGHT_BROWSERS_PATH, original.PLAYWRIGHT_BROWSERS_PATH);
  }
});

test("local browser cache preserves the environment and stays in the checkout", () => {
  const environment = { PATH: "/example/bin", PLAYWRIGHT_BROWSERS_PATH: "/other" };
  const result = browserEnvironment({
    environment, directory: "/checkout", platform: "linux",
    architecture: "arm64", version: "2.0.0"
  });
  assert.equal(result.PLAYWRIGHT_BROWSERS_PATH,
    path.resolve("/checkout/.cache/playwright/linux/arm64/2.0.0"));
  assert.equal(result.PATH, environment.PATH);
  assert.equal(environment.PLAYWRIGHT_BROWSERS_PATH, "/other");
});
