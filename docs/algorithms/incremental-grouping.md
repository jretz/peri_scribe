# Incremental source grouping and proximity forests

## Contract and context

Grouping returns exactly the connected components of the current source records. A
shared identifier supplies an unconditional edge. A shared normalized name supplies an
edge only when both geometries are nonempty and their exact GEOS distance is within the
configured degree tolerance. Every occurrence appears once, members retain source order,
and components follow their first occurrence. Canonical names, aliases, component
anchors and complex ownership continue to be derived from those complete ordered
occurrences.

This optimization retains the policy in [grouping and
ownership](fire-grouping-and-ownership.md). It avoids spatial edges that cannot change
connectivity and reuses complete partitions of independent dependency blocks. Source
indexing also retains authenticated slim snapshot summaries, so a changed generation can
load unchanged identity metadata without decoding its coordinates and raw attributes.
Every independent invocation still authenticates all authoritative source bytes.

## Complexity assessment

| Dimension | Score | Concrete reason |
| --- | --- | --- |
| History and state | 2 | A retained partition is reusable only for the same ordered current evidence. Removed bridges can split the result. |
| Rule interaction | 3 | Identifier paths, name incidence and geometric bridges interact across records and current components. |
| Mathematical reasoning | 2 | Conservative envelope search must retain every exact-distance edge, including multipart geometry and floating boundaries. |
| Scale and representation | 3 | Active-leaf deletion bounds successful discoveries; compact content-addressed partitions preserve occurrence reconstruction. |
| Failure and concurrency | 3 | Authenticated cached partitions are read and pruned within the owning product-store transaction. |

**Complex, total 13.** Misgrouping changes historical ownership and published outputs.
The pure forest alone has scores **1/1/2/2/0**, total 6, involved. Persistent selection
adds the history, representation and transaction obligations described here.

## Conservative dependency blocks

First join records that share any identifier or normalized name, without consulting
geometry. These components are conservative dependency blocks: every permitted identity
edge lies entirely in one block. Distant same-named fires may therefore share a
dependency block while remaining distinct fire components.

![Conservative blocks and a deleted bridge](grouping-dependencies.svg)

*A shared-name block can contain several actual fires. Removing an identifier bridge
changes the current incidence partition, so the former combined partition cannot be
selected for either surviving block.*

Each invocation reconstructs this incidence graph from the current row metadata. For a
block with more than one occurrence, its cache key includes the complete ordered
canonical row fingerprints and the exact grouping threshold. The existing product-store
context binds the code and numerical runtime. Multiplicity is retained: two equal rows
contribute two positions. A singleton has a known partition and needs no cache entry.

An authenticated matching product contains local component positions. Validation
requires nonempty components, ascending member positions, first-member component
ordering, and every position from zero through the block size minus one exactly once. A
count mismatch, malformed payload, missing receipt, checksum failure or unavailable
store causes ordinary calculation. Local positions are translated through the current
block's original source positions, then all components are ordered by their first
original occurrence.

The owning product transaction writes only complete partitions and prunes obsolete block
keys in the same transaction. This reuses the existing [product-cache
protocol](product-caching.md); it introduces no additional file or independently durable
manifest. An interrupted scope cannot publish a partial new block. A failed cache
remains disposable and cannot make source evidence unavailable.

The partition key assumes the canonical row fingerprint covers every relevant field and
that SHA-256 is collision resistant. Cache receipts authenticate stored payloads; they
do not establish a truth claim about external fire identity. Bare grouping calls without
row fingerprints or a usable product store calculate their relation directly.

## Retained summaries and affected closures

A complete initial source read seeds one summary per snapshot, bound to its relative
path, the checksum authenticated for that parse, and the product-store derivation
context. The summary keeps every row occurrence's fixed fire fields, complete evidence
digest, component anchor ordering and singleton identity, plus the normalized complex
declarations and memberships. It omits coordinates and raw attribute documents. A fresh
source checksum selects the summary; absent or invalid summaries hydrate that snapshot
and build a complete replacement. A checksum observed only after parsing cannot
authenticate the earlier parse.

