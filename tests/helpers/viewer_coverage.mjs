import assert from "node:assert/strict";
import { Readable } from "node:stream";
import { spec } from "node:test/reporters";

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

/** Keep passing runs compact while retaining failures. */
async function* checkedEvents(events) {
  let summary;
  for await (const event of events) {
    if (event.type === "test:start" || event.type === "test:pass") continue;
    if (event.type === "test:diagnostic" && event.data.file === undefined &&
        event.data.nesting === 0 && event.data.level === "info" &&
        /^(tests|suites|pass|fail|cancelled|skipped|todo|duration_ms) [\d.]+$/
          .test(event.data.message)) continue;
    if (event.type === "test:summary" && event.data.file === undefined) {
      summary = event.data;
    }
    yield event;
  }
  assert.ok(summary, "The test runner did not report a final summary");
  yield { type: "test:stdout", data: { message: summaryLine(summary) } };
}

/** Retain Node's failure details and summary. */
const reporter = events => Readable.from(checkedEvents(events)).compose(new spec());

export default reporter;
