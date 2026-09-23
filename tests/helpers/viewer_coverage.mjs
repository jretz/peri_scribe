import assert from "node:assert/strict";
import { Readable } from "node:stream";
import { spec } from "node:test/reporters";
import { pagePath } from "./peri_scribe/updates_script.mjs";

/** Keep the overall result readable without expanding every counter onto a line. */
function summaryLine({ counts, duration_ms: duration, success }) {
  const green = "\u001b[32m";
  const red = "\u001b[31m";
  const yellow = "\u001b[33m";
  const reset = "\u001b[0m";
  const emoji = success ? "😎" : "😞";
  const failures = counts.failed ? `${red}✗${counts.failed}${green}` : "✗0";
  let line = `${green}${emoji} node:test ran ${counts.tests} ` +
    `${counts.tests === 1 ? "test" : "tests"} in ${Math.round(duration)} ms` +
    `  ·  ✓${counts.passed} ${failures}`;
  if (counts.suites) line += `  ·  suites ${counts.suites}`;
  const warnings = ["cancelled", "skipped", "todo"].filter(name => counts[name]);
  if (warnings.length) {
    line += `${yellow}  ·  ` +
      warnings.map(name => `${name} ${counts[name]}`).join(" · ");
  }
  return `${line}${reset}\n`;
}

/** Keep passing runs compact while retaining failures and incomplete coverage. */
async function* checkedEvents(events) {
  let measured = false;
  let summary;
  for await (const event of events) {
    if (event.type === "test:start" || event.type === "test:pass") continue;
    if (event.type === "test:diagnostic" && event.data.file === undefined &&
        event.data.nesting === 0 && event.data.level === "info" &&
        /^(tests|suites|pass|fail|cancelled|skipped|todo|duration_ms) [\d.]+$/
          .test(event.data.message)) continue;
    if (event.type === "test:coverage") {
      const files = event.data.summary.files;
      assert.equal(files.length, 1, "Coverage must include the viewer script");
      const [file] = files;
      assert.equal(file.path, process.env.PERI_SCRIBE_VIEWER_SCRIPT);
      const metrics = ["Line", "Branch", "Function"];
      for (const metric of metrics) {
        assert.ok(file[`total${metric}Count`] > 0,
          `Viewer ${metric.toLowerCase()} coverage must not be empty`);
      }
      measured = true;
      if (metrics.every(metric =>
        file[`covered${metric}Count`] === file[`total${metric}Count`])) continue;
      file.path = pagePath;
      const offset = Number(process.env.PERI_SCRIBE_VIEWER_LINE_OFFSET);
      for (const item of [...file.lines, ...file.branches, ...file.functions]) {
        item.line += offset;
      }
    }
    if (event.type === "test:summary" && event.data.file === undefined) {
      summary = event.data;
    }
    yield event;
  }
  assert.ok(measured, "The test runner did not report viewer coverage");
  assert.ok(summary, "The test runner did not report a final summary");
  yield { type: "test:stdout", data: { message: summaryLine(summary) } };
}

/** Retain Node's failure details and summary after validating coverage scope. */
const reporter = events => Readable.from(checkedEvents(events)).compose(new spec());

export default reporter;
