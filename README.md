# PeriScribe

PeriScribe systematically gathers and symbolizes fire geography for fire behavior
analysis and presentation. It preserves source data, builds cleaned fire histories,
scores fires using geographic signals, and produces KMZ maps for Google Earth.

## Current commands

Run `peri_scribe --help` for command help. Pipeline commands that accept an optional
year-directory argument default to `data/<current year>`.

- `run` runs the pipeline (fetch → geography → score → kmz → reports). The fetch stage
  fetches all fire and external sources and the administrative-boundary GeoPackage, and
  the later stages rebuild derived geography, fire scores, the year's KMZ, and the fire
  reports. The pipeline ends after fetch when nothing changed and no rebuild is pending.
  `--full-fetch-interval` periodically fetches fire feeds in full and forces a
  derived rebuild, even without new data. `--unconditional` rebuilds the selected stages
  regardless of changes and bypasses history reuse when geography is selected. `--only
  STAGE`, `--from STAGE`, and `--to STAGE` run one stage or a range, and `--list-stages`
  prints the stages with descriptions.
- `show-colormap` previews the progression-ring colormap in a compatible terminal.
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
- `derived/fire_scores_ccdf.html` — score-distribution chart.
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
    reuse unchanged fires, derive changed histories and shared measurements
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

Geography reuses complete full and differential histories for fires whose inputs and
derivation settings match the previous run. A changed fire's entire history is rebuilt,
including earlier rings that a correction may affect. Area and exterior-length
measurements are stored with the geometry and shared by scoring, maps, and reports.
Missing, incompatible, or damaged reuse data causes recomputation automatically.

To recompute all geography from stored inputs, use `peri_scribe run --only geography
--unconditional`. Starting at a later stage uses the existing geography. Neither
`--unconditional` nor a scheduled full fetch forces static sources such as buildings to
be downloaded again.

## Status

The ingestion, validation, history derivation, scoring, KMZ, and reporting pipeline is
built. Notifications remain future work.
