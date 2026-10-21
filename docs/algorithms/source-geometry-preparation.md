# Source geometry preparation

## Contract and assessment

A source read retains one compact geometry-key registry alongside its immutable
geometries. A key identifies exact canonical `.wkb` bytes, including coordinate ordering
and dimensions, while deliberately excluding SRID to match named grouping's existing
equality rule. It is an execution-local equality token, not a persistent source
fingerprint. Parsed snapshot fingerprints continue to include their complete source
representation and metadata.

A fire classification retains a separate projection memo. Its key contains the exact
retained geometry object's identity and the source coordinate reference system. A
projection made for NAD83 cannot satisfy a WGS84 request merely because the input
coordinates happen to match. The memo is released after the fire's classification.

| Dimension | Score | Reason |
| --- | --- | --- |
| History and state | 1 | A source read and one classification each own disposable local preparation. |
| Rule interaction | 2 | Grouping ignores SRID in WKB classes; decoding and projection retain their distinct reference-system contracts. |
| Mathematical reasoning | 2 | Exact collision classes, immutable trie routing, and one-sided collection evidence preserve different observable equalities. |
| Scale and representation | 2 | Compact identity tokens avoid retaining another complete set of coordinate encodings. |
| Failure and concurrency | 2 | Independent shard locks publish complete roots and exact collision classes; a read ends their lifetime. |

**Complex: 9.** The public grouping and classification policies are unchanged. The
important guarantees concern exact equality, lifetime, and the numerical paths used to
produce published evidence.

## Exact keys without retained coordinate copies

The registry first checks the retained geometry object's identity. A miss serializes its
canonical WKB once, hashes those bytes, and searches only that digest's collision
bucket. Exact bytes determine which representative belongs to the class. The resulting
key is the digest and the class's insertion ordinal. Existing class ordinals never
change, and digest equality alone cannot merge classes. Encoded coordinate buffers are
released after the comparison; the registry keeps geometry references and compact keys.

For example, two points with coordinates `(1, 2)` but SRIDs 4326 and 3857 have the same
grouping key because their `.wkb` bytes agree. The decoder still retains distinct EWKB
objects, and the projection memo keeps distinct object/reference-system keys. A 3D point
`(1, 2, 3)` has another grouping key even under a forced digest collision.

The decoded-geometry pool partitions digests by integer digest modulo sixteen. Every
canonical encoding has one deterministic shard. That shard owns its immutable compressed
trie root and lock, so requests for the same encoding still serialize lookup, decoding,
and publication together. Unrelated shards can progress independently. Each trie keeps
[its existing insertion and snapshot contract](geometry-sharing.md). A consistent pool
snapshot acquires shard locks in their fixed index order and copies only root
references.

The geometry-key registry has matching digest partitions for collision-class insertion.
A short identity-table lock protects retained object/key publication. It is never held
while acquiring a collision-shard lock, so competing insertion paths cannot invert a
nested lock order. Two simultaneous first requests may serialize the same object before
one publishes its identity entry; both still receive the same exact class token.

## Projection and boundary evidence

`ProjectionCache` records each projected immutable geometry together with the original
retained object. The source CRS participates in its key. A cached result therefore
replaces exactly the same deterministic projection call. The whole-observation geometry
and freshest FIRIS/WFIGS extent comparison share this memo within one classification.

Each classification worker lazily clones and prepares the fixed California box. The
original boundary stays unprepared. Each thread owns its clone because GEOS prepared
predicates lazily mutate native acceleration data; sharing one prepared object between
workers can corrupt that data. Cloning retains coordinates, precision, and SRID, while
preparation leaves logical relations unchanged. Per-observation deduplication uses the
shared compact keys and source kind. Distinct source kinds remain separate because the
same coordinates may have different reference-system interpretations.

