# Incremental collection and buildings construction

These specifications extend the [ingestion recovery contracts](tla/ingestion.md).
They separate content selection, encoded point preservation, and the lifetime of the
workers and files used to build a database. The existing `FetchCrash`, `FeedCache`, and
`WorkerLifetime` models retain ownership of their recovery and cancellation contracts.

## Incremental collection completeness

[IncrementalCollection.lean](lean/PeriScribe/IncrementalCollection.lean) specifies the
union of changed IDs, missing IDs, and stored-active IDs now carrying a known inactive
status. It proves that retrieving that union and dropping identical content equals a
single declarative eligibility filter. It proves unique collection under unique source
IDs, full-fetch completeness without a timestamp eligibility premise, and incremental
completeness when every real edit is observable through at least one selection route.
The latter premise is a provider requirement, not a proved fact about a remote feed.

The timestamp definitions model the maximum across every configured stored change
column, subtracting the overlap or using the epoch when none is available. Proofs show
that the maximum includes every supplied time and cannot exceed their upper bound;
null current timestamps and the inclusive overlap boundary select their rows. A separate
metadata policy proves that full collection bypasses the existing-snapshot shortcut.

Implementation owners are:

- `sources/fetching.py::{fetch_feed_dataframe,fetch_feed_snapshot}` for query assembly,
  retrieval, and the metadata shortcut.
- `sources/feed_state.py::{where_clause_for,stored_object_ids,stored_status_object_ids,
  stored_status_literals}` for source predicates and stored selection facts.
- `sources/changes.py::{latest_modified_datetime,incremental_cutoff,
  drop_features_already_present,features_are_identical}` for time and content comparison.

`test_incremental_collection.py` calls the compiled definitions through
`oracleIngestion`. It compares 514 stored/current scenarios with actual
`fetch_feed_dataframe`, including a SQLite-backed evaluator of the emitted SQL and real
ArcGIS FeatureSet-to-dataframe conversion. Cases combine missing/present IDs, active and
inactive statuses with and without a known inactive spelling, before/at/after-overlap
and null timestamps, changed attributes, changed point geometry, and full/incremental
fetches. It checks returned contents as well as selected IDs. Empty incremental results
return no work; an empty full source is an explicit source error, not a deletion record.
Further checks cover all 64 three-column null/boundary combinations, 256 high-water
vectors distributed across rows and columns, and all four metadata/full combinations
using actual temporary snapshot filenames.

The proofs assume a stable source view across the separate ID and content queries,
unique object IDs, and a stable compared attribute schema. Lean rows represent already
normalized attributes and geometry equivalence classes; Lean does not verify timestamp
parsing, floating-point geometry, Shapely, pandas, or ArcGIS/SQLite SQL equivalence.
The conformance cases exercise real point geometry and date handling. Source deletion
is not collected: snapshots preserve historical observations. An old-timestamp edit
outside all selection routes can be missed; an active-to-inactive change with a newly
introduced raw status spelling is not covered by the known-literal query. Full collection
is required to discover such edits. Metadata skipping additionally assumes that a
provider's last-edit marker changes whenever relevant content changes. The tests do not
claim that an unchanged marker proves unchanged content or that racing queries form a
transaction. These are explicit limits, not new verified guarantees.

## Encoded point construction

[PointConstruction.lean](lean/PeriScribe/PointConstruction.lean) reuses the existing
`SpatialIndex` integer tile function. It defines partition routing by tile modulo 16,
partition filtering, occupied tile enumeration, and tile assembly. It proves:

- Every record for a tile reaches the same partition, and partition IDs are bounded.
- Each constructed tile equals exhaustive filtering of the original point list.
- Every input record has an occupied row, keys are unique, occupied rows are nonempty,
  and no row gains foreign records.
- Multiplicity is preserved, including coincident duplicate points.
- Arbitrary chunk boundaries and arbitrary input permutations preserve the tile bags.

Implementation owners are
`spatial_data/point_store.py::{PartitionFiles,append_centroids_to_partitions,
process_partition,build_tiles_database,compress_tile_points,decode_payload}`.
`test_point_construction.py` compares actual partition file records, SQLite tile keys,
building counts, and decompressed payload multisets against Lean output. It exercises
six bags at three chunk sizes, with concurrent real append calls, empty input,
duplicates, all partition residues, several tiles sharing a partition, grid edges,
world endpoints, and different input orders.

The proved domain starts with encoded integer WGS84 coordinates (offset to naturals in
Lean). Quantization, projection, geometry centroid calculation, byte encoding, NumPy
sorting, zstd, SQLite, and the filesystem remain trusted implementation boundaries;
conformance checks these construction operations on the documented finite fixtures.
This is a preservation guarantee for the supplied records, not a guarantee that upstream
archives contain every building or that a geometric centroid is the desired location.

## Buildings database construction lifecycle

[BuildingsConstruction.tla](tla/BuildingsConstruction.tla) separates worker admission,
append start/completion, worker exit, failure observation, task-group cancellation,
database construction, validation, publication, and cleanup. Worker failure and the
parent noticing that failure are distinct: releasing a failed worker's semaphore can
admit a queued worker before cancellation is delivered. An append already in flight may
finish after cancellation; staging must survive until that worker exits.

The safety and liveness configurations each explore 6,588 states with three workers,
two permits, and one abstract record chunk per worker. Cases cover absent, invalid, and
accepted existing outputs; success; each archive failure position before and after
partial conversion; external cancellation;
and failures at build, validation, and replacement. Invariants require bounded concurrency,
live-worker ownership of staging, complete successful collection before building,
validated complete construction before publication, and preservation of the previous
output on failure. Liveness assumes weak fairness of the remaining worker, cancellation,
build, validation, replacement, and cleanup steps. A blocking native call that never
returns is outside that progress guarantee.

The owner is `sources/buildings.py::{stream_one_archive,stream_state_archives,
fetch_buildings_database}`, using the separately checked `concurrency.py::run_blocking`
and `point_store.PartitionFiles`. `test_buildings_construction.py` obtains outcomes from
the TLC state dump and executes all 30 distinct initial-output/fault scenarios (retaining
all archive failure positions). It uses real asyncio task groups, semaphore permits,
worker threads, cooperative stop events, partition appends, SQLite construction,
validation, and atomic replacement. It controls archive conversion at the thread boundary
to force overlapping workers and an append completing after stop. It compares actual
worker outcomes, append sets, phase order, cleanup, and durable output with reachable
terminal model states, and verifies the exact published point multiset. There is no
network traffic. This is scheduling evidence, not an unbounded refinement proof of
Python's event loop or arbitrary native IO.

The lifecycle assumes one writer and same-filesystem atomic replacement. Exception and
cancellation cleanup are covered; abrupt process death can leave private staging files,
and power-loss durability is not established. The existing validator checks schema and
metadata, not every compressed payload or completeness against the remote source. A
preexisting database accepted by that validator is modeled as an opaque cached output;
its contents are preserved, not certified. Publication completeness for a newly built
database depends on successful input conversion and the separately checked point
construction contract. Neither specification silently repairs previously corrupted data.
