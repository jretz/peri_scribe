# Architecture

## Form

PeriScribe is a command-line application. `src/peri_scribe/main.py` defines the CLI and
coordinates the pipeline; domain logic is divided among source retrieval, geography
processing, fire scoring, and KML modules.

The primary workflow is:

```text
fetch fire feeds, external sources, and administrative boundaries
    ↓
derive geography history
    ↓
score fires
    ↓
create KMZ
    ↓
write fire reports
```

`run` organizes these steps into the stages fetch, geography, score, kmz, and reports.
It skips the derived outputs when no fire or evacuation data changed, unless
`--unconditional` is supplied; `--only`, `--from`, and `--to` select one stage or a
range of stages, and `--list-stages` prints the stage descriptions. `validate-sources`
is a separate diagnostic workflow that performs a complete fetch and compares it with
the incremental snapshots.

## Data handling

Fire-feed data is kept close to the source format: source attributes, geometry, source
coordinate reference systems, and observation metadata are retained in the snapshot
GeoPackages. Snapshots are stored under:

`data/<year>/sources/<feed>/<serial-bucket>/<serial>,lastEdit=<timestamp>.gpkg`

The fire index is stored at `sources/fires.json`. External datasets are stored beside
the fire snapshots: the latest evacuation layer is `sources/evacuations.gpkg`, and
building locations are in `sources/buildings.sqlite`. The buildings converter streams
the Microsoft USBuildingFootprints state archives into quantized centroid tiles and does
not retain the downloaded archives. The administrative-boundary GeoPackage at
`sources/CA_border_with_AZ_NV_and_OR.gpkg` holds the California border with Arizona,
Nevada, and Oregon; the fetch stage ensures it exists, downloading and computing it only
when it is missing or unusable.

Derived data is written below `data/<year>/derived/`:

- `history_of_full_geography.gpkg` contains perimeter and point histories.
- `history_of_differential_geography.gpkg` contains corrected growth rings.
- `fire_scores.json` contains one score and explanation per fire.
- `fire_scores_ccdf.html` plots the score distribution.

The KMZ is written to `data/<year>/maps/PeriScribe Fires <year>.kmz` and the fire
reports to `data/<year>/reports/PeriScribe Fires <year>.md`.

## Data validation and cleansing

Source coordinate reference systems are interpreted from feed metadata, with checks for
coordinate scale where feeds are inconsistent. Derived processing classifies sources
against the California border, reconciles competing perimeter records, removes
implausibly small perimeter updates, and cleans geometry for KML. Differential history
subtracts later perimeters so shrinkage does not appear as fire growth.

The original source snapshots are not modified by these cleansing steps. The output KMZ
excludes fires without a qualifying area indication and includes latest-perimeter and
progression-map views.

## Libraries

ArcGIS is used for FeatureServer access; GeoPandas, Shapely, pyproj, and pyogrio support
geospatial processing and GeoPackages; Pydantic validates serialized documents; Click
implements the CLI.

## Future work

Notifications are not implemented yet.