Compact anchors retain the original singleton digest and replace large anonymous row
tokens with their lexical rank within one source/serial/filename prefix. The least
ranked anchor therefore selects the same component digest. Distinct paths sharing that
prefix require complete preparation, because independently assigned ranks would not be
comparable. All row declarations precede all uncovered membership fallbacks, just as
they do in the full reader; preserving only per-snapshot order would change that global
encounter order.

One retained reverse manifest stores the complete previous occurrence inventory and both
tagged incidence indexes together. An occurrence reference is its relative path and row
ordinal. An insertion, deletion or changed complete evidence digest seeds invalidation.
Follow reverse incidences from both the previous and current inventories until the
closure stops growing. Old edges matter: removing the A–B–C bridge must invalidate both
surviving sides even though B is absent from the new graph. Identifier and name tokens
remain tagged, so an identifier whose text equals an unrelated name does not create a
dependency.

The current inventory producer validates every `DependencyRow` as it is created, checks
occurrence-reference uniqueness, and constructs the canonical reverse map once. Those
steps establish the same aggregate invariant as full `DependencyIndex` validation.
The local construction can therefore omit a second reverse-map calculation. Arbitrary
public constructor inputs and persisted JSON still run complete schema, uniqueness and
canonical-map validation. A repeated reference takes the validating failure path.

Changed occurrences are computed once. An empty set returns an empty affected closure
before allocating either adjacency map. A nonempty set seeds the ordinary old-plus-new
traversal, so bridge corrections and deletions preserve the existing invalidation rule.
These changes retain O(R + I) worst-case work for R occurrences and I incidences; the
empty-seed case avoids the O(I) traversal allocation. They change local representation
work within the existing complex algorithm and add no durable state transition.

The read also carries the exact lexical `SourcePaths` memo through current dependency
rows, classification fingerprints and output. Its pure derivation and lifetime are
explained in [source-index preparation](source-index-preparation.md); its implementation
is [`sources.provenance`](../../src/peri_scribe/sources/provenance.py).

Current blocks touched by this closure are recomputed; untouched blocks require an exact
validated partition receipt. Missing receipts also trigger computation. Hydration
batches the snapshots needed by those blocks and later by classification misses. It
reuses any full snapshot already decoded for a summary miss and verifies selected full
row digests against their slim summaries. The current reader hydrates at snapshot
granularity: other rows in an affected snapshot can also be decoded. It avoids unrelated
snapshots, rather than guaranteeing individual-row random access.

The source-index plan is a separate metadata-only value. Its classification callback
returns complete compact groups for the requested fires while retaining their Fire
object identities. It never enters the execution cache as a complete `PreparedSources`.
A later geography stage can still request a complete preparation with all raw evidence.
Missing or invalid reverse manifests, unavailable product storage and incompatible
compact anchors use complete preparation and seed fresh summaries.

Summary products, partitions and the complete reverse manifest share the existing owning
product transaction. Only completed current metadata is staged. An exception after
staging new partitions and a reverse manifest preserves the prior committed products;
retry follows the current authenticated sources. There is no separate durable
publication boundary.

## Identifier pruning and geometry identities

Identifier unions run first. For each normalized-name bucket, inspect the current
union-find representatives. If every member already has one representative, every
possible spatial edge joins vertices already connected by a path, so the bucket can be
skipped. This also uses unions established by earlier name buckets. A bucket with
several representatives retains every original nonempty geometry: choosing one geometry
per identifier component would lose a bridge supplied by another member.

Exact geometry classes use the execution-owned compact `GeometryKeys` registry. Its
digest chooses collision candidates, and exact canonical WKB comparisons distinguish
classes. It preserves the SRID-ignoring equality of the `.wkb` grouping contract. Source
authentication and row fingerprints retain their separate SRID-preserving encodings. The
registry retains geometry references, so Python object IDs cannot be recycled while keys
remain available. It does not retain a second complete coordinate buffer.

