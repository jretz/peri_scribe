/** Design: ../../docs/algorithms/verification-tooling.md */
import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import * as v8Coverage from "@bcoe/v8-coverage";
import istanbulCoverage from "istanbul-lib-coverage";
import v8ToIstanbul from "v8-to-istanbul";

import * as viewer from "./peri_scribe/updates_script.mjs";

export const contributors = ["node", "browser"];
let standaloneDirectory;

/** Source identity prevents separate collectors from reporting different builds. */
export async function productionSource() {
  const { script, lineOffset } = await viewer.source();
  return { script, lineOffset, filename: viewer.pagePath };
}

/** Byte identity is required because V8 ranges are offsets into the source text. */
export function sourceHash(script) {
  return crypto.createHash("sha256").update(script).digest("hex");
}

/** A new invocation cannot accidentally reuse another run's successful evidence. */
export async function createCoverageSession(directory, descriptor) {
  descriptor ??= await productionSource();
  const session = {
    version: 1, runId: crypto.randomUUID(), directory: path.resolve(directory),
    sourceHash: sourceHash(descriptor.script), filename: descriptor.filename,
    startedAt: Date.now()
  };
  await fs.mkdir(directory, { recursive: true });
  await fs.writeFile(path.join(directory, "session.json"), JSON.stringify(session),
    { flag: "wx" });
  return session;
}

/** Explicit session identity rejects moved, stale, and source-mismatched evidence. */
export async function readSession(directory, descriptor) {
  descriptor ??= await productionSource();
  const session = JSON.parse(await fs.readFile(
    path.join(directory, "session.json"), "utf8"));
  assert.equal(session.version, 1, "Unsupported JavaScript coverage session");
  assert.ok(session.runId, "JavaScript coverage session has no run identity");
  assert.equal(session.directory, path.resolve(directory),
    "JavaScript coverage belongs to another directory");
  assert.equal(session.filename, descriptor.filename,
    "JavaScript coverage belongs to another source file");
  assert.equal(session.sourceHash, sourceHash(descriptor.script),
    "JavaScript source changed since coverage collection began");
  return session;
}

/** Standalone collectors keep useful artifacts without consuming a complete run. */
async function collectionDirectory() {
  if (process.env.PERI_SCRIBE_COVERAGE_DIRECTORY) {
    return process.env.PERI_SCRIBE_COVERAGE_DIRECTORY;
  }
  if (!standaloneDirectory) {
    standaloneDirectory = path.resolve(
      ".coverage/javascript", `standalone-${crypto.randomUUID()}`);
    await createCoverageSession(standaloneDirectory);
  }
  return standaloneDirectory;
}

/** Retrying a contributor invalidates its prior success before tests can fail. */
export async function beginCoverage(contributor) {
  assert.ok(contributors.includes(contributor), "Unknown coverage contributor");
  const directory = await collectionDirectory();
  await readSession(directory);
  await fs.rm(path.join(directory, `${contributor}.json`), { force: true });
  return directory;
}

/** Empty or partial evidence cannot establish coverage of the shipped script. */
export function validateEntries(entries, script) {
  assert.ok(entries.length, "JavaScript coverage must contain executed scripts");
  assert.doesNotMatch(script,
    /\/\*\s*(?:[cv]8|istanbul)\s+ignore|\/\*\s*node:coverage\s+(?:disable|ignore)/,
    "JavaScript coverage suppression comments are not allowed");
  for (const entry of entries) {
    assert.equal(entry.source, script, "JavaScript coverage source does not match");
    assert.ok(entry.functions?.length, "JavaScript function coverage is empty");
    assert.ok(entry.functions.some(func => func.ranges.some(range => range.count > 0)),
      "JavaScript coverage must contain executed code");
    assert.ok(entry.functions.some(func => func.ranges.some(range =>
      range.startOffset === 0 && range.endOffset === script.length)),
    "JavaScript coverage must include the complete script");
    for (const func of entry.functions) {
      assert.ok(func.ranges.length, "JavaScript function ranges are empty");
      assert.ok(func.isBlockCoverage || func.ranges[0].count === 0,
        "Executed JavaScript functions require precise block coverage");
      for (const range of func.ranges) {
        assert.ok(Number.isInteger(range.startOffset) &&
          Number.isInteger(range.endOffset) && Number.isInteger(range.count) &&
          range.startOffset >= 0 && range.startOffset < range.endOffset &&
          range.endOffset <= script.length && range.count >= 0,
        "Invalid JavaScript coverage range");
      }
    }
  }
}

