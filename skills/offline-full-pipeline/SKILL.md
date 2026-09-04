---
name: offline-full-pipeline
description: "Rebuild PeriScribe histories, scores, and KMZ from existing local snapshots without fetching network data."
---

# Offline Full Pipeline

Use this skill when derived PeriScribe outputs need to be regenerated from an existing
`data/<year>/` directory, especially when network access is unavailable or a fetch would
be undesirable.

## Workflow

1. Confirm the requested year directory exists and identify its source and derived
   paths. If the user did not specify a year, inspect available `data/<year>/`
   directories instead of assuming the current year.
2. Check that the source snapshots and required external inputs are present. Report
   missing inputs before starting; do not silently fetch replacements.
3. Run the derived stages with the project's environment and public module APIs:
   `peri_scribe.fires.differential.write_history_of_differential_geography`,
   `peri_scribe.fires.scores.score_fires`, and `peri_scribe.kml.builder.create_kmz`, in
   dependency order. The differential stage is responsible for producing the full
   history needed by later stages.
4. Use `.venv/bin/python`, because the geospatial and plotting dependencies are
   installed there and KMZ rendering may use spawned workers. Do not invoke `peri_scribe
   update-kmz`; that command fetches network feeds first.
5. Verify that the expected GeoPackages, score JSON/PNG, and `maps/PeriScribe Fires
   <year>.kmz` were written and are non-empty. Inspect the KMZ as a zip when useful, and
   do not treat file size alone as proof of correctness.

## Safety and reporting

- Treat `sources/` snapshots as append-only inputs. Do not edit, delete, or replace them
  as part of a rebuild.
- Preserve unrelated derived artifacts unless the user explicitly requests cleanup.
- Report the year directory, stages run, output paths, skipped stages, and any
  missing or suspicious inputs. A failed stage should stop the rebuild.
