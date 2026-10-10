# Lean policy and algorithm proofs

These proofs check selected deterministic policies and mathematical algorithms used by
the pipeline and its supporting data stores. They use Lean's standard libraries, with
no external packages.
The tool version comes from the repository's mise configuration and lockfile; this
directory does not maintain an independent toolchain pin.

Run `mise formal-lean` from the repository root. The task builds every proof and
all executable references registered as default targets in `lakefile.toml`. Run
`mise formal-conformance` to compare executable Lean definitions with the Python
implementation. For direct development, enter this directory under the mise
environment and run `lake build`.

Lake treats warnings as errors. `PeriScribe/Audit.lean` checks the transitive axiom
dependencies of every theorem in the `PeriScribe` namespace. Only Lean's standard
`propext`, `Quot.sound`, and `Classical.choice` are allowed. Project axiom declarations
and any other dependencies fail the build. This also rejects proof placeholders and
proofs relying on native-evaluation trust extensions. The audit is imported by the
default library target and invoked after all domain imports, so an ordinary build
includes it. Add future proof modules to `PeriScribe.lean` before the audit command.

## Coverage and correspondence

The [ownership recomputation inventory](identity_recomputation.md) connects allocation
proofs with complete TLC feedback paths through real checkpoint persistence.
The [anonymous component inventory](component_identity.md) connects distinct source-row
anchors to history selection, scores, reports, map geometry, and durable ownership.
The [numerical policy inventory](numerical_policy.md) adds finite binary64 arithmetic,
fractional quantities, and exact comparisons at unit and tolerance boundaries.
The [update log chronology inventory](../update_log_chronology.md) connects ordered
archive occurrences with the complete projected snapshot reference.
The [output text inventory](output_text.md) connects normalized literal content and
structural encoding proofs with parsed Markdown, HTML, XML, and saved KMZ artifacts.