/** Only successful suites publish evidence that the final gate is allowed to merge. */
export async function writeContribution(directory, contributor, entries, descriptor) {
  descriptor ??= await productionSource();
  assert.ok(contributors.includes(contributor), "Unknown coverage contributor");
  const session = await readSession(directory, descriptor);
  validateEntries(entries, descriptor.script);
  const contribution = {
    contributor, runId: session.runId, sourceHash: session.sourceHash,
    completedAt: Date.now(), entries
  };
  const filename = path.join(directory, `${contributor}.json`);
  const temporary = `${filename}.${crypto.randomUUID()}.tmp`;
  await fs.writeFile(temporary, JSON.stringify(contribution));
  await fs.rename(temporary, filename);
}

/** Browser and Node adapters share the same source checks and success manifests. */
export async function recordCoverage(contributor, entries) {
  const directory = await collectionDirectory();
  await writeContribution(directory, contributor, entries);
  return directory;
}

/** A successful process must also have published fresh, complete coverage evidence. */
export async function readContribution(directory, contributor, descriptor) {
  descriptor ??= await productionSource();
  assert.ok(contributors.includes(contributor), "Unknown coverage contributor");
  const session = await readSession(directory, descriptor);
  const contribution = JSON.parse(await fs.readFile(
    path.join(directory, `${contributor}.json`), "utf8"));
  assert.equal(contribution.contributor, contributor,
    "JavaScript coverage contributor does not match");
  assert.equal(contribution.runId, session.runId,
    "JavaScript coverage comes from another run");
  assert.equal(contribution.sourceHash, session.sourceHash,
    "JavaScript coverage comes from another source version");
  assert.ok(contribution.completedAt >= session.startedAt,
    "JavaScript coverage predates this run");
  validateEntries(contribution.entries, descriptor.script);
  return contribution.entries;
}

/** Both contributors must have succeeded in this invocation with the current source. */
export async function readContributions(directory, descriptor) {
  const contributions = await Promise.all(contributors.map(contributor =>
    readContribution(directory, contributor, descriptor)));
  return contributions.flat();
}

/** V8 offsets share one denominator before locations are mapped back into the HTML. */
export async function coverageMap(entries, descriptor) {
  validateEntries(entries, descriptor.script);
  const merged = v8Coverage.mergeScriptCovs(entries.map(entry => ({
    scriptId: "0", url: descriptor.filename,
    functions: entry.functions.map(func => ({
      ...func,
      functionName: func.functionName || `anonymous@${func.ranges[0].startOffset}`,
      ranges: func.ranges.map(range => ({ ...range }))
    }))
  })));
  const converter = v8ToIstanbul(descriptor.filename, 0, {
    source: descriptor.script
  });
  await converter.load();
  converter.applyCoverage(merged.functions);
  const converted = converter.toIstanbul();
  const file = converted[descriptor.filename];
  const offset = descriptor.lineOffset;
  const locations = [
    ...Object.values(file.statementMap),
    ...Object.values(file.fnMap).flatMap(func => [func.decl, func.loc]),
    ...Object.values(file.branchMap).flatMap(branch =>
      [branch.loc, ...branch.locations])
  ];
  const positions = locations.flatMap(location => [location.start, location.end]);
  for (const position of new Set(positions)) position.line += offset;
  for (const func of Object.values(file.fnMap)) func.line += offset;
  for (const branch of Object.values(file.branchMap)) branch.line += offset;
  return istanbulCoverage.createCoverageMap(converted);
}

/** The final gate uses one common definition of lines, branches, and functions. */
export function checkCoverage(coverage) {
  const summary = coverage.getCoverageSummary();
  for (const metric of ["lines", "branches", "functions"]) {
    const measured = summary[metric];
    assert.ok(measured.total > 0, `JavaScript ${metric} coverage is empty`);
    assert.equal(measured.covered, measured.total,
      `JavaScript ${metric} coverage must be 100% ` +
      `(${measured.covered}/${measured.total})`);
  }
  return summary;
}
