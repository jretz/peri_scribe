# Bounded source work

Full geography keeps compact metadata for every source occurrence, then decodes detailed
evidence only while the relevant dependency block or fire needs it. This removes the
requirement to keep the whole year's native geometries and attribute documents alive
through reconstruction. Authoritative source GeoPackages retain their original bytes,
paths, layers and field representations.

## Contract and assessment

Inputs are the complete ordered snapshot inventory, authenticated parsed-cache receipts,
typed row metadata, exact geometry and attribute identities, and the existing grouping,
complex ownership, classification and history policies. Outputs are the same ordered
full-history layers, classification products and fire index as complete preparation.
Differential geography still consumes the published full history through GDAL. That
round trip remains part of the numerical contract.

History scores 3: later membership evidence can transfer historical ownership. Rule
interaction scores 3: grouping, ownership, classification completeness and reusable
histories must agree across all fires. Mathematical reasoning scores 2: the conservative
dependency closure feeds the existing exact geometry algorithms. Scale and representation
scores 3: compact metadata and reconstructed payloads determine evidence lifetimes.
Failure and concurrency scores 3: pinned readers must outlive every worker, and source
changes must be rejected before completed work leaves the preparation scope. **Complex,
total 14.** Published history makes preservation of the existing policy essential.

## Metadata before detailed work

The owner hashes every authoritative source file, synchronizes each disposable parsed
cache, and opens a read transaction for each feed. It compares the pinned snapshot
receipts with those source hashes. Each row's fixed fields and referenced logical
payload digests must reproduce its complete evidence fingerprint. Missing references,
invalid payload sizes and unsupported anonymous identity anchors reject this path.

Metadata retains occurrence multiplicity, original path order and row order. Dictionary
IDs are local to a feed connection; equal integer IDs from different feeds never imply
shared payloads. Metadata rows deliberately carry no geometry and an empty attribute
mapping. They are not complete source evidence and never enter the execution cache as a
`PreparedSources` value.

The existing dependency-block algorithm connects every shared identifier or name. A
proximity edge requires a shared name, so no exact grouping edge can cross these blocks.
For each nontrivial block, the owner decodes its geometry, runs the existing exact
grouping algorithm, records its partition, then releases those coordinates. Singletons
need no geometry to establish their partition. Cached partitions retain their existing
complete evidence and code dependencies; a forced invocation recomputes them.

Global complex ownership is resolved before admitting history work. Attribute documents
are decoded one at a time to project normalized membership declarations. The owner
retains those declarations and independent membership fallbacks, then applies the same
complete ownership resolver used by eager preparation. Resolving ownership inside each
fire independently would lose claims made by another fire or snapshot.

## Detailed evidence lifetimes

The [ordered worker queue](history-work-queues.md) receives compact fire positions.
Its byte weight is the sum of distinct uncompressed geometry and attribute payload
sizes referenced by that fire. Up to four workers and 64 unfinished tasks are allowed,
with a 128 MiB admitted input budget. An oversized fire runs alone. The catalog's read
lock serializes SQLite decoding; geometry computation can overlap after that lock is
released.

Each worker decodes its complete source rows into a private geometry pool. Identical
immutable geometries may share storage within that hydration; mutable attributes and
evidence bases remain independent for each occurrence. The worker applies existing
diagnostics, parent exclusion, classification, reconciliation and incident rules. It
returns only completed output rows and a scalar classification. Raw row containers and
their geometry registry leave scope before the next work item uses that worker.

Ordered completion preserves fire order and each fire's existing row order. Classification
products are written by the owner after workers finish. A forced invocation still warms
the products and refreshes the fire index. Whole-layer normalization and GeoPackage
publication happen after the catalog has verified source bytes again and closed its
readers.

For example, suppose observations A and B share a name but are spatially separate, and
C shares B's identifier. Their conservative block contains all three. Exact grouping
may separate A from B/C; only then can their histories run separately. If C declares a
complex relationship affecting A, that declaration is already included in global
ownership. Decoding A first cannot make that claim disappear.

## Failure and consistency boundaries

Every selected payload is decoded and authenticated against its original logical bytes
before it becomes complete evidence. A malformed disposable cache causes complete
preparation to retry through the existing source adapter. That adapter retains the
original behavior for anonymous rows whose stable lexical anchor needs full evidence.
This fallback can retain the whole year's source working set.

A worker failure closes admission, cancels queued work and joins running workers before
the catalog releases its readers. No partially collected layer is published. A genuine
source inventory or byte change at final verification propagates as an error; it is not
hidden by a cache fallback. Publication failures also propagate through the existing
atomic layer/signature protocol.

The final source check authenticates the pinned generation at that checkpoint. It does
not prevent another process from editing a source after the check. Existing publication
locks protect geography writers and readers, not arbitrary external source edits. A
read transaction also retains a coherent old cache inode across atomic cache compaction.
Neither guarantee promises that publication represents an edit made after validation.

## Costs, alternatives and limits

For N occurrences, metadata and occurrence references use O(N) memory. If B is the
largest conservative dependency block, its grouping pass holds at most that block's
decoded geometries, plus the existing grouping algorithm's working structures. The
history pass holds admitted raw inputs and native working memory, plus completed output
rows and their geometries. The complete output frames remain resident for GDAL writing.
Grouping and history can decode the same geometry in separate passes; this trades some
CPU and reads for shorter lifetimes.

The 128 MiB value bounds canonical input weights of unfinished work, not RSS. Native
GEOS objects, Python dictionaries, algorithms' scratch storage, SQLite pages, completed
results waiting behind an earlier result, and final output frames are additional. One
oversized fire or dependency block remains an unavoidable working-set floor. A corrupt
positive size can understate admission until payload authentication rejects it. Cache
metadata is an integrity aid, not a hostile-input memory sandbox.

Keeping every decoded source is simpler but retains the full native working set.
Spilling arbitrary intermediate geometry would add encoding and I/O and could change
the established GDAL boundary if done carelessly. The chosen path changes evidence
ownership while reusing the existing exact policy functions. Geometry simplification,
approximate grouping and alternate union algorithms are outside its contract.

## Implementation and verification

Owners are [the pinned catalog](../../src/peri_scribe/geo/catalog.py),
[bounded history work](../../src/peri_scribe/fires/bounded_sources.py), and
[full publication](../../src/peri_scribe/fires/files.py). The shared complex-observation
and group-assembly functions serve both complete and bounded preparation.

[BoundedSourceRead](../../tests/formal/tla/bounded-source-read.md) was checked before
implementation. It models metadata, global ownership, worker verification, settlement,
source revision checks, reader release and publication. Existing ordered-worker,
grouping, cache, complex ownership and geography publication contracts cover the reused
algorithms. The finite model and concrete path adapter do not prove arbitrary GEOS or
SQLite behavior.

Ordinary tests cover exact equality with complete history and incident policy, global
group identities, independent mutable payloads, cache corruption, incomplete
classification, forced recomputation, reusable rows, source races, and reader leases
across cache replacement. Saved-data comparisons additionally check ordered KMZ member
bytes, updates, reports and authoritative source hashes. Profiling evidence stays under
`.cache/profiling/`.
