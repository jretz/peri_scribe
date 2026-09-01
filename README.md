# PeriScribe

PeriScribe systematically gathers and symbolizes fire geography for fire behavior analysis and presentation. It preserves source data, builds cleaned fire histories, scores fires using geographic signals, and produces KMZ maps for Google Earth.

## Current commands

Run `peri_scribe --help` for command help. Pipeline commands that accept an optional year-directory argument default to `data/<current year>`.

- `update-kmz` fetches all fire and external sources, rebuilds derived geography and scores when needed, and writes the year's KMZ. Use `--force` to fetch incremental feeds in full and rebuild all later outputs.
- `fetch-buildings` builds `sources/buildings.sqlite` from the Microsoft USBuildingFootprints state archives. The archives are streamed and not retained.
- `fetch-evacuations` retrieves the latest California evacuation-zone layer into `sources/evacuations.gpkg`, retaining the existing version if a refresh fails.
- `ensure-admin-boundaries` retrieves or reuses `sources/CA_border_with_AZ_NV_and_OR.gpkg`.
- `validate-sources` compares incremental feed snapshots with complete fresh downloads and leaves validation data for inspection when problems are found.
- `show-turbo-colormap` previews the progression-ring colormap in a compatible terminal or writes it to a PNG file.

## Inputs and outputs

Three ArcGIS fire feeds are configured in the package: CAL FIRE/NIFC historical perimeters, WFIGS current perimeters, and WFIGS current incident locations. Fire-feed snapshots are append-only GeoPackages under `data/<year>/sources/`; each snapshot keeps source attributes, geometry, and source coordinate reference system information.

The pipeline writes these derived files:

- `derived/history_of_full_geography.gpkg` — full perimeter and point histories.
- `derived/history_of_differential_geography.gpkg` — corrected growth rings.
- `derived/fire_scores.json` — score and explanation for each qualifying fire.
- `derived/fire_scores_ccdf.png` — score-distribution chart.
- `maps/PeriScribe Fires <year>.kmz` — the Google Earth output.

The KMZ contains active and inactive fire folders, latest perimeters, progression maps, fire information, and score-based top-fire views. Styles and placemark behavior are currently defined in code.

## Pipeline

```text
ArcGIS fire feeds ───────────────┐
evacuation layer + buildings ────┼─> fetch and store source data
administrative boundaries ───────┘                │
                                                  v
                                      index and classify fires
                                                  │
                                                  v
                                       full geography history
                                                  │
                                                  v
                                     differential growth history
                                                  │
                                                  v
                                     fire scores and CCDF chart
                                                  │
                                                  v
                                       symbolized KMZ in maps/
```

## Status

The ingestion, validation, history derivation, scoring, and KMZ pipeline is prototyped and actively maturing. A reporting command and notifications remain future work.