A prepared observation collection records whether every projected part is contained by
the box or disjoint from it. Its classification consumes that exact side evidence
without repeating those predicates or constructing an unnecessary union. Mixed-side
geometry keeps the exact union/intersection path. Single distinct geometries also keep
their existing measurement path: replacing an overlay-derived fraction by an ideal
fraction could otherwise change floating-point evidence. Positive-area overlaps are
never added together as if they were disjoint.

The classification coordinator admits at most four workers, limited further by reported
CPU availability, and uses one when availability is unknown. It retains the executor
context until admitted work finishes, including when retrieving a result raises. Results
are collected in input group order, independently of completion order. This cap belongs
to classification; other pipeline executors keep their own resource policies. It bounds
simultaneously active projection memos and prepared native boundary indexes. The measured
source-index workload benefits from avoiding excessive Python and native contention;
the cap does not claim the best worker count for every machine or input.

The cap's local assessment is **straightforward: 4**: history 1 for local task sequencing,
rule interaction 1 for CPU fallback and the fixed bound, mathematics 0, representation 1
for bounded in-memory work, and failure/concurrency 1 for the existing synchronous
executor lifetime. The geometry preparation assessment above remains unchanged.

## Costs and boundaries

For N requests and U distinct retained objects, normal key lookup takes O(N) identity
operations and serializes each object's bytes once. A bucket with C genuinely colliding
encodings can require O(C) exact comparisons per miss. Only digest and reference storage
is retained, O(U), alongside the already-owned geometry; there is no second retained WKB
payload of all U geometries. Collision comparisons can transiently serialize a
candidate.

Geometry-pool trie depth stays bounded by the digest width in every shard. The shards
reduce one lock's contention; they do not establish a parallel speedup, remove the GIL,
or bound GEOS's geometry allocation. The projection memo holds at most the distinct
object/CRS pairs for one fire. Each active worker retains one prepared box and GEOS-owned
index until its thread or `Boundaries` owner is released.

Malformed WKB raises before a pool root is published. Digest collisions cannot
substitute coordinates, dimensions, or reference systems. Python locks, Shapely
immutability, canonical serialization, and deterministic projection for fixed runtime
dependencies remain explicit trusted boundaries. The cache does not claim eventual
object collection while a caller still retains its owner.

## Implementation and verification

The compact-key and shard design was checked before implementation in
[`GeometryPreparation.lean`](../../tests/formal/lean/PeriScribe/GeometryPreparation.lean).
It proves exact/disjoint shard partitioning, equality of encoding class positions,
preservation of existing class positions, projection-memo refinement, and source-CRS
separation. Existing `GeometrySharing` proves each shard's actual compressed trie;
`BorderClassification` proves the consumed summary and one-sided union properties. The
complete Lean project audits these proofs without additional axioms.

The executable presentation-flow oracle exposes exact encoding class positions.
Conformance checks compare actual collision ordinals with that definition and actual
shard trees with the existing trie oracle. Real concurrent calls check both normal
hashes and deliberately colliding payloads. Ordinary and generated tests cover
lifecycle, reference systems, dimensions, exact key equality, prepared predicates and
complete classification evidence. They also check projection reuse through both
classification consumers. Deterministic ownership checks verify distinct prepared
objects per thread and release with their owner. A subprocess stress check synchronizes
eight workers before their first native prepared query, then compares 43,200 predicates
with an unprepared reference. Native prepared-index ownership is an adapter constraint
outside the ideal geometry model; it changes neither policy nor mathematical evidence.
[Coordinator regressions](../../tests/tests/standard/peri_scribe/fires/test_classification.py)
check reported CPU counts, four simultaneously admitted real workers, input result order,
and failure propagation after a held worker exits. The existing
[`WorkerLifetime` model](../../tests/formal/tla/WorkerLifetime.tla) checks resource closure
only after admitted children finish. Changing the count does not change that protocol.
These finite implementation checks do not prove all thread schedules or third-party
floating-point geometry.
