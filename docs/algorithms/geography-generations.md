# Authenticated geography generations and reuse

## Contract and context

Reuse must produce the same complete histories as recomputation for unchanged inputs.
A generation identifies source bytes and derivation dependencies; a signature separately
authenticates the actual published output bytes and declared layers. Full geography and
differential geography are separate GeoPackages, and their metadata are separate files.
A successful downstream read must authenticate their relationship while excluding writers.

Inputs include ordered source snapshots, all raw observations/provenance, grouped fires,
code and runtime dependencies, cleaning/classification settings and boundary data. Outputs
are full perimeter/point/incident histories, differential histories, and signatures.
Generation keys are opaque hashes; coordinates and measurement units remain the domain
transformers' responsibility. Cooperating readers/writers use the year lock.

## Complexity assessment

| Dimension | Score | Concrete reason |
| --- | --- | --- |
| History and state | 2 | Unchanged fires reuse prior complete history while corrected fires are reconstructed. |
| Rule interaction | 3 | Source identity, per-fire evidence, classification completeness and full/differential dependencies must agree. |
| Mathematical reasoning | 1 | Hash identity and set inclusion establish reuse eligibility under explicit collision assumptions. |
| Scale and representation | 2 | Whole-generation shortcuts and indexed per-fire rows avoid unnecessary decoding of large GeoPackages. |
| Failure and concurrency | 3 | File/signature and full/differential publication each have distinct interruption boundaries. |

**Total 11: complex.** Authentication is a consistency contract, not cryptographic proof
against a malicious writer able to replace both data and metadata.

## Approach and invariants

Compute a derivation context from source code, relevant library/runtime versions,
configuration and administrative boundaries. The complete source generation also hashes
ordered snapshot paths and bytes. A matching complete generation, authenticated checksum,
and exact layer declaration permit skipping all reconstruction unless forced.

When that shortcut fails, derive per-fire keys from *all* source evidence, including
observations reconciliation discards, geometry bytes, attributes, provenance, aliases,
component identity, complex membership and the derivation context. Reuse rows only from
an
authenticated prior file and matching per-fire keys; reconstruct affected fires in full.
A later correction can therefore revise early history. Matching only the most recent
surviving perimeter would miss corrections to a discarded observation.

![Dependencies contributing to a reusable generation](assets/geography-dependencies.svg)

*Whole-generation identity protects the complete input inventory. Per-fire identity allows
unchanged histories to survive a change elsewhere, without omitting discarded evidence.*

Classification must be complete for every non-complex fire before saving a whole-generation
tag. A prior complete authenticated generation can supply classification evidence for
matching reused fires. If classification is unavailable, bytes may still be published
with `generation=None`; the next run must reconsider the incomplete work.

Write all layers into one temporary GeoPackage, compute its checksum, prepare metadata,
then replace the file followed by its metadata. Differential generation incorporates the
full-history checksum and current derivation context. It cannot authenticate against a
new full file with an old dependency.

Individual replacements can expose a mixed physical pair. The following publication
sequence shows what a supported reader may observe after interruption:

| Publication state | Full history | Differential history | Reader result |
| --- | --- | --- | --- |
| Initial complete generation | `g0`, valid signature | Depends on full `g0`, valid signature | Accept pair `g0`. |
| Replace full bytes | `g1` bytes, old `g0` signature | Still depends on full `g0` | Refuse: full checksum does not match its signature. |
| Replace full metadata | `g1`, valid signature | Still depends on full `g0` | Refuse: differential dependency does not match full history. |
| Publish differential bytes and metadata | `g1`, valid signature | Depends on full `g1`, valid signature | Accept pair `g1` and return all four requested layers. |

The reader checks both signatures and their dependency under one lock, so these
intermediate states never become a successful mixed-generation result.

