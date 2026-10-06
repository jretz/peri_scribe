import childProcess from "node:child_process";

import * as browser from "./browser_environment.mjs";

const result = childProcess.spawnSync(process.execPath, [
  browser.playwrightCli, "install", "--no-shell", "chromium"
], { stdio: "inherit", env: browser.browserEnvironment() });
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
