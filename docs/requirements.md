# Requirements

## Project: PeriScribe

PeriScribe gathers fire geography from configured ArcGIS feeds, preserves source snapshots, derives cleaned fire histories, calculates fire scores, and produces a symbolized KMZ for Google Earth. The current implementation stores data below `data/<year>/` in the working directory.

## Implemented behavior

The configured fire feeds are:

- CAL FIRE/NIFC perimeters, which retain historical updates.
- WFIGS current perimeters, which retain the latest perimeter for active fires.
- WFIGS current incident locations, which provide fire points.

The pipeline also retrieves California evacuation zones and a nationwide building centroid database. Fire-feed snapshots are append-only GeoPackages. The evacuation layer is kept as its latest GeoPackage, while the buildings source is stored as a compact SQLite database at `sources/buildings.sqlite`.

`update-kmz` performs the following operations:

1. Fetch fire feeds incrementally, plus the external sources.
2. Ensure the administrative-boundary GeoPackage exists at `sources/CA_border_with_AZ_NV_and_OR.gpkg`.
3. Write `derived/history_of_full_geography.gpkg` with `perimeter_history` and `point_history` layers.
4. Write `derived/history_of_differential_geography.gpkg` containing growth rings.
5. Write `derived/fire_scores.json` and `derived/fire_scores_ccdf.png`.
6. Write `maps/PeriScribe Fires <year>.kmz`.

The later steps run when fire data or evacuation data changed, or when `--force` is provided. A failed step stops the pipeline. The KMZ includes active and inactive fire folders, latest perimeters, progression rings, fire information, and score-based top fire views.

## Configuration and operation

Run `peri_scribe --help` for the available commands:

- `update-kmz` runs the end-to-end pipeline.
- `fetch-buildings` and `fetch-evacuations` retrieve individual external sources.
- `ensure-admin-boundaries` retrieves or reuses the administrative boundaries.
- `validate-sources` compares incremental snapshots with complete fresh downloads.
- `show-turbo-colormap` previews or writes the colormap used for progression rings.

The pipeline commands accept an optional year-directory argument; when omitted it defaults to `data/<current year>`. `show-turbo-colormap` instead accepts colormap trim options and an optional PNG output path.

## Future work

Notifications, configurable recipients and delivery rules, and a reporting command remain future requirements.
