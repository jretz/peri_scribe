# Architecture

## Form

PeriScribe is a command-line application. `src/peri_scribe/main.py` defines the CLI and
coordinates the pipeline; domain logic is divided among source retrieval, geography
processing, fire scoring, and KML modules.

The primary workflow is:

```text
fetch fire feeds and external sources
    ↓
classify and index fires
    ↓
derive full history
    ↓
derive differential history
    ↓
score fires
    ↓
create KMZ
```

`update-kmz` skips the derived outputs when no fire or evacuation data changed, unless
`--force` is supplied. `validate-sources` is a separate diagnostic workflow that
performs a complete fetch and compares it with the incremental snapshots.

## Data handling

Fire-feed data is kept close to the source format: source attributes, geometry, source
coordinate reference systems, and observation metadata are retained in the snapshot
GeoPackages. Snapshots are stored under:

`data/<year>/sources/<feed>/<serial-bucket>/<serial>,lastEdit=<timestamp>.gpkg`

The fire index is stored at `sources/fires.json`. External datasets are stored beside
the fire snapshots: the latest evacuation layer is `sources/evacuations.gpkg`, and
building locations are in `sources/buildings.sqlite`. The buildings converter streams
the Microsoft USBuildingFootprints state archives into quantized centroid tiles and does
not retain the downloaded archives.

Derived data is written below `data/<year>/derived/`:

- `history_of_full_geography.gpkg` contains perimeter and point histories.
- `history_of_differential_geography.gpkg` contains corrected growth rings.
- `fire_scores.json` contains one score and explanation per fire.
- `fire_scores_ccdf.png` plots the score distribution.

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
implements the CLI; and Pillow/matplotlib support generated KML imagery and score
visualization.

## Future work

A reporting command and notifications are not implemented yet.