`read_derived_layers` acquires a shared lock, authenticates before cache lookup, reads all
layers, and releases afterward. Its execution-cache key includes both authenticated
checksums. The live writer may read its own completed pair only within the same process,
thread and still-active ownership context. Copying an expired context cannot bypass locking.
Tolerant scoring accepts missing geography only when both files are absent; a partial or
unsigned pair requires repair.

The fire index and spatial-product coordinators use the same principle: authenticate
complete input/dependency generations before skipping work, and keep advisory indexes
subordinate to authoritative bytes. [index.py](../../src/peri_scribe/fires/index.py) records
a completed source generation only with complete classification.
[spatial_products.py](../../src/peri_scribe/fires/spatial_products.py) keys buffers by exact
geometry, distance and projection definitions; counts also include the building database
checksum and point-store policy. Missing/empty geometries retain their defined results;
invalid cached polygons or noncanonical counts are misses. A live SQLite WAL bypasses
count caching so a database-file checksum cannot omit pending database contents. Only
missing products are batched, then restored to their original query positions. Its cache
storage contract is in the [persistent-cache inventory](../../tests/formal/tla/cache.md).

## Worked examples and boundaries

If only fire A's raw record changes, the whole-source key changes. A's per-fire key changes,
while unrelated B can reuse its authenticated rows. If a boundary file or derivation code
changes, context changes invalidate affected keys even when feed geometry is identical.
If classification could not finish, persisting a generation tag would incorrectly turn
that transient absence into a permanent cache hit.

An alternative single bundle could atomically replace both histories together but would
change consumers and duplicate large-file handling. The current design keeps separate
files and makes successful reads conditional on authentication. Raw readers bypassing
this protocol can observe intermediate files; that limitation is intentionally modeled.

## Costs and limitations

For B source/code/boundary/output bytes, hashing costs O(B) I/O. Per-fire key creation scans
R rows and total geometry bytes, deduplicating geometry hashing by live object identity.
Keys and row digests require O(R) memory. Whole-generation reuse still authenticates output
bytes; indexed partial reuse avoids loading unrelated rows when beneficial and can fall
back to bulk layer reads. Reconstruction costs depend on changed histories. Publication
requires temporary space for each complete GeoPackage and its signature.

[execution.py](../../src/peri_scribe/execution.py) shares completed source, derived,
history and presentation work only in a bounded publication scope; group clearing and scope
exit release references. It is not a durable cache. Source-stat shortcuts within that scope
assume input ownership; standalone invocations recompute exact generation identity.
Assumptions include collision-resistant hashes, atomic replacement, cooperative locks,
correct serializers, complete declared inputs and reliable file metadata. Power loss,
forged metadata and arbitrary external mutation are excluded.

## Implementation and verification

Owners: [generation.py](../../src/peri_scribe/fires/generation.py),
[reuse.py](../../src/peri_scribe/fires/reuse.py),
[files.py](../../src/peri_scribe/fires/files.py), and
[derived_layers.py](../../src/peri_scribe/fires/derived_layers.py).
Ordinary checks cover [generation](../../tests/tests/standard/peri_scribe/fires/test_generation.py),
[reuse](../../tests/tests/standard/peri_scribe/fires/test_reuse.py),
[whole-file generation](../../tests/tests/standard/peri_scribe/fires/test_files_generation.py),
[reader generations](../../tests/tests/standard/peri_scribe/fires/test_derived_layers_generations.py),
and [execution lifetime](../../tests/tests/standard/peri_scribe/test_execution.py).

[Geography publication](../../tests/formal/tla/README.md#geography-and-cache-publication)
checks separate durable actions; [reader contracts](../../tests/formal/tla/command_readers.md)
check lock ownership and all returned layers.
[Publication conformance](../../tests/formal/conformance/test_geography_publication.py)
and [reader conformance](../../tests/formal/conformance/test_geography_readers.py) exercise
actual files. `GeographyPairExpected` explicitly demonstrates mixed physical files after
interruption. Finite protocol models abstract collision-free identities and do not prove
geometry reconstruction, library serializers or correctness of external boundaries.