| Module | Python boundary | Checked guarantees |
| --- | --- | --- |
| `Pipeline` | `pipeline_state.require_stages`, `complete_stage` | Invalidation is exactly the union of previous and requested stages; a later success cannot clear a prerequisite; unconditional work stays forced until the last required stage succeeds. |
| `Pipeline` | `publication.decide` | Missing checkpoints cannot authorize a skip; changed city contents require publication; unchanged inputs stay skipped even when the timer expires; pending data proceeds when the timer expires; skipping requires a valid, unchanged baseline. |
| `AreaPolicy` | `areas.report_can_take_over`, `accepted_reports` | Takeover requires a subsequent report, at least ten acres of growth, and growth beyond a known survey baseline; takeover cannot occur before one day; takeover before three days requires two distinct eligible confirmations; waiting preserves eligibility; confirmed decreases remain eligible. |
| `Reconciliation` | `incidents.simultaneous_updates`, `reconcile_updates` | Each field's winning value keeps its complete supporting evidence; conflicting values follow feed priority; equal reports are idempotent; confirmed evidence survives an unconfirmed duplicate; stale unconfirmed fields cannot revert confirmed measurements, with the explicit acreage-growth exception. |
| `Geography` | `fires.differential.corrected_geometries`, `differential_rows_for_fire` | The optimized reverse-intersection recurrence equals the independent intersection-of-every-later-footprint specification; corrected footprints are nested; growth rings are pairwise disjoint and their union reconstructs the final corrected footprint. |
| `Geography` | `fires.grouping.group_fire_record_indices` | Reachability over symmetric identity/proximity edges is reflexive, symmetric, and transitive; components sharing a record coincide. This proves the component specification, not Python's union-find implementation. |
| `Scoring` | `fires.scoring.tiered_points`, `fire_score_for` | Generic tier bounds and monotonicity under ordered awards; the current tier lists satisfy that ordering; all current nonnegative signal inputs produce a total at most 637 when importance is at most three; increasing independent signals cannot decrease the score. |
| `Scheduling` | `sources.full_fetch_state.full_fetch_is_due` | Zero intervals and missing checkpoints are immediately due; positive intervals do not treat future checkpoints as due; elapsed time preserves eligibility once reached. |
| `Identity` | `fire_updates.matching_name_identities`, `stable_identity`, `history_claims` | Name adoption requires eligible evidence, excludes identifier-reserved histories, and has a unique claimant; existing aliases supply preferred writer keys. |
| `AreaHistory` | `areas.area_history` | The selection fold preserves source evidence and effective event times; fresh surveys restore mapped selection. The executable specification includes accepted reports, distinct confirmations, timestamp ties, and inserted deadlines. |
| `IncidentHistory` | `incidents`, `fires.incident_history` | Complete multi-field histories remain chronological; selected source metadata survives; effective values have earlier same-field support; sparse confirmations have independent ledgers; normalized incident history survives polygon removal. |
| `IdentityOutput` | `fires.sources`, `presentation.selection`, `presentation.history_index`, `presentation.fire_data` | Component and tagged-history ownership, exact eligible observation retention, chronological alias aggregation, and explicit identifier/name fallback boundaries. |
| `SparseEvidence` | `areas`, `presentation.selection`, `presentation.index` | Dated-history precedence, sparse current and historical fallback, missing versus zero, visibility witnesses, and continued qualification after dated corrections. |
| `SpatialIndex` | `point_store.tile_id`, `tile_ids_for_box`, `point_counts_within` | Tile enumeration is complete and duplicate-free; counting across the enumerated tiles equals exhaustive bag counting under the stated containment assumptions. |
| `Grouping` | `fires.grouping.group_fire_record_indices` | Executable class merging computes exactly undirected connectivity, independent of edge order and duplicate edges; parent-pointer operations have explicit representation obligations. |
| `PerimeterVersions` | `perimeters.versions`, `areas` | Revision windows remain anchored; collapsing observations preserves provenance; supersession retains its witness; survey freshness follows the last actual survey. |
| `PublicationCandidates` | `publication` | First captures follow identity components; ambiguous ownership stays conservative; collapsed and stale candidates cannot trigger a mapped-area change; comparison retains the largest absolute signed change. |
| `IncrementalCollection` | `sources.fetching`, `sources.changes` | Selection equals the union of changed, missing, and status-flipped rows followed by content deduplication; completeness has explicit stable-view and observable-edit premises. |
| `PointConstruction` | `point_store`, `buildings` | Tile partitioning preserves each point's multiplicity; chunk boundaries and input ordering preserve the resulting bags. |
| `CacheDependencies` | Prepared history, chart, spatial, and classification cache keys | Complete declared dependencies are necessary and sufficient for sound structured keys; current wrappers remain live. |
| `ComplexOwnership` | `fires.complexes`, source parsing and caches | Latest ownership and explicit releases, parent mergers, aliases, and conservative cycle/tie handling. |
| `RankedViews` | `presentation.score_association`, `presentation.views` | Unique ranked owners retain their winning score; observation windows exclude future evidence. |
| `OutputReferences` | KMZ resources and Markdown report anchors | Allocated names, owner references, and tour targets remain unique and complete. |
| `CacheCodec` | `spatial_data.cache_values` | Tagged trees round-trip injectively, preserve scalar payloads and child order, and reject incomplete or trailing prefix tokens. |
| `BuildingCentroids` | `spatial_data.centroid_math`, `centroid_streaming` | Exact signed moments, orientation, translation, hole subtraction, and feature preservation across streaming chunks. |
| `PerimeterComposition` | Complete perimeter reconciliation | Attribute precedence and source lineage survive the composition; final losses require a rejection witness. |
| `BorderClassification` | Border signals, classification, and source preference | Geometric classification and optimized collection handling follow the declared evidence policy. |
| `MonitorReconstruction` | `monitor.model.append_records`, `phase_tree` | Run context stays isolated; terminal outcomes and skips retain evidence; batch/stream ingestion agrees within the declared retention domain. |
| `SourceDigest` | `sources.digests` | Field framing is injective; schema identity survives empty frames; canonical row order retains multiplicity. |
| `SourceValidation` | `sources.validation.validate_feed` | Indexed success is equivalent to complete relational coverage with unique IDs, every required attribute, and a known matching CRS; extra stored content and input reordering preserve valid coverage. |
| `SpatialOverlap` | `spatial_data.overlaps` | Indexed evacuation-overlap searches agree with exhaustive intersection and streamed batches. |
| `DifferentialRows` | `fires.differential` | Growth blocks retain their final source attribution, sparse deltas retain their baseline, and visible ring sequences preserve order. |
| `CoordinateQuantization` | `spatial_data.point_store` | Signed rounding has a half-step bound; valid coordinates fit stored integers; encoded envelopes retain enclosed stored points. |
| `GeometrySharing` | `spatial_data.geometry_pool` | Every insertion preserves compressed-tree routing and representation; lookup agrees with a finite map; digest width bounds depth for arbitrary insertion histories. |
| `UpdateViewer` | `updates.snapshot_from_entries`, browser row replacement | Complete-prefix baselines under current one-hop ownership, exact visible changes and buckets, immutable original rows, and unique retained node ownership. |
| `LogSeeking` | `log_reading` | Byte-offset binary search equals the independent linear reference for chronological complete records; window selection preserves order and incomplete tails cannot hide complete records. |
| `CoordinateReference` | `arcgis_access.spatial_reference` | Exact magnitude-interval filtering, sound longitude extents, unique candidate selection, and candidate-order independence. |
| `IdentityLifecycle` | `fire_updates.history_claims`, `resolved_ownership`, `acknowledged_state` | Under compatible existing ownership, both adoption phases and fresh allocation assign every fire; acknowledged evidence and consistently reaffirmed aliases survive repeated publications. |
| `NotableViews` | `presentation.views.new_notable_fires` | Complete active-owner percentile, tie admission, signal fallback, discovery windows, and ranked unique selection. |
| `ChartEvidence` | `kml.plot_data`, `svg_charts.time_series` | Independent evidence ledgers agree with complete-prefix search; plotted edges and legends preserve source styles. |
| `RawDecoding` | Raw numeric, text, and timestamp parsing | Typed fallback selects the first usable value; zero remains present; invalid/nonfinite values cannot mask fallback; UTC normalization preserves the instant within calendar bounds. |
| `IdentityTransfer` | `fire_updates.history_claims`, `resolved_ownership`, `acknowledged_state`, `updates.snapshot_from_entries` | Latest mapped claims win all reachable histories; lineage and bucket evidence survive corrections, novelty uses the full inherited union, and one-hop viewer projection preserves immutable records. |
| `PublicationBaseline` | `publication.published_fires` | Repeated displayed rows accumulate aliases while preserving final-row source attribution and actual index inclusion. |
| `IdentityRecomputation` | `fire_updates.resolved_ownership`, `acknowledged_state`, `prepare_updates` | Unchanged inputs reach a fixed point after acknowledgement: writer and owner selection, alias routes, and retained evidence survive any number of subsequent retries. |
| `UpdateLogChronology` | `updates.read_entries`, `write_updates_page` | Archive prefixes precede plain tails; filtering preserves occurrence order and equal-time snapshot predecessors. |
| `OutputText` | `document_text.encoding`, report and KML rendering | Normalized literal text survives encoding while typed structure retains its delimiters, order, and multiplicity. |
| `NumericalPolicy` | `publication.mapping_decision`, `areas.report_can_take_over`, `accepted_reports`, score tiers | Finite binary64 rounding, conversion order, threshold equality, and relative tolerance boundaries follow the declared numerical reference. |
| `ReplayPrefixes` | Formal pipeline replay helpers | Sequential partial execution composes across every prefix and suffix. Reusing a successful prefix preserves the complete result, including failure, when the copied filesystem image and surviving TLC path equal the original state. |

