# Testing

## Conventions

[Conventions](../docs/conventions.md) — Coding conventions and style guide for the project also apply to testing code.

## Decomposition

- Each test module should test exactly one module of the codebase, and be named for that module.
- Each test should test exactly one thing.
- Where test setup is at all complicated, it should be factored out into a fixture.
- When a class/method/function is tested by a function, that class/method/function name should appear immediately after `test_` in the test function name. For example, if the class `MyClass` has a method `my_method`, then a test function for that method should be named `test_my_class_my_method`.

## Input/Output

No tests should touch the network in any way. All network access should be mocked out. This includes ArcGIS FeatureServer and any other data sources.

Tests must not write to the repository or depend on persistent local state. Code that intentionally reads or writes files should use pytest's per-test `tmp_path` directory or an equivalent isolated temporary location; network access remains mocked.

## Test Coverage

Do not introduce pragmas to ignore test coverage.

## What to Test

Tests should ensure behavior is correct and they should be independent of implementation. For example, if code constants change (e.g., the default number of retries), tests should still pass. If a function body has most of its code replaced with calls to a library, but it behaves in the same way, tests should still pass.

## Running PeriScribe's KMZ generation despite multiprocessing/sandbox friction

### The short version

The KMZ stage that matters (`builder.create_kmz`) renders fire plots with a real `multiprocessing.Pool`, and it works in this sandbox **if** you satisfy all these conditions:

- run the project's own venv interpreter
- call a module-level function so nothing picklable comes from `__main__`
- give the shell command a long timeout

### What works (exact pattern)

```bash
cd the-lookout/peri_scribe
.venv/bin/python -c "
import pathlib
import peri_scribe.kml.builder as b
print(b.create_kmz(pathlib.Path('data/2026')))
"
```

That completes in ~1 minute.

### Why each detail matters

- **Use `.venv/bin/python`, not a bare `python3`.** This Python defaults to the `spawn` start method (check: `multiprocessing.get_start_method()` → `spawn`), so every pool child re-executes `sys.executable`. With the venv interpreter the children get the same environment (geopandas, shapely, pyproj, matplotlib).
- **Never put worker functions or payloads in `__main__`.** Spawn children cannot re-import a `python -c`/REPL main module. In PeriScribe the pool worker (`peri_scribe.kml.plot_rendering.render_plot_request`) and its payloads (`PlotRequest`, `PlotImage`, plot series) are module-level in importable `peri_scribe.*` modules, so children bootstrap fine and no `if __name__ == "__main__":` guard is needed. This is the #1 spawn failure mode; a lambda or local closure passed into a pool would break it.
- **Don't call the `update-kmz` CLI** when only the KMZ is wanted. It fetches feeds (network is blocked here) and rebuilds derived data. `create_kmz` reads the already-derived local data under `data/2026/` and only does plotting + zipping.
- **Give a long timeout** (1800 s). First run builds matplotlib's font cache and spins up workers; the default 120 s shell timeout kills it mid-flight.
- **Sandbox niceness is already handled**: the pool initializer calls `os.nice()` and deliberately suppresses `OSError`/`AttributeError`, which is exactly what a sandbox raises when niceness is denied.
- The test suite sidesteps the pool where it doesn't need it via the `in_process_plot_image_bundles` fixture (tests/conftest.py), which monkeypatches `plot_image_bundles` with `serial_plot_image_bundles` (tests/.../kml_helpers.py). Only `test_plot_rendering.py` exercises the genuine pool. If a future sandbox blocks process spawn entirely, reuse that same monkeypatch to render serially.

### Pitfall checklist for future attempts

- Spawn (macOS default) + picklables defined in `__main__` / interactive session → fails.
- Short shell timeout while matplotlib builds its font cache → looks like a hang.
- Wrong interpreter (system python without the project deps) → import errors in children.
- Trying `update-kmz` (network fetch) instead of `create_kmz` (offline) → network denial.
