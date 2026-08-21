# PeriScribe

PeriScribe is a tool for systematic gathering and symbolizing of fire geography, for use in fire behavior analysis and presentation.

Fire geography is pulled from configurable data sources, symbolized to show how fires grow over time, and made available as KML files. Each fire has a point location (e.g., a flame icon) and a series of perimeters over time.

## Status

Prototyped:

- **`fetch`** — pulls current wildfire data from ArcGIS feature services into one GeoPackage snapshot per source. Each source's snapshot is named by serial number and watermark under `data/<year>/sources/<feed name>/`; on later runs only new or changed features are fetched, and existing snapshots are never modified. Data is written as close to original source formats as practical: no re-projection, original column names, per-layer CRS, etc.
- **`current-watermarks`** — logs the current watermark (the `lastEdit` timestamp) for each configured feed.
- **`list-fires`** — reads the fire source index (`data/<year>/sources/fires.json`) and logs each fire's name, status, and identifier, building the index from the GeoPackage snapshots first when it is missing.
- **`index-fire-sources`** — builds the fire source index for a year directory.
- **`ensure-admin-boundaries`** — ensures the administrative boundaries needed for symbolization are available.
- **`derive-geo-history`** — derives the full and differential point and perimeter history for a year directory.
- **`create-kml-template`** — generates the KML template used to specify symbolization.
- **`create-kml`** — builds the compressed KML (KMZ) output for a year directory from the derived history.
- **`full-pipeline`** — runs `fetch`, then `ensure-admin-boundaries`, `derive-geo-history`, and `create-kml` in order. It stops after `fetch` when nothing changed, runs the later steps only when something changed (or with `--force`), and stops at the first step that fails.

Planned:

- **`report`** — generates reports about fires (largest, fastest growing, etc.).
