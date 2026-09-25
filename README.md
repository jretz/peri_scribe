# PeriScribe

PeriScribe systematically gathers and symbolizes fire geography for fire behavior
analysis and presentation. It preserves source data, builds cleaned fire histories,
scores fires using geographic signals, and produces KMZ maps for Google Earth.

See the [glossary](docs/glossary.md) for definitions of project concepts.

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
- `show-latencies` displays the combined run-time and source-publication latency
  CDFs inline in compatible image-capable terminals. It defaults to the last week;
  for example,
  `peri_scribe show-latencies data/2026 --start=-3d --end=-1h`. See
  [latency charts](docs/latency_charts.md) for inputs and measurement details.
- `show-colormap` previews the progression-ring colormap in a compatible terminal.
- `validate-sources` compares incremental feed snapshots with complete fresh downloads
  and leaves validation data for inspection when problems are found.

## Generated KMZ

The pipeline writes `data/<year>/maps/PeriScribe Fires <year>.kmz`. Open it in Google
Earth to explore the year's fires, compare recent perimeters, and replay mapped growth.

- **Find fires of interest.** Choose among active and inactive fires, top fires by name
  or score, new and notable fires, Type 1 incidents, fast-growing fires by acres or
  percentage, and fires with the most personnel. Views appear when they contain
  matching fires; “Top Fires by Name” is selected initially when available.
- **Compare recent mappings.** Expand a fire to see its location, up to three recent
  perimeter outlines, and an “Interior” folder of growth rings colored by observation
  day. The rings show how the mapped footprint changed over time.
- **Replay growth.** Play a fire's “Progression” tour to reveal its mapped growth from
  oldest to newest. Select an individual ring to see the area it added.
- **Inspect the details.** Click a fire's placemark or perimeter to see its area and
  measurement basis, containment, personnel, costs, source, and other reported facts.
  Where history is available, charts show changes in area, perimeter and containment,
  costs, and personnel. Area charts distinguish mapped measurements from reported
  estimates.

Available map features and details depend on the source observations. The KMZ also
includes data-source links and attribution.

## Pipeline

A full `run` turns observations from across the United States into fire histories,
rankings, maps, and reports. The stages run from top to bottom; each stage's main
outputs are shown alongside it.

![PeriScribe pipeline stages and their outputs](docs/pipeline.svg)

The pipeline preserves original observations so it can account for later corrections.
It reuses unchanged histories, rebuilds affected fires, and shares the resulting facts
across scores, maps, and reports. The KMZ stage also produces a browser viewer showing
the last 48 hours of mapping updates.

Routine runs skip derived work when fire and evacuation data are unchanged and no
rebuild is pending. Failed work is retried on a later run. The optional
`--publish-threshold` can defer output generation until a mapped-area change or elapsed
time reaches the configured threshold.

See the [architecture and detailed dataflow](docs/architecture.md) for file classes,
network sources, reuse, and recovery behavior.
