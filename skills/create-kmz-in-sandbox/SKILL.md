---
name: create-kmz-in-sandbox
description: >-
  Generate a PeriScribe KMZ from saved local geography using the project's virtual
  environment when fetching new data is unnecessary or unavailable.
---

# Create PeriScribe KMZ in the Sandbox

Use this skill to generate a KMZ from existing derived data without fetching new source
observations or rebuilding geography. This is useful when checking map output from a
particular set of saved histories or working without network access.

From the project root, select only the KMZ stage with the command installed in the
project's virtual environment:

```sh
.venv/bin/peri_scribe run data/2026 --only kmz
```

Replace `data/2026` with the requested year directory. The command uses its saved fire
index, scores, and full and differential geography histories. The histories must form a
valid pair; selecting KMZ alone cannot repair missing or incompatible geography. If
upstream data needs rebuilding, use the
[offline pipeline skill](../offline-full-pipeline/SKILL.md).

The CLI keeps the year's writer lock and records unfinished work for recovery. Using
the installed command also supplies the project's geospatial dependencies. Charts are
rendered locally as SVGs, then packaged with the map and icons.

Allow enough time for the selected season's map to finish. The output is
`data/<year>/maps/PeriScribe Fires <year>.kmz`; a successful KMZ stage also updates the
fire-update log and browser viewer files. Report the output path and whether the command
completed successfully.
