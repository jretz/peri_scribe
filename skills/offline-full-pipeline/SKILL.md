---
name: offline-full-pipeline
description: >-
  Rebuild PeriScribe histories, scores, maps, and reports from saved local inputs
  without fetching new source data.
---

# Offline Full Pipeline

Use this skill to rebuild derived outputs from an existing `data/<year>/` directory
without collecting new source data. That is useful when network access is unavailable
or the existing snapshots are the inputs that need to be checked.

## Workflow

1. Confirm the requested year directory exists and identify its source and derived
   paths. If the user did not specify a year, inspect available `data/<year>/`
   directories instead of assuming the current year.
2. Check that the saved fire index, source snapshots, and required external inputs are
   present. Report missing inputs before starting; do not silently fetch replacements.
3. Run `.venv/bin/peri_scribe run data/2026 --from geography --unconditional`, replacing
   `data/2026` with the requested directory. Starting at geography skips fetching and
   runs geography, score, KMZ, and reports in dependency order. `--unconditional`
   rebuilds histories without reusing prior derived geography.
4. Use this installed command so the rebuild has the project's geospatial dependencies
   and retains the CLI's writer lock and recovery handling. The geography stage builds
   both full and differential histories; later stages use that matching pair.
5. Verify that the expected GeoPackages, score JSON and HTML chart, KMZ, and Markdown
   report were written. The map is `maps/PeriScribe Fires <year>.kmz`; inspect it as a ZIP
   archive when useful. A non-empty file alone does not establish that its contents are
   correct.

## Safety and reporting

- Treat `sources/` snapshots as append-only inputs. Do not edit, delete, or replace them
  as part of a rebuild.
- Preserve unrelated derived artifacts unless the user explicitly requests cleanup.
- Report the year directory, stages run, output paths, skipped stages, and any
  missing or suspicious inputs. A failed stage should stop the rebuild.