Each class is joined internally. One representative per exact class then enters the
proximity search; every duplicate has the same neighbors as that representative. The
same geometry identities serve outlier diagnostics, avoiding another full serialization
of every repeated snapshot occurrence. Diagnostics retain their independent one-degree
neighbor rule and do not split the identity components.

## Active-envelope forest

Small geometry lists use a bounded STRtree query and retain one direction of each
distinct edge. The threshold is an implementation choice, not a grouping tolerance. For
larger finite inputs, a balanced bounding-box tree stores each representative once.
Immutable tree nodes hold source-coordinate envelopes and parent/child links. One local
counter per node records how many undiscovered leaves remain below it.

Start a component at an undiscovered geometry and remove that leaf from the active tree.
For every discovered geometry, search its tolerance-expanded envelope against active
nodes. Exact `dwithin` checks reject envelope false positives. Every accepted neighbor
is removed immediately, queued for expansion, and connected by one emitted edge.
Exhausted subtrees are skipped by their zero counters. After the queue empties, start
the next remaining component.

Search envelopes round outward with `nextafter` at each bound. The envelope is only a
conservative broad phase; exact GEOS `dwithin` decides every emitted edge. Nonfinite
envelopes retain the existing STRtree adapter. Native envelope coordinates remain in the
source geometry's degree system; the configured Pint tolerance is converted only at the
geometry boundary. This does not substitute a physical distance or centroid distance.

The argument for completeness is the exhausted-cut invariant: when a discovered geometry
finishes, it has no exact neighbor left undiscovered. Later discoveries can only shrink
that remaining set. When a component's queue empties, no edge connects any of its
vertices to an undiscovered vertex. Thus no true connected component can be split
between two seeds. Every emitted edge passed the exact predicate, so the algorithm
cannot merge different true components. Immediate removal ensures each non-seed receives
one discovery edge; a component with K representatives emits K−1 edges.

Polygon minimum distance need not satisfy triangle inequality. A multipart geometry can
intersect two separated perimeters that are far from each other. The forest explores
every discovered geometry and uses no Euclidean point-MST bound, triangle pruning or
single nearest-neighbor substitution. A name-only representative or centroid shortcut
would not preserve this example.

## Changes, splits and boundaries

Consider A with identifier `left`, B with identifiers `left` and `right`, and C with
identifier `right`. Initially their dependency block and fire component are A–B–C. If B
is removed, the current incidence scan produces independent A and C blocks. Neither can
select the previous three-occurrence key. If B was instead a same-name geometric bridge,
the remaining rows can stay in one name block; its changed ordered key still requires
recomputation and permits two resulting fire components.

An insertion can connect previously separate blocks through identifiers or names. The
new combined block has a different ordered key and is calculated as a whole. Attribute,
status or geometry changes invalidate the full row fingerprint even when a particular
change would not affect grouping. This conservative invalidation avoids depending on a
second incomplete interpretation of source evidence.

The grouping cache reuses the partition, while source indexing reconstructs fire
metadata, component identities and complex ownership from current ordered summaries. A
new parent declaration can therefore change ownership without inheriting a cached
mutable `Fire` object. Complete source preparation continues to calculate geometry
diagnostics and serves downstream raw-evidence consumers. The source interpretation and
declaration ordering contracts remain those in the authoritative grouping and ownership
note.

## Costs and limitations

For N rows and I identifier/name incidences, dependency construction uses O(N+I) storage
and O((N+I) α(N)) union work with size balancing and path halving. The incidence scan
still examines all current rows. Matching blocks avoid geometry-class construction and
spatial predicates, but this is not a fully dynamic graph that updates in logarithmic
time. A common name can conservatively dirty many actual fires.

Slim metadata and the old-plus-new reverse closure use O(N+I) space and work, in
addition to sorting canonical reverse keys and current block construction. If I distinct
tokens are retained, canonical reverse encoding can require O(I log I) comparisons. Only
affected or missing-product snapshots incur geometry and attribute hydration; one
affected row in a large snapshot can still incur that complete snapshot's payload cost.
Classification dependency changes can require hydration even when grouping is unchanged.
The initial full read, corrupt-cache fallback and complete geography preparation retain
their full decoding costs. Authoritative byte authentication remains linear in source
bytes on every invocation.

