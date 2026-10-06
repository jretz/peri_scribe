import module from "node:module";
import path from "node:path";
import url from "node:url";

const require = module.createRequire(import.meta.url);
export const playwrightVersion = require("playwright/package.json").version;
export const playwrightCli = require.resolve("@playwright/test/cli");
export const projectDirectory = url.fileURLToPath(new URL("../../", import.meta.url));

/** Separate platform and release directories allow concurrent browser binary reuse. */
export function browserEnvironment({
  environment = process.env, platform = process.platform, architecture = process.arch,
  version = playwrightVersion, directory = projectDirectory
} = {}) {
  const root = environment.PERI_SCRIBE_PLAYWRIGHT_CACHE_ROOT ??
    path.join(directory, ".cache", "playwright");
  return {
    ...environment,
    PLAYWRIGHT_BROWSERS_PATH: path.resolve(root, platform, architecture, version),
    PLAYWRIGHT_SKIP_BROWSER_GC: "1"
  };
}