The replay-prefix proof assumes each invocation is a deterministic partial transition
over its complete filesystem image and surviving TLC path. Python conformance checks
must establish exact copy equivalence and compare reused and fresh executions. The
proof does not establish that file-copy operations implement that equivalence or that
unmodeled external state cannot affect execution.

Each statement quantifies over its declared domain; the proofs do not enumerate a
small finite sample. The conformance suite supplies a separate, sampled bridge to
the production implementation, using the same executable Lean definitions appearing
in the proofs. Passing that suite does not establish a full Python refinement proof.

The [domain proof inventory](domain.md) details the identity, complete area-history,
spatial-index, and grouping proofs, their conformance cases, and the `oracleDomain`
protocol.

The [evidence inventory](evidence.md) covers perimeter versions, survey freshness,
publication candidates, and `oracleEvidence`. The [ingestion inventory](../ingestion_extensions.md)
covers incremental collection, point construction, and `oracleIngestion`.
The [complete incident-history inventory](incident_histories.md) covers sequence
reconciliation, field-specific evidence support, and real storage conformance.
The [presentation inventory](presentation.md) covers identity through output and sparse
evidence selection.
The [cache dependency inventory](cache_dependencies.md),
[complex ownership inventory](complex_ownership.md), and
[ranked views and output references](output_references.md) describe their policy and
artifact conformance boundaries.
The [typed codec inventory](cache_codec.md) covers the structured encoding proof and
exact representation fixtures.
The [perimeter composition inventory](perimeter_composition.md) covers complete
reconciliation and border classification, including optimized geometry handling.
The [centroid and monitor inventory](centroids_monitor.md) covers exact footprint
moments, streaming feature preservation, and run/phase reconstruction.
The [source fingerprint inventory](source_digest.md) covers source-change encoding,
schema identity, and row-bag equivalence.
The [source validation inventory](source_validation.md) covers complete stored-content
coverage, unique identifiers, and compatible coordinate references.
The [spatial boundary inventory](spatial_boundaries.md) covers indexed overlaps,
differential-row attribution, and integer coordinate conversion.
The [geometry-sharing and viewer inventory](geometry_updates.md) covers persistent
compressed trees and update history through displayed rows.
The [projected snapshot inventory](projected_snapshots.md) composes current ownership
with exact chronological predecessors, visible changes, and immutable source records.
The [log rotation and seeking inventory](../log_rotation_seeking.md) covers byte-level
reader contracts and their real-file conformance.
The [coordinate-reference inventory](coordinate_reference.md) covers numerical candidate
filtering and reference-selection policy. The
[identity lifecycle inventory](identity_lifecycle.md) covers name adoption and complete
allocation under compatible existing ownership, plus persistent checkpoint evidence. The
[policy detail inventory](policy_details.md) covers complete notable selection and
chart evidence preservation.
The [raw decoding inventory](raw_decoding.md) covers typed field fallback and timestamp
normalization. The [history ownership inventory](identity_transfer.md) covers competing
claims, inherited evidence, durable alias lineage, and current viewer grouping while
preserving original logs. [Publication baselines](publication_baseline.md) extend
visible-source ownership through repeated rows and index membership.

