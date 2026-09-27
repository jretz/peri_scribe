# Domain algorithms

The four modules below add 44 explicit theorems. `OracleDomain.lean` evaluates their
executable definitions; `oracleDomain` is a default Lake target. Conformance tests use
this binary through the same process adapter as the pipeline oracle. The axiom audit
includes these modules through `PeriScribe.lean`.

## Fire identity ownership

`Identity.lean` corresponds to `fire_updates.matching_name_identities`,
`stable_identity`, and the adoption priority in `history_claims`.

- Candidate eligibility requires a matching normalized name and either empty history,
  matching mapped evidence, or matching current/superseded source references. Reserved
  keys are excluded before local-alias preference is applied.
- Local-alias preference cannot invent candidates. Every selected candidate retains its
  continuity evidence and cannot be reserved.
- Adoption requires exactly one eligible history and no competing claimant. Two distinct
  current fires therefore cannot adopt the same key in one adoption phase.
- Stable identifier selection chooses the first known identifier association. Known
  ownership takes precedence over adoption and allocation.

The model treats normalized names, evidence tokens, and historical keys as exact natural
identifiers. Input history keys and current fire keys must be unique. Conformance builds
real serialized aliases and exercises name normalization, local preference, both matching
ambiguities, correction-source continuity, and reserved histories. It checks 2,524 finite
candidate inputs, plus the complete two-phase resolver on a representative subset.
Additional cases cover direct historical identifier keys, identifier enrichment, renaming,
known-alias priority, retry determinism, and input-order independence.

[Identity lifecycle](identity_lifecycle.md) extends these phase-level theorems to the
complete resolver, sequential fresh allocation, and retained checkpoint evidence across
publications. Existing identifier associations are trusted; conflicting historical
aliases are not proved consistent. Fresh local keys use SHA-256 in Python. Their
collision resistance is an explicit environmental assumption, not a theorem about a
substitute allocator. Conformance treats fresh hashes as opaque keys and checks that
they are distinct from historical and simultaneously allocated keys in exercised cases.
The separate [identity-transfer checks](identity_transfer.md) establish reversible
current ownership while retaining durable evidence, with an executable bridge through
publication, checkpoints, immutable logs, and the viewer.

## Complete area histories

`AreaHistory.lean` corresponds to `areas.accepted_reports`, `report_can_take_over`, and
`area_history`, with the survey classifications produced by `mapping_history` as inputs.
It imports the proved default thresholds from `AreaPolicy.lean`.

The executable definition includes report acceptance, same-time last-observation
selection, distinct confirmation timestamps, mapping freshness, survey-time reported
baselines, continued report ownership, and subsequent survey restoration. It inserts both
policy deadlines when they lie within the observed history, sorts and deduplicates event
times, and folds the resulting events into complete source-attributed estimates.
Confirmation status is independent of timestamp availability: a confirmed report with an
unknown report time contributes one shared unknown confirmation token, matching Python.

Theorems establish preservation of whole evidence records through individual decisions
and the complete event fold. Effective estimate times come from processed events. A fresh
survey restores the mapped estimate even after report takeover. The history-level
no-future-evidence theorem includes timeline construction and sorting: it requires no
caller-supplied chronological premise for the generated event list. The generic fold
version states its chronological premises separately.

Conformance compares all effective times, observation times, acreages, sources, and
provenance against the real `area_history` function in 553 histories. Cases include both
sides of policy deadlines, duplicate timestamps, duplicate confirmations, unknown
confirmation times, report corrections, stale mapping republication, fresh surveys,
empty histories, and histories with only one evidence kind. It exercises real mapping
preparation using controlled geometries, stored measurements, and survey metadata.

The proof domain uses exact integer acres and seconds with the default policy. It does
not prove the geometry or capture-metadata classifier, floating-point measurement, the
upstream incident-reconciliation algorithm, or sparse undated fallbacks in `latest_area`
and `historical_area`. Those remain covered by their separate policies and ordinary
implementation tests. Real numerical conversions are exercised by conformance, with
acreage comparisons allowing the unit-conversion rounding of the Python implementation.

## Grouping and union operations

`Grouping.lean` corresponds to `fires.grouping.group_fire_record_indices` and the edges
supplied by `merge_records_by_name`.

The executable union operation replaces the losing representative class with the winning
class. Its output labels are equal exactly when a finite undirected path connects the
records. This establishes both soundness and completeness over arbitrary finite edge
lists, including duplicate edges and isolated vertices. Edge order and duplication cannot
change component membership. A concrete representative table is proved equivalent to
that operation and is the implementation evaluated by the oracle.

Separate representation lemmas establish that the production parent-root linking and
path-halving operations preserve their representative-class abstraction. They assume the
input parent links already agree with the representative function, and root linking
receives actual roots. These are preservation obligations, not a machine-checked proof
of the full mutable Python loop or its termination. Exhaustive implementation conformance
provides the remaining connection to that loop.

Conformance exercises all graphs through five vertices, every permutation of four-vertex
graph inputs (2,572 total graph cases), and 400 combinations of identifier/name aliases
with missing, empty, identical, nearby, and distant geometries. The graph specification
uses exhaustive pair comparisons, while Python uses its spatial index and identical-shape
classes. The tests compare canonical component membership and require every record to
appear exactly once. GEOS distance predicates, normalization, and STRtree internals are
external numerical/library assumptions.

## Spatial tile queries

`SpatialIndex.lean` corresponds to `spatial_data.point_store.tile_id`, `tile_ids`,
`tile_ids_for_box`, `points_within_box`, and `point_counts_within`.

Coordinates are exact stored integers shifted to a nonnegative WGS84 origin. The model
uses the actual 50,000-unit tile width, 720 columns, 360 rows, and upper-endpoint clamps.
It proves monotone axis assignment, uniqueness of row/column encoding, complete tile
selection for encoded envelope members, and absence of duplicate query tiles. The
concrete counting theorem instantiates the actual tile enumerator and proves that
summing its per-tile bag counts equals exhaustive containment counting. Repeated point
coordinates retain their full multiplicity.

The remaining containment premise is explicit: exact geometry membership must imply
membership in its encoded envelope. Conformance uses rectangular geometries with corners
on stored coordinates to satisfy that premise directly. It checks 3,245 positions around
every world-grid axis boundary and 54 queries over a 144-record bag, including repeated
coordinates, negative coordinates, geographic endpoints, empty matches, and polygon
boundaries. Counting runs against a real temporary SQLite database with production
compression, tile lookup, envelope filtering, and Shapely containment.

The proof covers valid encoded geographic coordinates and query boxes inside that domain.
Coordinate quantization, arbitrary floating-point envelopes, antimeridian interpretation,
GEOS polygon containment, SQLite integrity, compression, and corrupt/missing-database
recovery are outside the arithmetic proof. Conformance exercises those concrete storage
adapters on valid data; it does not claim an unbounded proof of those dependencies.
