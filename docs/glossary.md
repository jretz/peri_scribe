# Glossary

Concepts used in PeriScribe's data, pipeline, code, and outputs. The project's area of
interest is the entire United States; some source feeds and reference datasets are
specific to California. Paths below are relative to a year directory such as
`data/2026/`, unless they link to project files.

## Fires and identity

- **Fire** — One incident assembled from observations across source rows, snapshots,
  and feeds. It has a preferred name, a status, and any known identifiers.
- **Fire record** — A single source row's description of a fire, including its names,
  identifiers, geometry, and observation time. Several records can describe one fire.
- **Canonical identifier** — The preferred identifier for a fire. A unique fire
  identifier shaped like `YYYY-UNIT-######` takes precedence over a GUID, which takes
  precedence over other identifiers. A fire may have no identifier yet.
- **Alias** — Any normalized identifier associated with a fire, including its canonical
  identifier. Aliases keep observations connected when feeds use different identifiers.
- **Normalized name** — A name prepared for comparison by ignoring case, collapsing
  whitespace, and treating hyphens, underscores, and slashes as spaces. Name-based
  grouping also considers geometry and time so unrelated namesakes remain separate.
- **Fire complex** — A source-identified group of related fires. Member fires retain
  their individual identities and a link to the complex.
- **Active / inactive** — The status assembled from source records. A grouped fire is
  active when any of its records is active. This status is separate from its score and
  whether it qualifies for presentation.
- **Border classification** — A fire's relationship to the California boundary, such as
  inside, outside, near, or crossing it. This classification helps reconcile sources;
  it does not define the project's geographic scope.

