# Architecture

## Form

PeriScribe is a command-line application. `src/peri_scribe/main.py` defines the CLI and
coordinates the pipeline; domain logic is divided among source retrieval, geography
processing, fire scoring, and KML modules.

The top-level packages express reusable responsibilities. They ship together in the
same distribution, with one dependency set and release cycle:

- `peri_scribe` owns feeds, fire schemas, reconciliation, scoring, download and refresh
  policy, pipeline logging, reports, and map composition.
- `spatial_data` owns geometry transformation and interning, geodesic measurements,
  coordinate systems, bounded layer reads and GeoPackage writes, streamed polygon
  centroids, indexed overlap queries, and compact tiled point storage.
- `arcgis_access` owns FeatureServer metadata and feature queries, retries, conversion
  to GeoDataFrames, and interpretation of ambiguous ArcGIS spatial-reference metadata.
  Callers supply request identity, timeouts, layer names, and geometry-column names.
- `svg_charts` owns generic time-series and distribution plots, chart models, drawing,
  and SVG metrics. Callers supply labels, values, units, colors, line styles, and
  annotations; fire measurement and provenance decisions stay in the application.
- `kml_io` owns streaming KML document and folder envelopes, geometry serialization and
  caching, generic styles, timed reveal tours, and atomic KMZ publication.
- `measurement_units` owns the single Pint registry, including the currency unit shared
  by application observations and library calculations.
- `aircraft_registration` owns offline recognition of trailing civil registrations,
  using ICAO-notified marks and sourced national overrides. Its dataclass preserves
  the caller's prefix and the normalized tail number. See the
  [recognition rules and sources](aircraft_registration.md) for coverage and exceptions.

These libraries do not import `peri_scribe`. `arcgis_access` uses `spatial_data` for
coordinate systems; geometry measurements and charts use `measurement_units`. Package
initializers expose no rendering or spatial I/O backends, so callers import the modules
they need. Import-boundary tests enforce these dependencies.

### Spatial package boundary

Geospatial primitives and spatial streaming/storage share one `spatial_data` package.
The storage paths already depend directly on coordinate-system construction, geometry
conversion, and projection-aware centroid math. The pure foundation is small, and a
second package would add another API boundary without separating an independent
workflow. Individual modules keep pure geometry and measurements apart from layer I/O,
stream parsing, and point storage; a caller can use the former without importing the
latter.

The trade-off is a broader spatial package whose I/O modules require heavier libraries.
The distribution still installs the complete application's dependencies; this extraction
does not create separately installable products or optional dependency sets. A future
consumer that needs only geometry could justify splitting the pure modules then.

Point storage accepts WGS84 points and retains its existing coordinate quantization,
tile layout, metadata, compression, and database schema. Building dataset URLs,
concurrent downloads, cooperative cancellation, validation before atomic publication,
and refresh policy remain in `peri_scribe/sources/buildings.py`.

### Shared fire presentation

`peri_scribe/presentation/` owns fire qualification, prepared histories, summary facts,
ranking, row selection, and descriptive text shared by reports and maps. Its
`FireSummary` contains facts without rendered images. Both output paths use this layer;
reports do not import KML modules or chart rendering through it.

`peri_scribe/kml/` supplies map folders, balloon HTML, colors, progression timing, and
fire-specific chart preparation. It adds images to shared summaries and passes neutral
geometry, styles, and playback durations to `kml_io`. `peri_scribe/report/` supplies
Markdown layout and report-specific location descriptions. Pipeline phase logging stays
with the application adapters.

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

`fire_updates.py` prepares fire-update records from the same in-memory summaries used
by the KMZ, reusing report selection and location descriptions. After successful KMZ
generation it appends to `logs/YYYY-MM-fire-updates.jsonl` and saves
`derived/fire_updates_state.json`. This baseline includes all eligible fires, including
those outside the report's interesting sections. Normalized geometry and observation
time identify new perimeters; pending updates survive unsuccessful KMZ generation.
Known identifier aliases retain the fire's first checkpoint and log identity, so adding
a preferred identifier preserves its mapping baseline and acreage history. A first
identifier joins a name-only history only when shared mapping evidence identifies a
unique current fire and that history is not already claimed. Name matching uses the
same normalization as source grouping. Known identifiers keep ownership of their
histories; unrelated namesakes receive deterministic `local` identities. The checkpoint
retains historical name associations even when a later fire reuses a name. Each record
preserves its identity in `log_identity`, independently of its current display name.
The checkpoint also retains exact source snapshot and object-ID references, including
superseded rows preserved by reconciliation. These references link corrected perimeters
to their acknowledged history when the original geometry has been replaced. Missing
provenance supplies no identity evidence; older checkpoints acquire it during an
unchanged publication. Provenance-only changes update the checkpoint without logging
another mapping update.
Snapshot acreage comparisons and viewer fire counts use this key; records without it
use their logged identifier or name. A recovery journal at
`derived/fire_updates_pending.json` retains the completed batch and original timestamp
until its log and checkpoint are both saved. Each batch has a `batch_id` and is appended
atomically; retries recognize it in plain or compressed logs before advancing the
checkpoint. Recovery runs before comparing the next build's inputs.
The monthly log writer shares locking, timestamps, and Zstandard compression across
diagnostic and fire-update logs while rotating each series independently. Closed months
remain uncompressed until seven local calendar days after the next month starts; the
next write compresses eligible months. The monitor reads the diagnostic series.

