import crypto from "node:crypto";
import fs from "node:fs/promises";
import inspector from "node:inspector/promises";
import os from "node:os";
import path from "node:path";
import url from "node:url";
import vm from "node:vm";

import * as coverage from "./javascript_coverage.mjs";

export const script = `function choose(enabled) {
  if (enabled) {
    return "browser";
  }
  return "node";
}
`;
export const descriptor = {
  script, filename: path.join(os.tmpdir(), "coverage-fixture.html"), lineOffset: 18
};

/** Every synthetic script is measured using the same canonical source identity. */
export async function collect(source, invocation) {
  return collectCoverage(source, invocation, descriptor.filename);
}

/** Each test owns evidence whose lifetime cannot overlap a normal test invocation. */
export async function directory(context) {
  const result = await fs.mkdtemp(path.join(os.tmpdir(), "coverage-test-"));
  context.after(() => fs.rm(result, { recursive: true, force: true }));
  await coverage.createCoverageSession(result, descriptor);
  return result;
}

/** Real V8 data exercises conversion and merging independently of hand-made ranges. */
export async function collectCoverage(source, invocation, sourceFilename) {
  const filename = `${sourceFilename}.${crypto.randomUUID()}`;
  const session = new inspector.Session();
  session.connect();
  try {
    await session.post("Profiler.enable");
    await session.post("Profiler.startPreciseCoverage", {
      callCount: true, detailed: true
    });
    const context = vm.createContext();
    vm.runInContext(source, context, { filename });
    vm.runInContext(invocation, context);
    const { result } = await session.post("Profiler.takePreciseCoverage");
    return result.filter(entry => entry.url === url.pathToFileURL(filename).href).map(
      entry => ({ ...entry, source }));
  } finally {
    session.disconnect();
  }
}
