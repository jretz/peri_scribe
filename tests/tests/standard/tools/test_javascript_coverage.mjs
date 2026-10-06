import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import test from "node:test";

import * as coverage from "../../../helpers/javascript_coverage.mjs";
import * as samples from "../../../helpers/javascript_coverage_samples.mjs";

test("coverageMap combines a branch exercised only by the browser", async () => {
  const node = await samples.collect(samples.script, "choose(false)");
  const browser = await samples.collect(samples.script, "choose(true)");
  const combined = await coverage.coverageMap(
    [...node, ...browser], samples.descriptor);
  const summary = coverage.checkCoverage(combined);
  assert.equal(summary.branches.pct, 100);
  assert.equal(summary.functions.pct, 100);
});

test("checkCoverage rejects omission of the browser's branch", async () => {
  const entries = await samples.collect(samples.script, "choose(false)");
  const incomplete = await coverage.coverageMap(entries, samples.descriptor);
  assert.throws(() => coverage.checkCoverage(incomplete), /must be 100%/);
});

test("checkCoverage rejects an uncovered branch on an otherwise covered line",
  async () => {
    const source = "function choose(value) { return value ? 1 : 2; }\n";
    const node = await samples.collect(source, "choose(false)");
    const sourceDescriptor = { ...samples.descriptor, script: source };
    const incomplete = await coverage.coverageMap(node, sourceDescriptor);
    assert.equal(incomplete.getCoverageSummary().lines.pct, 100);
    assert.equal(incomplete.getCoverageSummary().functions.pct, 100);
    assert.throws(() => coverage.checkCoverage(incomplete), /branches.*100%/);
    const browser = await samples.collect(source, "choose(true)");
    coverage.checkCoverage(await coverage.coverageMap(
      [...node, ...browser], sourceDescriptor));
  });

test("coverageMap maps uncovered source locations into the production HTML",
  async () => {
    const entries = await samples.collect(samples.script, "choose(false)");
    const incomplete = await coverage.coverageMap(entries, samples.descriptor);
    const file = incomplete.fileCoverageFor(samples.descriptor.filename);
    assert.ok(file.getUncoveredLines().includes("21"));
    for (const branch of Object.values(file.branchMap)) {
      assert.equal(branch.line, branch.loc.start.line);
      assert.equal(branch.line, branch.locations[0].start.line);
      assert.ok(branch.line <= samples.descriptor.lineOffset +
        samples.script.split("\n").length);
    }
  });

test("checkCoverage counts a function that no contributor calls", async () => {
  const source = `${samples.script}function unused() {\n  return "unvisited";\n}\n`;
  const entries = await samples.collect(source, "choose(true); choose(false)");
  const incomplete = await coverage.coverageMap(entries, {
    ...samples.descriptor, script: source
  });
  assert.ok(incomplete.getCoverageSummary().functions.pct < 100);
  assert.throws(() => coverage.checkCoverage(incomplete), /must be 100%/);
});

test("checkCoverage counts anonymous callbacks that never execute", async () => {
  const source = "const callbacks = [() => 1, () => 2];\n";
  const entries = await samples.collect(source, "callbacks[0]()");
  const incomplete = await coverage.coverageMap(entries, {
    ...samples.descriptor, script: source
  });
  assert.equal(incomplete.getCoverageSummary().lines.pct, 100);
  assert.ok(incomplete.getCoverageSummary().functions.pct < 100);
  assert.throws(() => coverage.checkCoverage(incomplete), /must be 100%/);
});

test("readContributions requires successful evidence from both suites",
  async context => {
    const location = await samples.directory(context);
    const node = await samples.collect(samples.script, "choose(false)");
    await coverage.writeContribution(location, "node", node, samples.descriptor);
    await assert.rejects(coverage.readContributions(location, samples.descriptor),
      /ENOENT/);
  });

test("readContributions accepts both source-matched contributions", async context => {
  const location = await samples.directory(context);
  const node = await samples.collect(samples.script, "choose(false)");
  const browser = await samples.collect(samples.script, "choose(true)");
  await coverage.writeContribution(location, "node", node, samples.descriptor);
  await coverage.writeContribution(location, "browser", browser, samples.descriptor);
  const entries = await coverage.readContributions(location, samples.descriptor);
  coverage.checkCoverage(await coverage.coverageMap(entries, samples.descriptor));
});

test("readContributions rejects a success manifest from an older run",
  async context => {
    const older = await samples.directory(context);
    const current = await samples.directory(context);
    const node = await samples.collect(samples.script, "choose(false)");
    await coverage.writeContribution(older, "node", node, samples.descriptor);
    await coverage.writeContribution(current, "browser", node, samples.descriptor);
    await fs.copyFile(path.join(older, "node.json"), path.join(current, "node.json"));
    await assert.rejects(coverage.readContributions(current, samples.descriptor),
      /another run/);
  });

test("readSession rejects source changes after collection starts", async context => {
  const location = await samples.directory(context);
  await assert.rejects(coverage.readSession(location, {
    ...samples.descriptor, script: `${samples.script}\n`
  }), /source changed/);
});

test("writeContribution rejects coverage for different source text", async context => {
  const location = await samples.directory(context);
  const entries = await samples.collect(`${samples.script}\n`, "choose(false)");
  await assert.rejects(
    coverage.writeContribution(location, "node", entries, samples.descriptor),
    /source does not match/);
});

test("writeContribution rejects empty coverage", async context => {
  const location = await samples.directory(context);
  await assert.rejects(
    coverage.writeContribution(location, "node", [], samples.descriptor),
    /must contain executed scripts/);
});

test("validateEntries rejects coverage that omits the complete script", async () => {
  const entries = await samples.collect(samples.script, "choose(false)");
  const partial = entries.map(entry => ({
    ...entry, functions: entry.functions.filter(func => func.functionName)
  }));
  assert.throws(() => coverage.validateEntries(partial, samples.script),
    /complete script/);
});

test("validateEntries rejects coarse executed functions as branch evidence",
  async () => {
    const entries = await samples.collect(samples.script, "choose(false)");
    const coarse = entries.map(entry => ({
      ...entry, functions: entry.functions.map(func => ({
        ...func, isBlockCoverage: false, ranges: [func.ranges[0]]
      }))
    }));
    assert.throws(() => coverage.validateEntries(coarse, samples.script),
      /precise block coverage/);
  });
