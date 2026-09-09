# PeriScribe

PeriScribe systematically gathers and symbolizes fire geography for fire behavior
analysis and presentation. It preserves source data, builds cleaned fire histories,
scores fires using geographic signals, and produces KMZ maps for Google Earth.

## Current commands

Run `peri_scribe --help` for command help. Pipeline commands that accept an optional
year-directory argument default to `data/<current year>`.

- `run` runs the pipeline fetch → geography → score → kmz → reports. The fetch stage
  fetches all fire and external sources and the administrative-boundary GeoPackage, and
  the later stages rebuild derived geography, fire scores, the year's KMZ, and the fire
  reports; when nothing changed the pipeline ends after fetch. Use
  `--full-fetch-interval` to fetch incremental feeds in full. Use `--unconditional` to
  run all specified stages regardless of data changes. `--only STAGE`, `--from STAGE`,
  and `--to STAGE` run one stage or a range, and `--list-stages` prints the stages with
  descriptions.
- `show-colormap` previews the progression-ring colormap in a compatible terminal or
  writes it to a PNG file.
- `validate-sources` compares incremental feed snapshots with complete fresh downloads
  and leaves validation data for inspection when problems are found.

## Inputs and outputs

Three ArcGIS fire feeds are configured in the package: CAL FIRE/NIFC historical
perimeters, WFIGS current perimeters, and WFIGS current incident locations. Fire-feed
snapshots are append-only GeoPackages under `data/<year>/sources/`; each snapshot keeps
source attributes, geometry, and source coordinate reference system information.

The `run` pipeline writes these outputs:

- `derived/history_of_full_geography.gpkg` — full perimeter and point histories.
- `derived/history_of_differential_geography.gpkg` — corrected growth rings.
- `derived/fire_scores.json` — score and explanation for each qualifying fire.
- `derived/fire_scores_ccdf.png` — score-distribution chart.
- `maps/PeriScribe Fires <year>.kmz` — the Google Earth output.
- `reports/PeriScribe Fires <year>.md` — the fire reports.

The KMZ contains active and inactive fire folders, latest perimeters, progression maps,
fire information, and score-based top-fire views. Styles and placemark behavior are
currently defined in code.

## Pipeline

The `run` command walks the stages in order:

```text
fetch:
    fire feeds, evacuation layer, buildings, and boundaries
        │
        v
geography:
    classify and index fires, derive full and differential history
        │
        v
score:
    fire scores and CCDF chart
        │
        v
kmz:
    symbolized KMZ in maps/
        │
        v
reports:
    fire reports in reports/
```

## Status

The ingestion, validation, history derivation, scoring, KMZ, and reporting pipeline is
built. Notifications remain future work.
