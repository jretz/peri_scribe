# Building centroids and monitor reconstruction

`BuildingCentroids.lean` and `MonitorReconstruction.lean` use the standard Lean library.
Their executable definitions are exposed by `OracleObservers.lean` as `oracleObservers`.
The normal axiom audit includes both modules. The Python bridge exercises the actual
array calculations, archive conversion, reducer and phase projection.

## Building centroid calculation and streaming

The 27 centroid theorems map to `src/spatial_data/centroid_math.py` and
`src/spatial_data/centroid_streaming.py`:

- An oriented triangle fan contributes exact signed double area and first moments.
  Reversing its edges negates both quantities; orientation normalization makes the
  resulting ring contribution independent of winding.
- Translating every vertex translates the area-weighted result by the same offset.
  The translated shoelace expression agrees with the fan contribution, including the
  factor of three in restoring each ring's offset.
- Exterior rings add and holes subtract area and moments, independent of hole order.
  Associative and commutative moment addition preserves multipart aggregation. The
  weighting relation is cross-multiplied exact integer algebra; no rounded centroid is
  an assumption of the executable reference.
- Zero-area features use every recorded vertex, including duplicated closing vertices,
  for the fallback mean. Nonzero-area features use the complete signed moments.
- The greedy streaming split preserves every accepted feature, its order and duplicate
  multiplicity. Feature and archive-member boundaries cannot change the flattened
  sequence or any independently computed per-feature result. Every nonempty split
  consumes input, and its feature count is bounded by the positive configured limit.

The vertex threshold is checked after a complete feature is accepted. A feature is never
split to fit the threshold, so a chunk can exceed it by its final feature. A single large
feature can exceed it by an arbitrary amount. This is a threshold between features, not
an unconditional memory bound. The formal collector also describes zero limits as one
feature per chunk, matching the implementation; production limits are positive.

`test_building_centroids.py` contains nine conformance tests:

- 180 integer projected footprints combine exterior rings, off-center holes, unequal
  multipart areas, concavity, reversed winding, shifted ring starting vertices,
  degenerate rings and offsets near twelve million meters. The real NumPy collector,
  shoelace sums and feature aggregation agree with Lean's rational results to an
  absolute tolerance of two billionths of a projected meter.
- Five feature/vertex budgets compare every collected coordinate, ring and part boundary
  with the proved greedy split. Unsupported point geometry is skipped; repeated polygon
  features retain their multiplicity.
- Three real ZIP conversions use byte fragments of 1, 17 and 257 bytes, three GeoJSON
  members and ignored intervening members. Real ijson, stream_unzip, pyproj and GDAL
  produce a GeoPackage whose six ordered points agree with Lean's projected centroids
  within two ten-millionths of a meter after reprojection. The cases include large
  offsets, holes, multipart geometry, degeneracy and a repeated feature.

The mathematical domain uses exact integer projected coordinates and complete, closed
rings with positional exterior/hole ownership. The fan representation assumes the usual
valid polygon interpretation; it does not prove polygon topology, that the source supplied
valid rings, or that a footprint represents a real building. Projection accuracy, Web
Mercator distortion, antimeridian/polar behavior, overflow, floating-point error bounds,
ZIP/JSON/GDAL correctness and malformed-input handling are not Lean theorems. The real
numerical and artifact checks supply finite evidence at those boundaries. Arbitrarily
large geometry and integer-array capacity limits are also outside that evidence.

## Monitor run and phase reconstruction

The 19 monitor theorems map to `src/peri_scribe/monitor/model.py`, with context parsing
through `src/peri_scribe/monitor/events.py`:

- A record changes only its owning run and obtains inferred context from that run.
  Steps belonging to different runs commute; the resulting run equals folding just
  its own records. Processing complete history or arbitrary batches gives the same
  unbounded result.
- A completed or failed phase requires a corresponding finish observation. Ordinary
  records cannot manufacture those terminal outcomes. A phase still active when its
  command ends is unfinished, and missing execution is never classified as completion.
- Explicit skip decisions have a separate omission category and precedence over inferred
  absence. Command failure, command completion and the first completed/failed ancestor
  remain distinguishable reasons for not reaching a planned branch.
- Retention preserves structural observations in their original order and multiplicity.
  Therefore it preserves phase completion/failure outcomes even when verbose rows leave
  the retained suffix. A positive run-count limit bounds the retained run list.

`test_monitor_reconstruction.py` contains ten conformance tests. They compare 792 scoped
histories with real `append_records`, `event_path` and `phase_tree`, including every
three-event history over eight event classes and all 70 interleavings of two four-event
commands under four branch/failure choices. Same-named phase instances on different feed
branches remain distinct. Every resolved event path, final run context/status and observed
phase status is checked against Lean. Whole-batch results also equal per-record results.

The omission bridge checks all 250 combinations of run status, explicit-decision presence
and two ancestor statuses. Eight further scenarios compose the policies across the real
planned phase catalogue, checking visible phases and topmost omitted branches. Four
positive event limits check actual retained structural records and phase outcomes; three
positive run limits check the actual bounded run list.

These proofs assume scoped run identities and valid explicit/inferred phase metadata.
Legacy unscoped command grouping, malformed fields, the phase catalogue itself, publication
gate reason strings, wall-clock durations, widget rendering and archive restoration have
separate ordinary tests and are outside these theorems. An observed finish is evidence;
a matching start is not required to accept it. Reused run identifiers are not treated as
new identities. Bounded run eviction intentionally discards a run's in-memory context;
batch/stream equivalence is claimed only for unbounded processing. Retained structural
progress may grow during a long run. The retention theorem preserves terminal outcomes,
not every phase inferred solely from an ordinary record that has since expired.
