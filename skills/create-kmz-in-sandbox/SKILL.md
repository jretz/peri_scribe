---
name: create-kmz-in-sandbox
description: "Generate PeriScribe KMZ files from existing local derived data when multiprocessing or sandbox constraints make the normal CLI unreliable."
---

# Create PeriScribe KMZ in the Sandbox

Use this skill when the user needs PeriScribe's KMZ output and the normal `update-kmz`
command is unsuitable because it fetches network feeds or because the plotting pool is
sensitive to interpreter, pickling, and timeout details.

Run the offline KMZ stage directly from the project root with the project's
virtual-environment interpreter:

```bash
.venv/bin/python -c "
import pathlib
import peri_scribe.kml.builder as b
print(b.create_kmz(pathlib.Path('data/2026')))
"
```

Allow a long command timeout (up to 1800 seconds). The first run may build Matplotlib's
font cache and start worker processes.

Preserve these multiprocessing invariants:

- Use `.venv/bin/python`, not a bare system `python3`, so spawned workers inherit the
  environment containing geopandas, shapely, pyproj, and matplotlib.
- Call the module-level `peri_scribe.kml.builder.create_kmz`; do not define pool
  workers, payloads, lambdas, or local closures in `__main__`. Spawned children must be
  able to import the worker and its data types from `peri_scribe.*` modules.
- Do not use `update-kmz` for this offline task: it fetches feeds and rebuilds derived
  data. `create_kmz` consumes the already-derived local data under `data/2026/` and
  performs plotting and zipping.
- Sandbox niceness failures are expected and handled by the pool initializer; do not
  treat a denied `os.nice()` call as the root failure.

If process spawning itself is unavailable, use the test suite's serial fallback: apply
the `in_process_plot_image_bundles` fixture's monkeypatch from `tests/conftest.py`,
which replaces `plot_image_bundles` with `serial_plot_image_bundles` from the test
helpers. Keep this fallback limited to environments where the genuine pool cannot run.