Keys read each current row fingerprint once per nontrivial block and retain its ordered
occurrences. Cached partition storage is O(N) positions plus key/encoding overhead for
the current nontrivial blocks. Canonical row fingerprint construction, authoritative
byte authentication, decoding and exact geometry-key construction have their separate
payload costs. They do not disappear from the end-to-end pipeline bound.

For K representatives in a large proximity search, balanced envelope construction uses
O(K log² K) comparison work with the current recursive median sorting and O(K) stored
nodes. Removing all discoveries updates O(K log K) ancestor counters. Only K−C true
edges are emitted for C components, and the active query never materializes the complete
dense adjacency array. False envelope candidates and geometry tests can still require
O(K²) work for adversarial multipart shapes or holes. GEOS predicate cost also depends
on coordinate counts. The small-list branch has bounded quadratic output below its fixed
threshold. The outlier diagnostic still has quadratic worst-case comparisons among
distinct singleton geometry classes.

## Implementation and verification

[`SourceProvenance.lean`](../../tests/formal/lean/PeriScribe/SourceProvenance.lean) checks
the current reverse-construction refinement under individually validated row and unique
reference premises, plus the empty-seed closure result. Its
[inventory and conformance limits](../../tests/formal/lean/source_provenance.md) connect
these refinements to actual lexical strings and strict cached-index decoding.

Owners are [grouping](../../src/peri_scribe/fires/grouping.py), [selective index
preparation](../../src/peri_scribe/fires/source_index_cache.py), [snapshot
summaries](../../src/peri_scribe/geo/source_summaries.py), [dependency
partitions](../../src/peri_scribe/fires/grouping_cache.py), [union
tables](../../src/peri_scribe/fires/connectivity.py), and [active-envelope
search](../../src/peri_scribe/fires/proximity.py).

[Lean grouping proofs](../../tests/formal/lean/PeriScribe/Grouping.lean) establish that
identifier-connected omitted edges preserve components, forest paths preserve the full
edge relation, every connected component stays inside a conservative dependency block,
and sound/complete local partition replacements preserve the global partition. The
proofs state the edge-coverage and dependency-locality obligations explicitly. They do
not prove Python mutation, GEOS or floating envelope arithmetic.

The [frontier model](../../tests/formal/tla/grouping_forest.md) checks every undirected
graph on four vertices and every discovery/seed order. Its concrete bridge realizes all
64 abstract graphs using multipart polygon gadgets and requires the actual forest to
appear among the freshly checked complete model outcomes. The existing product-cache
models cover complete transaction publication; canonical input identity remains an
explicit dependency contract.

The [retained-index proofs](../../tests/formal/lean/retained_source_index.md) establish
old-plus-new closure, deleted-reference exclusion, dirty/clean separation and
equivalence with complete current connectivity under explicit complete-evidence and
conservative-edge premises. Executable conformance compares all 31,250 three-reference
histories across two tag assignments with those actual Lean definitions. The
snapshot-summary model separately checks authenticated summary selection and hydration;
the parsed-cache inventory records its adapter assumptions. None of these proofs
establish external source truth or arbitrary Python execution correctness.

Ordinary regressions cover identifier and geometric bridge deletion, unchanged block
reuse, changed-block invalidation, exact occurrence reconstruction, malformed
partitions, dense forest edge bounds, multipart bridges and threshold boundaries.
Property tests compare changed histories with exhaustive grouping and compare large
active-tree inputs with every exact geometric edge. Formal conformance additionally
compares both cached partitions and forced active-tree grouping with the executable Lean
component definition. Ordinary selective-index checks reject malformed reverse maps,
duplicate references, changed hydrated evidence and incomparable compact anchors. A real
GeoPackage integration hydrates only an appended snapshot and compares its final index
bytes with an unconditional full rebuild. A real SQLite abort after new partition and
reverse-manifest staging retains the previous commit and retries against complete
current source evidence.
