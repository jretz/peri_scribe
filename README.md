# PeriScribe

PeriScribe is a tool for systematic gathering and symbolization of fire geography, for use in fire behavior analysis and presentation.

Fire geography is pulled from configurable data sources, symbolized to show how fires grow over time, and made available as KML files. Each fire has a point location (e.g., a flame icon) and a perimeter polygon for each day it was actively mapped.

## Status

Prototyped:

- **`feed-config`** — prints the configured data feeds.
- **`fetch`** — pulls current wildfire data from ArcGIS feature services into one GeoPackage snapshot per source. Each source's snapshot is named by serial number and watermark under `data/<year>/sources/<feed name>/`; on later runs only new or changed features are fetched, and existing snapshots are never modified. Data is written as close to original source formats as practical: no re-projection, original column names, per-layer CRS, etc.
- **`current-watermarks`** — logs the current watermark (the `lastEdit` timestamp) for each configured feed.
- **`list-fires`** — reads every GeoPackage below a directory and logs each fire's name, status, and identifier.

Planned:

- **`symbolize`** — applies the styles from a KML template to recent GeoPackage files to produce KML output.
- **`report`** — generates reports about fires (largest, fastest growing, etc.).