See [identity models](../src/peri_scribe/models.py),
[source grouping](../src/peri_scribe/fires/grouping.py), and
[data validation and cleansing](architecture.md#data-validation-and-cleansing).

## Sources and observations

- **Feed** — A configured source of fire records. The current fire feeds are the
  CAL FIRE/NIFC historical perimeters, WFIGS current perimeters, and WFIGS current
  incident locations.
- **ArcGIS FeatureServer** — The service interface used to query fire-feed features.
  A feature combines attributes with geometry, such as a perimeter polygon or an
  incident location point.
- **Source snapshot** — An append-only GeoPackage preserving fetched fire-feed records,
  their original attributes, geometry, and coordinate reference system information.
  Snapshots under `sources/` remain authoritative when derived histories are rebuilt.
- **Incremental fetch** — A fetch using a feed's change fields to retrieve updates since
  earlier collection. Retained snapshots preserve observations that current feeds may
  later replace or remove.
- **Full fetch** — A complete download of the current fire feeds. A scheduled full fetch
  also refreshes the fire index and requires a derived rebuild, even if it produces no
  new snapshot. It does not force static reference datasets to download again.
- **Observation time** — When a source says a perimeter or incident observation applies.
  It is distinct from the time PeriScribe downloads the record. Source timestamps are
  normalized to UTC.
- **Provenance** — Evidence connecting a derived value or geometry to its source,
  including snapshot paths, source object identifiers, and observation times. Retained
  provenance also links corrected mapping to its previous update history.
- **Fire index** — The `sources/fires.json` catalog connecting grouped fire identities
  to their source records and classifications. It is distinct from the derived history
  GeoPackages.
- **External source** — A supporting dataset, such as evacuation zones, building
  locations, or major cities, used alongside the fire feeds.
- **Building centroid** — A representative center point computed from a building
  footprint. Nationwide building locations are stored in `sources/buildings.sqlite` as
  compact, quantized point tiles for spatial counting.

See [configured feeds](../src/peri_scribe/sources/feeds.py) and
[data handling](architecture.md#data-handling).

## Geography and histories

- **Perimeter** — A polygon or multipolygon representing a mapped fire footprint at an
  observation time. In this context, the perimeter geometry includes the enclosed area.
- **Point history** — The sequence of incident location observations and their
  attributes. A point supplies location evidence even when no mapped perimeter exists.
- **Incident history** — Reported measurements, including size, costs, personnel, and
  containment, retained independently of perimeter changes. Its rows have null geometry
  and preserve the evidence supporting each measurement.
- **Full geography history** — The cleaned `perimeter_history`, `point_history`, and
  `incident_history` layers in `derived/history_of_full_geography.gpkg`. Full perimeters
  describe each retained footprint before conversion into growth rings.
- **Reconciliation** — Resolving overlapping or competing observations into a consistent
  derived history, including superseded or implausible perimeter updates. Original
  snapshots remain available as evidence.
- **Differential geography history** — The history in
  `derived/history_of_differential_geography.gpkg` whose perimeter layer represents
  growth steps. Later reductions correct earlier footprints before added areas are
  derived; its point layer is copied from the full history.
- **Growth ring / progression ring** — The geometry added at one step of the corrected
  perimeter history, with its observation time. Progression maps color these rings to
  show the sequence of mapped growth. A ring need not be circular or contiguous.
- **Ring area** — The measured area of an individual ring geometry.
- **Displayed added area** — The increase in cumulative covered area when a ring joins
  a particular ordered display sequence. Overlap is counted only once, so this value
  depends on the preceding rings as well as the current ring.
- **Exterior perimeter length** — The combined lengths of the outer boundaries of a
  geometry's polygon parts, excluding the boundaries of interior holes.
- **Coordinate reference system (CRS)** — The definition that gives coordinates their
  location and units. Source CRS information is preserved and interpreted before
  geometry is transformed for derived processing or output.
- **WGS 84** — The geographic reference system used for longitude/latitude geometry in
  shared geodesic measurements and KML output.
- **Geodesic measurement** — Area or length measured on the Earth's reference ellipsoid.
  The shared measurement functions use WGS 84 and return quantities with explicit units.
- **GeoPackage (GPKG)** — A SQLite-based geospatial file with named layers, spatial
  metadata, and attributes. PeriScribe uses it for fire snapshots and derived histories.

See [differential history](../src/peri_scribe/fires/differential.py),
[progression measurements](../src/peri_scribe/perimeters/progression.py), and
[spatial measurements](../src/spatial_data/measurements.py).

## Area selection and scoring

- **Mapped area** — Area measured from a fire's perimeter geometry. A fresh mapping can
  legitimately decrease the current acreage when it corrects an earlier footprint.
- **Reported area** — Acreage supplied by incident reports. It provides size evidence
  when usable mapping is absent and can supersede stale mapping under the area policy.
- **Selected area / current area** — The shared size estimate used by scores, charts,
  balloons, and reports. It follows the mapping-freshness and reporting policy instead
  of simply choosing the largest available number.
- **Area basis** — Whether a selected estimate comes from mapping or reporting, together
  with the supporting observation and its date.
- **Mapping freshness** — Whether survey evidence or a meaningful footprint change
  establishes a recent mapping. Republishing a polygon does not automatically renew
  its freshness.
- **Formal confirmation** — Source report evidence supporting a particular incident
  measurement. Confirmation belongs to that value; it cannot be transferred to a
  conflicting value. Repeated confirmations can support earlier reported-area takeover.
- **Effective time** — When a selected area estimate starts applying. It can be later
  than the supporting observation because a policy deadline must first pass. Charts use
  effective time; source attribution uses observation time.
- **Qualifying area** — The historical selected area used to decide whether a fire can
  appear in maps and reports. The current minimum is 25 acres; a later downward
  correction does not disqualify a fire that previously met it. Sparse records can use
  the policy's undated or supplied-acreage fallbacks.
- **Fire score** — A weighted sum of signals used to rank fires: current size, largest
  single growth step, first-mapping size, nearby buildings, evacuation-zone overlap, and
  incident complexity. The saved score includes an explanation of its contributions.
- **First mapping** — The first retained growth step used for the first-mapping size
  signal. It describes mapped size when first observed, rather than the fire's ignition
  size or discovery time.
- **CCDF** — Complementary cumulative distribution function. The fire-score chart shows
  the share of scored fires with scores greater than each plotted value.

See [area selection](architecture.md#incident-evidence-and-area-selection),
[area policy](../src/peri_scribe/areas.py), and
[scoring](../src/peri_scribe/fires/scoring.py).

## Pipeline, reuse, and recovery

- **Year directory** — The root of one year's source data, derived data, maps, reports,
  logs, and run state. Pipeline commands default to `data/<current year>`.
- **Pipeline stage** — A selectable step in `run`: `fetch`, `geography`, `score`, `kmz`,
  or `reports`. Stage selection can run a single stage or an ordered range.
- **Derived data** — Recomputable results built from source observations, including
  cleaned histories, stored geometry measurements, and scores under `derived/`.
- **Source generation** — A fingerprint of the ordered snapshot paths and contents,
  together with derivation dependencies. A validated unchanged generation can reuse the
  source index and geography without parsing the source snapshots again.
- **Derivation key** — A per-fire fingerprint covering ordered observations, geometry,
  attributes, provenance, identity, complex membership, and derivation dependencies.
  It determines whether that fire's complete histories can be reused.
- **History reuse** — Retaining validated full and differential histories for unchanged
  fires. A changed fire rebuilds its complete history because a correction can affect
  earlier rings. Missing or invalid reuse evidence causes recomputation.
- **Ring sequence digest** — A fingerprint identifying the exact ordered ring geometries
  used to calculate displayed added areas. Stored measurements can be reused only when
  the consumer's sequence matches.
- **Prepared products** — Disposable cached computations in
  `derived/prepared-products.sqlite`, such as classifications, measurements, building
  counts, and rendered fragments. Deleting this cache loses acceleration; authoritative
  source and history files remain separate.
- **Unconditional rebuild** — A run with `--unconditional` that executes the selected
  stages regardless of input changes. When geography is selected, it bypasses prior
  history reuse. Stage selection and static-source download policies still apply.
- **Pending work** — Unfinished derived stages saved in `run_state.json`. A successful
  fetch does not clear this work, allowing later runs to recover from failed or partial
  builds.
- **Atomic publication** — Replacing a completed file as a unit so consumers do not see
  a partially written replacement. Related metadata and recovery records let subsequent
  runs validate or recover interrupted publication.

See [pipeline usage](../README.md#pipeline),
[publication reuse](architecture.md#publication-reuse-and-performance), and
[recovery and scheduling](architecture.md#recovery-and-scheduling).

## Presentation and updates

- **KML / KMZ** — Keyhole Markup Language describes map features, styles, and folders;
  KMZ packages KML and related assets in a compressed archive. PeriScribe produces a
  yearly KMZ for Google Earth with latest perimeters and progression maps.
- **Placemark / balloon** — A selectable KML feature and its associated information
  display. Fire balloons contain descriptions, measurements, and charts.
- **Fire summary** — Shared prepared facts used by maps and reports, including selected
  area, histories, and descriptive information. Output-specific rendering builds on
  these common facts.
- **Interesting fire** — For update logging, a fire selected into any report section
  before Fire Details. This selection determines which newly mapped perimeters are
  logged after successful KMZ generation.
- **Fire update** — A newly mapped perimeter recorded after successful KMZ generation.
  Report edits or ranking changes alone do not generate one. Monthly records live in
  `logs/YYYY-MM-fire-updates.jsonl`, with older months eventually compressed.
- **Log identity** — A stable key linking a fire's update records across name changes,
  identifier enrichment, and mapping corrections. It preserves acreage history while
  keeping unrelated fires with reused names separate.
- **Checkpoint / baseline** — Saved acknowledgement of mapped perimeters in
  `derived/fire_updates_state.json`. The next publication uses it to identify new
  updates; a pending recovery journal coordinates log and checkpoint writes.
- **Update viewer** — The `maps/updates.html` page and adjacent `updates.json` showing
  nonzero mapped-acreage changes from the preceding 48 hours. Each change compares a
  record with its previous logged acreage and can be positive or negative.

See [shared fire presentation](architecture.md#shared-fire-presentation),
[update behavior](requirements.md#implemented-behavior), and
[viewer setup](development_tools.md#fire-update-viewer).
