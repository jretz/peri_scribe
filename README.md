# PeriScribe

PeriScribe is a tool for systematic gathering and symbolization of fire geography, for use in fire behavior analysis and presentation.

Fire geography is pulled from configurable data sources, symbolized to show how fires grow over time, and made available as KML files. Each fire has a point location (e.g., a flame icon) and a perimeter polygon for each day it was actively mapped.

## Status

Prototyped:

- **`fetch`** — pulls current wildfire data from ArcGIS feature services into a single GeoPackage. Data is written as close to original source formats as practical: no re-projection, original column names, per-layer CRS, etc.
- **`feed-config`** — prints the configured data feeds.

Planned:

- **`symbolize`** — applies the styles from a KML template to recent GeoPackage files to produce KML output.
- **`report`** — generates reports about fires (largest, fastest growing, etc.).
