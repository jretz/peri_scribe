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
After fetch, it skips the derived outputs only when no fire or evacuation data changed
and no rebuild is required. A scheduled full fetch requires an unconditional derived
rebuild, even when it writes no new snapshot. `--unconditional` forces the selected
stages to run and bypasses prior history reuse when geography is selected; `--only`,
`--from`, and `--to` select one stage or a range of stages, and `--list-stages` prints
the stage descriptions. `validate-sources` is a separate diagnostic workflow that
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
not retain the downloaded archives. The administrative-boundary GeoPackage at
`sources/CA_border_with_AZ_NV_and_OR.gpkg` holds the California border with Arizona,
Nevada, and Oregon; the fetch stage ensures it exists, downloading and computing it only
when it is missing or unusable.

Derived data is written below `data/<year>/derived/`:

- `history_of_full_geography.gpkg` contains `perimeter_history`, `point_history`, and
  `incident_history`.
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

## Incident evidence and area selection

`fires/incident_history.py` derives reporting history from original observations before
perimeter reconciliation can remove unchanged or superseded polygons. Incident fields
use their incident modification time. Rows contain normalized measurements, report
confirmation, and source provenance, with null geometry. Measurements at the same time
can occupy separate rows when different reports support them. Direct location values win
conflicts; matching values can retain formal confirmation from either feed.

`incidents.py` reconciles those measurements independently of mapping. `areas.py` uses
that reporting history and mapping evidence to select current and historical area for
scoring, KMZ qualification, plots, and descriptions. Survey metadata or a footprint
change of at least both 1% and one acre renews mapping freshness. Ordinary reported
growth can take over after three days when it reaches both 1.25 times mapped area and an
additional ten acres, and exceeds the report known at the survey. Rapid growth can take
over after one day with two distinct formal confirmations at twice mapped area, subject
to the same absolute increase and subsequent-growth requirements.

Fresh surveys restore measured area, including legitimate decreases. Estimates retain
separate effective and observation times because an eligibility deadline can occur after
the supporting report. Source times are normalized to UTC; naive source timestamps are
interpreted as UTC. Displayed provenance dates refer to the observation, while charts
place estimates at their effective times. Growth and first-mapping signals use geometry
independently of the selected current area. Area quantities carry their units; consumers
convert explicitly rather than assuming acres or square meters.

## History reuse and shared measurements

The geography stage reads and groups all source observations before deciding which fires
can reuse previous results. Each fire's `derivation_key` covers its complete ordered
source records, geometry, attributes and provenance, including observations discarded
during reconciliation. It also covers fire identity and complex membership, package
source code, relevant geospatial library versions, boundary data, and cleaning,
size-filtering, and classification settings.

Matching fires retain their full point, perimeter, and incident rows and differential
history. Incident reuse uses the complete source fingerprint, so a report edit
invalidates it even when the polygon is unchanged. Other fires are classified and
reconciled in full, and their complete differential sequences are rebuilt. Appended
observations, shrinking corrections, late observations, metadata edits, removed records,
and grouping changes can affect earlier output, so reuse is decided for a whole fire
rather than an appended ring suffix. Source reading and global grouping remain work on
every geography run.

Full perimeter rows store `geometry_area_square_meters` and `exterior_perimeter_meters`
for the cleaned shape. Differential rows store ring area and `added_area_square_meters`,
which measures newly covered ground in the cumulative union of dated, visible rings. A
`ring_sequence_digest` identifies the exact ordered geometries used for that
calculation. Downstream scoring, KML, and report consumers share these measurements.
When a consumer uses a different ring sequence or receives rows without stored
measurements, it computes the measurements it needs. Scores, rankings, and presentation
are regenerated to reflect external inputs and current time.

Within each KMZ or report stage, prepared fire histories hold reconciled incident
updates, the selected area timeline, and current and historical size. Qualification,
charts, containment estimates, and descriptions share that evidence so JSON parsing,
report reconciliation, and footprint comparisons are performed once per fire.

`fires/reuse.py` validates each prior GeoPackage against its sibling `.reuse.json` file,
which contains a cache version and the completed file's checksum. Missing, incompatible,
corrupt, or edited cache data causes a miss. Each replacement GeoPackage is generated in
a temporary directory beside its destination, then atomically replaces the destination
before its checksum metadata is published. An interrupted publication cannot validate
mismatched geometry and metadata. Full and differential files are published separately;
their per-fire derivation keys determine whether rows are reusable.

An unconditional geography rebuild bypasses both prior history files and refreshes the
fire index from the grouped sources. Existing parsed source-record caches retain their
own validation rules. Static sources retain their existing download policy.

## Recovery and scheduling

`--full-fetch-interval` compares the last successful full-fetch time in
`sources/fetch_state.json` with the requested interval. The first run with the option
fetches in full. A full fetch refreshes `sources/fires.json` even if it writes no new
snapshot.

`pipeline_state.py` stores unfinished derived stages and their unconditional rebuild
requirement in `data/<year>/run_state.json`. A scheduled full fetch records that
requirement before fetching. Fetch failures, changed fire snapshots, and evacuation
changes also leave downstream work pending. Completing the fetch updates its timestamp
without clearing pending derived work, so a later incremental fetch with no changes
still allows a failed rebuild to be retried.

Successful stages clear pending work in prerequisite order; running a later stage alone
cannot clear an unfinished prerequisite. Partial stage selections leave un-run
requirements pending. Stage selection is respected even with `--unconditional`, so a run
starting at KMZ consumes the existing geography. Recovery state is replaced atomically,
and invalid state requires a full derived rebuild.

The `run` command holds an operating-system lock on `data/<year>/.run.lock` for its
selected stages. A competing invocation logs a skip and exits successfully. The lock is
released when the owning process exits, including after failure; the persistent lock
file itself does not indicate that a run is active.

## Libraries

ArcGIS is used for FeatureServer access; GeoPandas, Shapely, pyproj, and pyogrio support
geospatial processing and GeoPackages; Pydantic validates serialized documents; Click
implements the CLI.
