# PeriScribe

PeriScribe is a tool for systematic gathering and symbolizing of fire geography, for use in fire behavior analysis and presentation.

Fire geography is pulled from configurable data sources, symbolized to show how fires grow over time, and made available as KML files. Each fire has a point location (e.g., a flame icon) and a series of perimeters over time.

## Status

Prototyped:

- **`fetch`** — pulls current wildfire data from ArcGIS feature services into one GeoPackage snapshot per source. Each source's snapshot is named by serial number and timestamp in directories under `data/<year>/sources/<feed name>/`; on later runs only new or changed features are fetched, and existing snapshots are never modified. Data is written as close to original source formats as practical: no re-projection, original column names, per-layer CRS, etc.
- **`current-timestamps`** — logs the current timestamp (the `lastEdit` timestamp) for each configured feed.
- **`list-fires`** — reads the fire source index (`data/<year>/sources/fires.json`) and logs each fire's name, status, and identifier, building the index from the GeoPackage snapshots first when it is missing.
- **`index-fire-sources`** — builds the fire source index for a year directory.
- **`ensure-admin-boundaries`** — ensures the administrative boundaries needed for symbolization are available.
- **`derive-geo-history`** — derives the full and differential point and perimeter history for a year directory.
- **`create-kml-template`** — generates the KML template used to specify symbolization.
- **`create-kml`** — builds the compressed KML (KMZ) output for a year directory from the derived history.
- **`full-pipeline`** — runs `fetch`, then `ensure-admin-boundaries`, `derive-geo-history`, and `create-kml` in order. It stops after `fetch` when nothing changed, runs the later steps only when something changed (or with `--force`), and stops at the first step that fails.

Planned:

- **`report`** — generates reports about fires (largest, fastest growing, etc.).

## Data Flow

```
  ┌─ EXTERNAL WORLD ─────────────────────────────────────────────────────────────────┐
  │three ArcGIS feeds — the data that drives the maps:                               │
  │   • CA Perimeters — CAL FIRE/NIFC; keeps every update of the season              │
  │   • WFIGS Perimeters — USFS; only the latest perimeter per active fire           │
  │   • WFIGS Locations — one incident point per fire                                │
  │plus CA + AZ/NV/OR state-boundary services (for classification)                   │
  └──────────────────┬──────────────────────────────────────────────────────────┬────┘
       fire feeds    ↓                                        boundary services ↓
  ┌─ 1 · FETCH ────────────────────────────────────────┐   ┌─ ADMIN BOUNDARIES ──────┐
  │for each feed, query its ArcGIS layer:              │   │fetch the CA polygon and │
  │  1. read the layer timestamp (lastEdit); if a      │   │AZ/NV/OR neighbors from  │
  │     snapshot already carries it, skip the feed     │   │ArcGIS; intersect to     │
  │  2. else fetch only features changed since the     │   │get the shared border    │
  │     stored cutoff − 5-min overlap, so in-flight    │   │lines; write one small   │
  │     edits are re-checked rather than missed        │   │boundary GeoPackage:     │
  │  3. drop rows already stored identically           │   │data/administrative      │
  │why: snapshots are append-only and verbatim         │   │boundaries/CA_border.gpkg│
  │(original CRS, columns, attributes), never modified │   └──────────────────────┬──┘
  └──────────────────┬─────────────────────────────────┘                          │
                     ↓  data/<year>/sources/<feed>/000___/000142,lastEdit=….gpkg  │
  ┌─ 2 · INDEX + CLASSIFY ─────────────────────────────┐                          │
  │read every snapshot; group rows into distinct fires:│                          │
  │  • any shared identifier → same fire; complexes    │                          │
  │    link children via the complex ID                │                          │
  │  • name-only matches merge only when spatially     │<─────────────────────────┤
  │    compatible (“Canyon” in CA vs AK stay apart)    │                          │
  │classify each fire vs the CA border (uses the       │                          │
  │file from the right; picks the trusted source)      │                          │
  └──────────────────┬─────────────────────────────────┘                          │
                     ↓  sources/fires.json — identity + classification            │
  ┌─ 3 · FULL HISTORY ─────────────────────────────────┐                          │
  │build one cleaned, reconciled timeline per fire:    │                          │
  │  • collapse consecutive identical perimeters       │                          │
  │    (duplicate observations of the same moment)     │                          │
  │  • reconcile CA vs WFIGS — the border              │<─────────────────────────┘
  │    classification picks the preferred source       │
  │  • drop implausibly small perimeters (a 2-acre     │
  │    “update” of a 100k-acre fire is noise)          │
  │  • clean geometry for Google Earth: tiny parts,    │
  │    holes, collinear points, slits                  │
  └──────────────────┬─────────────────────────────────┘
                     ↓  derived/history_of_full_geography.gpkg
  ┌─ 4 · DIFFERENTIAL HISTORY ─────────────────────────┐
  │turn the full timeline into growth rings, per fire: │
  │  • correct each ring: subtract every later         │
  │    perimeter (a later shrink folds back as a       │
  │    correction — only growth remains)               │
  │  • keep rings that add area; compute deltas:       │
  │    area, % contained, estimated cost               │
  │points are copied through unchanged                 │
  └──────────────────┬─────────────────────────────────┘
                     ↓  derived/history_of_differential_geography.gpkg
  ┌─ 5 · CREATE KMZ ───────────────────────────────────┐   ┌─ KML TEMPLATE ──────────┐
  │per fire, build the symbolized KML:                 │   │data/templates/PeriScribe│
  │  • Active / Inactive folders                       │   │Template.kml — fictional │
  │  • Latest Perimeters: filled latest area + last 3  │   │fire; you edit its styles│
  │    outlines + point icon, in explicit draw order   │   │in Google Earth (the KML │
  │    (the icon is never covered)                     │   │editor is the styling UI)│
  │  • Progression Maps: growth rings grouped into     │   │tool generates it once   │
  │    day bands (1, 2, 4 … 128+), unioned & dated     │   │via create-kml-template  │
  │  • styles copied from the KML template             │<──┤                         │
  │write one compressed KMZ (zipped KML)               │   │consumed by CREATE KMZ   │
  └──────────────────┬─────────────────────────────────┘   └─────────────────────────┘
                     └─> maps/PeriScribe Fires 2026.kmz
```