## Explicit assumptions and exclusions

- Geometry is modeled as ideal sets of points. Intersection and difference satisfy
  exact set algebra. GEOS robustness, floating-point slivers, polygon validity,
  geodesic measurement, projection, simplification, and serialization remain outside
  these proofs. Empty rings remain in the original mathematical list; omitting empty
  geometry preserves its union and disjointness. `DifferentialRows` separately proves
  source attribution and sparse deltas through candidate selection and geometric
  omission, with the boundaries in its inventory.
- Most area and score models use nonnegative integer acres/counts; `SparseEvidence`
  also admits signed integer fallback measurements to check filtering and precedence.
  Publication measurements use natural square meters. Area ratios are exact
  cross-multiplied rational comparisons. Time is integer elapsed UTC seconds. The
  default one-day/three-day, 1.25/2.0, and ten-acre policy is modeled. Python floating
  point, unit conversion, fractional acreage, timezone parsing, and customized area
  policies are not proved by these original integer models. `NumericalPolicy`
  separately extends finite arithmetic and selected policy boundaries; its
  [inventory](numerical_policy.md) records the remaining implementation assumptions.
- The original `AreaPolicy` takeover receives the count of **distinct eligible
  confirmation times** after filtering. Its oracle's `reportNewer` field means an
  accepted report exists and was observed after the mapping. `AreaHistory` extends the
  specification through report acceptance, distinct confirmations, deadlines, and the
  complete selection fold. `PerimeterVersions` separately checks survey freshness and
  its fold with explicit geometry-measurement premises. Raw incident extraction and
  configurable numerical policies remain separate implementation boundaries.
