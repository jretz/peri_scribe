# Sealed diagnostic log segments

`tla/LogSegments.tla` checks the extension from one monthly archive/plain pair to a
legacy archive followed by numbered immutable segments and an active tail. Atomic
rename publishes a complete tail as a plain segment. Each segment then uses the
already checked `LogRotation` receipt protocol: receipt publication, archive
replacement, plain removal and receipt retirement are independently interruptible.

The safety configuration explores 54 distinct states, with two successive segments,
three byte-identical diagnostic occurrences, an older legacy occurrence and up to two
process interruptions. Its invariants require exact retained occurrence order and
multiplicity, archive publication before source retirement, receipts for overlapping
published/plain copies, and completion of earlier segments before a later seal.
The complete finite check passed before implementation.

`conformance/test_log_segments.py` materializes every checked state's active source,
plain and compressed segments, legacy archive and authenticated receipts. The real
`log_reading.complete_lines` must return the complete `expected` sequence supplied by
TLC, including legitimate identical diagnostics. The adapter does not calculate an
independent expected selection algorithm. Ordinary regressions execute the actual
writer at both sides of rename, receipt publication, archive publication, source
removal and receipt removal, then retry and append a distinct later occurrence.

The model abstracts exact file bytes with occurrence values and checksum equality with
authenticated identity. Python conformance uses actual JSONL, Zstandard and SHA-256.
Existing receipt/reader conformance retains its separate multi-epoch checks. This
segmentation check adds no claim about archive corruption, external writers, filesystem
implementations or power-loss durability. It assumes the cooperative directory lock,
atomic rename/replacement, immutable completed segments and collision-resistant hashes.
It checks safety within the stated bounds, not unbounded liveness or bounded monitor
latency. Monitor regressions cover retained inode cursors and replay after a new sealed
archive appears; these adapters do not alter the abstract occurrence protocol.
