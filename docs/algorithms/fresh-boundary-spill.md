# Fresh boundary fragments within a KML document

A forced publication rejects prior product-cache entries. It can still reuse boundary
text it has just computed. The writer keeps its 16 MiB least-recently-used text cache
and spills complete serialized fragments into a private, compressed temporary file.
This avoids formatting a large fire's coordinates again after its text leaves memory.
Saved source files and published coordinate text are unchanged.

## Contract and assessment

The input key includes the complete ordered geometry WKB, SRID, geometry type and
coordinate precision. Values contain the exact ordered exterior/interior ring strings.
The unchanged renderer determines rounding, negative zero, component order and XML.
The spool adds no coordinate transformation. SHA-256 identity assumes no collision.

| Dimension | Score | Reason |
| --- | --- | --- |
| History and state | 2 | A document can reuse only complete entries admitted during its own scope. |
| Rule interaction | 2 | Memory, fresh disk, persistent-cache policy and two capacity limits interact. |
| Mathematical reasoning | 1 | Exact byte encoding and digest comparison preserve an existing representation. |
| Scale and representation | 3 | Compressed disk fragments replace repeated large coordinate strings in memory. |
| Failure and concurrency | 2 | Writes can fail after reserving bytes; only complete writes gain an index entry. |

Total **10: complex**. The spool is single-owner and disposable. It is not another
persistent publication or recovery store.

## Selection, admission and release

A boundary request checks the memory cache, the current document's spool, and then the
existing persistent product cache. The persistent cache still rejects every read in
forced mode. A miss calls the unchanged formatter. Newly computed or validated bytes
can be added to the spool; neither an old temporary file nor another document is opened.
Decoded fragments must pass the existing component-count and boundary-grammar checks.

The spool reserves at most **128 MiB of encoded bytes** and indexes at most **8,192
entries**. It appends each admitted key once. Capacity exhaustion skips that insertion;
there is no eviction, rewrite or compaction pass. The ordinary memory cache remains
available for requests that cannot enter the spool. These conservative first-admission
limits avoid another disk-reclamation protocol. They are performance choices, not
requirements for the generated content.

Each index record contains a fixed-size key, offset, encoded length and logical SHA-256
digest. Encoding uses the shared bounded zstd payload codec with its raw-byte fallback.
The offset range is reserved before writing, and the index is updated only after the
write reports the complete length. A short write or I/O error disables later appends;
previous complete entries remain readable. A rejected or corrupt read becomes a miss.
The reserved size includes any incomplete tail, so failure cannot increase the byte
allowance. Codec limits likewise cause a skipped insertion.

For example, suppose A and B exceed the memory cache together. Rendering A admits its
compressed bytes, rendering B evicts A's text, and a later A request decodes its fresh
spool entry. With a disk cap too small for A, the same request renders A again. Both
paths return identical strings. Allowing forced requests to read the ordinary persistent
cache would violate forced recomputation; a new file owned by this document avoids that
change in policy.

`KmlWriter.document` owns the temporary file around the entire document envelope,
including opening and closing XML writes. Scope exit restores the previous cache scope
and closes the file on normal completion or exceptions. Standalone geometry calls retain
their prior memory-only lifetime. Failure to create the optional temporary file leaves
rendering available. A resource-close error can still propagate, like an output-writer
close error; the spool does not promise successful publication after arbitrary I/O
failure. The platform's temporary-file cleanup semantics govern abrupt process exit.

## Costs, alternatives and limits

For V vertices, initial rendering remains O(V). If L is logical fragment bytes and Z is
encoded bytes, a spool insertion takes O(L) serialization/compression work and O(Z) disk
traffic; a hit takes O(Z) reads and O(L) decoding/validation. Lookup is expected O(1).
The byte budget bounds file length, and the entry cap bounds index metadata. Retained
text stays within its separate accounted memory budget. One decoded fragment, serializer
buffers, the codec's bounded working memory, native geometry and the caller's completed
XML string remain transient allocations. The budgets do not bound process RSS.

An unbounded in-memory dictionary would retain every string. Re-reading newly written
persistent entries in forced mode would change existing cache policy and couple reuse to
its transactions. A rotating spool could retain more recent entries after capacity is
reached, but would add free-space accounting and partial-rewrite behavior. The append-only
spool deliberately gives up those extra hits for a small, explicit lifetime contract.

## Verification and ownership

[BoundarySpill.tla](../../tests/formal/tla/BoundarySpill.tla) was checked before runtime
implementation. Its finite configuration explores every operation prefix through five
actions, three distinct payload keys, both index limits one/two and a four-byte encoded
budget. It includes successful and failed writes, oversize requests, authenticated reads,
corruption and closure. It checks capacity, fresh-entry provenance, exact hit selection
and release of the owning scope.

[Conformance](../../tests/formal/conformance/test_boundary_spill.py) replays all 18,240
checked prefixes using actual private temporary files and production admission, codec,
lookup and scope code. Write failures and corrupt bytes are injected at the file boundary.
Each complete prefix is replayed before comparing its full modeled observation, so a
locally reachable state cannot hide an incompatible earlier operation.

API operations are atomic in the model because the spool has no other reader or writer;
failed partial bytes are never indexed. Process death ends the disposable scope rather
than recovering an intermediate index. This is not a durable-write proof. Shared payload
codec proofs and conformance cover reversible compression; tiny symbolic payloads in
this protocol model use the codec's raw fallback. Ordinary tests cover compressed frames,
exact rendered XML, forced prior-cache misses, byte/index caps, failure fallback and file
closure. The existing staged KMZ publication contract remains responsible for replacing
only complete archives.

Owners are [boundary fragments](../../src/kml_io/fragments.py) and the
[document scope](../../src/kml_io/geometry.py). The broader formatting and publication
rules remain in [output serialization](output-serialization.md).