- Publication decisions receive the result of mapping comparison as a Boolean.
  Candidate identity matching, reliable measurements, tolerant numeric thresholds,
  maximum-change selection, and `UNCERTAIN_MAPPING` reasons are outside `Pipeline`;
  `PublicationCandidates` now covers the discrete candidate policy with explicit
  numerical abstractions described in its inventory.
  The oracle's positive mapping branch exercises a known area-triggering comparison.
- `Reconciliation` proves local per-field rules; `IncidentHistory` extends them through
  sorting, simultaneous selection, and arbitrary sparse histories. The complete model
  preserves winning metadata and proves separate causal support for effective values
  carried forward from confirmations. It does not prove Python, serialization, or
  external report truth. `stale` means a supplied report time is no later than the
  retained confirmation time.
- Grouping assumes symmetric compatibility edges. The proved executable component
  algorithm is compared with Python's mutable union-find and spatial representative
  optimization. This is not a full Python refinement proof and cannot establish whether
  two source observations describe the same real fire. Timestamps, external feeds,
  storage, hashes, filesystem atomicity, and process scheduling are not verified by
  Lean here; protocol failures are explored separately by the TLA+ models.

## Executable conformance protocol

The build creates `.lake/build/bin/oracle`. It reads one space-separated request per
line from standard input and writes exactly one response line. Boolean values are
`0` or `1`; optional natural numbers use `-1` for missing. Malformed requests fail
with a nonzero exit code. Stage numbers are geography `0`, score `1`, KMZ `2`, and
reports `3`; pending masks use the corresponding bits `1`, `2`, `4`, and `8`.

| Request | Response |
| --- | --- |
| `complete MASK FORCE STAGE` | Remaining mask and force flag after success. |
| `require MASK FORCE REQUESTED_MASK NEW_FORCE` | Combined pending mask and force flag. |
| `gate VALID EVAC_CHANGED CITIES_CHANGED HISTORY_CHANGED PENDING MAPPING_PROCEED TIMER_DUE` | Proceed flag and reason code. |
| `takeover MAPPED REPORTED REPORT_NEWER BASELINE AGE CONFIRMATIONS` | Whether the report can replace the mapping. |
| `accept PREVIOUS CURRENT CONFIRMED` | Whether this acreage report is accepted. Missing previous reports are accepted. |
| `score SIZE GROWTH FIRST_MAPPING BUILDINGS EVACUATION IMPORTANCE` | Weighted total from raw integer acres/counts; importance is awarded points `0..3`. |
| `due INTERVAL HAS_PREVIOUS ELAPSED` | Whether full collection is due. Elapsed seconds may be negative. |
| `winner PREVIOUS_VALUE PREVIOUS_SOURCE PREVIOUS_CONFIRMATION CURRENT_VALUE CURRENT_SOURCE CURRENT_CONFIRMATION` | Winning value, source identity, and confirmation time. |
| `preserve PREVIOUS CURRENT CONFIRMED STALE IS_AREA` | Measurement after stale-edit protection. |
| `corrected MASK ...` | Corrected masks for four abstract cells, one per input observation; masks are `0..15`. An empty history produces an empty line. |

The finite-cell oracle uses Boolean membership. A checked refinement theorem connects
its executable recurrence to the ideal-set recurrence, whose equivalence, nesting,
and ring-partition properties are proved for arbitrary point types and histories.

Gate reason codes are `0` missing publication, `1` evacuation changes, `2` source
history changes, `3` no unpublished data, `4` mapped area change, `5` expired timer,
`6` below threshold, and `7` city reference changes.

Keep the formal definitions, theorem statements, source correspondence, and Python
conformance cases together when behavior changes. A passing old theorem does not
detect a changed Python contract on its own. New policy domains should extend the
stated assumptions and executable oracle before claiming additional coverage.

The [cache-dependency inventory](cache_dependencies.md) covers necessary and sufficient
key completeness, constructive omitted-dependency counterexamples, and real persistent
hit/fresh-result conformance through `oracleCache`.
The [complex ownership inventory](complex_ownership.md) covers current parent ownership
and its executable `oracleComplex` reference.
The [ranked-output inventory](output_references.md) covers ranked views and output
reference integrity through `oracleOutputs`.
