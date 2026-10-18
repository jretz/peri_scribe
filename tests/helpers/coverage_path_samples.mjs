import childProcess from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import url from "node:url";

export const legacyData = "SQLite format 3\u0000existing Python coverage data";

/** Isolated working directories preserve existing coverage data during collection. */
export async function workspace(context) {
  const directory = await fs.realpath(await fs.mkdtemp(
    path.join(os.tmpdir(), "coverage-paths-")));
  context.after(() => fs.rm(directory, { recursive: true, force: true }));
  await fs.writeFile(path.join(directory, ".coverage"), legacyData);
  return directory;
}

/** Record the launcher contract without recursively starting another test suite. */
export async function stubMise(directory) {
  const filename = path.join(directory, "mise");
  await fs.writeFile(filename, `#!${process.execPath}
import fs from "node:fs";
fs.writeFileSync("invocation.json", JSON.stringify({
  arguments: process.argv.slice(2),
  directory: process.env.PERI_SCRIBE_COVERAGE_DIRECTORY,
  pythonFile: process.env.COVERAGE_FILE
}));
`, { mode: 0o755 });
}

/** A fresh process exercises default paths independently of the enclosing test run. */
export function run(directory, argumentsList) {
  const environment = { ...process.env };
  delete environment.PERI_SCRIBE_COVERAGE_DIRECTORY;
  delete environment.COVERAGE_FILE;
  delete environment.NODE_TEST_CONTEXT;
  delete environment.NODE_V8_COVERAGE;
  environment.PATH = `${directory}${path.delimiter}${environment.PATH}`;
  return childProcess.spawnSync(process.execPath, argumentsList, {
    cwd: directory, encoding: "utf8", timeout: 10000, env: environment
  });
}

/** Absolute helper paths retain production imports when the working directory moves. */
export function helperPath(filename) {
  return url.fileURLToPath(new URL(filename, import.meta.url));
}
