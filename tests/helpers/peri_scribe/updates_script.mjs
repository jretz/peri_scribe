import assert from "node:assert/strict";
import fs from "node:fs/promises";
import url from "node:url";
import vm from "node:vm";

export const pagePath = url.fileURLToPath(
  new URL("../../../src/peri_scribe/updates.html", import.meta.url));

/** Keep coverage tied to the complete JavaScript shipped in the production page. */
export async function source() {
  const html = await fs.readFile(pagePath, "utf8");
  const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)];
  assert.equal(scripts.length, 1, "The viewer must have exactly one inline script");
  const script = scripts[0][1];
  assert.ok(script.trim(), "The viewer script must not be empty");
  const start = scripts[0].index + scripts[0][0].indexOf(">") + 1;
  return { script, lineOffset: html.slice(0, start).split("\n").length - 1 };
}

/** Name VM code with its extracted source so Node measures JavaScript, not HTML. */
export async function runScript(context) {
  const filename = process.env.PERI_SCRIBE_VIEWER_SCRIPT;
  const script = filename ?
    await fs.readFile(filename, "utf8") : (await source()).script;
  vm.runInContext(script, context, { filename: filename ?? pagePath });
}