`updates.py` reads the fire-update series, validates its records, and compares each
record with its chronological predecessor before selecting the last 48 hours. It writes
`maps/updates.json` atomically with explicit previous acreage, including history older
than the visible window. The KMZ builder invokes it after appending the fire-update log;
an output failure keeps the pipeline stage pending for retry without repeating already
acknowledged perimeters. Missing history, including missing months, contributes no
previous acreage. Invalid logs leave the previous JSON output intact.

The packaged `updates.html` is copied beside the JSON only when its content changes.
It fetches the JSON immediately and checks for changes with HEAD every 10 seconds.
The check compares ETag when available, otherwise Last-Modified and Content-Length,
against the last successfully displayed GET response. Only a matching strong ETag
allows indefinite reuse. Weak ETags and modification time/size metadata expire after
five minutes, when the next HEAD check also downloads the JSON to catch collisions.
Changed or missing metadata, or HEAD responses with status 405 or 501, trigger a GET.
Failed requests and invalid snapshots preserve the displayed data for later retry.

The viewer retains the name filter and each group's sorting and collapsed state when
applying a snapshot. Retained row elements support animated additions, sorting, bucket
changes, and expiry without resetting highlight transitions. A move between an open
and closed group animates to or from the closed header; moves between two closed groups
skip animation. The browser clock controls aging and highlighting. Local preview uses
the same HTTP loading path as production through the `serve-updates` mise task.

New records in initial or refreshed snapshots start a 30-second favicon notification
when their rows match the current filter, belong to an expanded group, and are less than
15 minutes old. The green circle fades in and out every five seconds in foreground and
background tabs. Favicon images are generated in memory and cleared after the final
pulse; the viewer does not require favicon files. Additional qualifying records restart
the notification.

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

## Publication reuse and performance

`execution.py` shares source grouping and classification across indexing and geography,
then shares derived frames, area histories, and summaries across scoring, KMZ, and
reports. Source objects are released after geography; remaining references are released
at scope exit, including failures. Standalone stages use the same lifecycle.

`preparation.py` manages disposable products in `derived/prepared-products.sqlite`:
classifications, histories, descriptions, spatial measurements, buffers, building
counts, SVGs, and KML boundaries. Keys cover exact relevant inputs, policies, code, and
runtime dependencies. Invalid or unavailable products fall back to computation.
Deleting the database only loses acceleration. SQLite's page cache is 8 MiB and the
KML fragment cache retains at most 16 MiB of accounted values; neither bounds total RAM.
Old runtime contexts remain on disk.

Complete source generations hash ordered snapshot paths and bytes plus derivation
dependencies. Parsed source records also validate snapshot content checksums. An
unchanged, fully classified generation can retain its source index and geography
without parsing sources or rewriting GeoPackages. Output checksums and complete layer
signatures authenticate reuse; replacement files are published atomically before their
`.reuse.json` metadata. `--unconditional` bypasses reuse of prior outputs and refreshes
the fire index when rebuilding geography.

Changed generations still read and group all sources. Each fire's `derivation_key`
covers all ordered observations, geometry, attributes, provenance, identity, complex
membership, and derivation dependencies. Matching fires retain full and differential
histories; affected fires rebuild their complete histories. Dense reuse reads whole
GeoPackage layers; sparse reuse can use a lazy row index bound to the published file's
checksum and exact normalized values. Published GeoPackages remain authoritative.

Consumers share stored geometry area, exterior perimeter, and added-area measurements;
ring measurements require a matching ordered `ring_sequence_digest`. Scores, rankings,
time-dependent selection, and complete publication assembly still run against current
inputs.

Offline Mac benchmarks on 23 September 2026 reduced warm unchanged publication medians
from 132.31 to 26.84 seconds (4.93×; two trials), with maximum measured peak RAM falling
from 1.804 to 0.845 GB. One incident-only update improved from 123.72 to 45.67 seconds
(2.71×).
Application outputs matched an unconditional build of the original code on this Mac,
excluding container metadata, batch UUIDs, and internal fingerprints. These measurements
exclude live collection and predate subsequent correctness fixes. Local evidence is in
`data/profiling/2026-09-23-implementation`.

Reaching 10× still requires less full-history loading and reconstruction in consumers,
plus incremental source grouping for changed runs. A 100× target would require broader
reuse of completed artifacts or precomputed output pieces; neither target is established
by these measurements.

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
