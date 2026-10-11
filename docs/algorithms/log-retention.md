# Log rotation, coherent reads, and time windows

## Contract and context

[logging.py](../../src/peri_scribe/logging.py) retains monthly JSONL occurrences while
compressing older months. [log_reading.py](../../src/peri_scribe/log_reading.py) reads a
coherent monthly sequence across the archive and any later plain tail. Ordinary identical
diagnostic lines are distinct occurrences; only journal batches have an explicit
idempotency identity. Inputs may contain undated/malformed lines, UTF-8 text, incomplete
last lines, and equal timestamps. Dated occurrences have nondecreasing timestamps within
each logical monthly log, compared as aware instants. This requirement permits byte-offset
binary search; timestamp regressions in stored logs are outside its completeness
guarantee. Date-window endpoints are inclusive.

Writers and readers cooperate through `.rotation.lock`. A reader holds the shared lock
through iteration; callers must close abandoned iterators promptly. Rotation uses local
calendar months, retaining a closed month for seven complete calendar days. Window
comparison uses aware instants, with naive parsed timestamps interpreted as UTC.

## Complexity assessment

| Dimension | Score | Concrete reason |
| --- | --- | --- |
| History and state | 2 | Late arrivals and retained reader cursors span several rotation epochs. |
| Rule interaction | 2 | Receipt authentication determines whether a plain file is a duplicate source or a new tail. |
| Mathematical reasoning | 1 | Binary probes must preserve the inclusive boundary across unequal byte lengths and undated records. |
| Scale and representation | 3 | Streaming compressed frames and byte cursors preserve complete records without materializing archives. |
| Failure and concurrency | 3 | Receipt, archive replacement and source retirement survive separate interruptions under shared/exclusive locks. |

**Total 11: complex.** Streaming is bounded by record size and batch-ID sets, not by a
promise that every line or journal is small.

## Approach and invariants

Prepare a target archive privately from the old archive and closed plain source. Ordinary
occurrences are copied without value deduplication. Journal batches already in the old
archive are excluded using their explicit IDs. Before publishing, write a receipt with
SHA-256 checksums for the source, previous archive and target archive. Publish the target,
remove the plain source, then remove the receipt.

On recovery, a target-matching archive authorizes retirement only if any remaining source
still matches its receipted checksum. Otherwise both old archive and source must match
preparation inputs before rebuilding. An unexpected checksum or malformed receipt fails
closed. Discover pending receipts even when their source is absent or calendar policy no
longer selects the month, so a late append cannot recreate a source before retirement.

A reader performs the same authentication without modifying files. A committed receipt
selects archive only; otherwise select archive followed by the distinct plain tail.
Holding the shared lock across both components prevents a mixed view during rotation.
Physical duplication is permitted while logical occurrence duplication is forbidden.

`seek_since` binary-searches byte positions within the observed plain-file size. A probe
skips a split line and reads forward to the next complete dated record. An older timestamp
moves the lower bound just after that record; a recent timestamp or absent complete
timestamp moves the upper bound to the probe. Ordered dated records make these decisions
monotonic. The result is immediately after the last complete old record, leaving following
undated records and any incomplete tail available. After seeking, filtering tests every
occurrence independently so an upper-bound violation cannot hide later undated diagnostics.
Lightweight token scanning tracks JSON nesting so a nested source timestamp cannot move
the root timestamp boundary.

## Worked examples and boundaries

Start with two byte-identical diagnostic occurrences d,d in the plain source:

1. Prepare the target archive from the old archive and d,d. The receipt authenticates
   the source, old archive, and prepared target.
2. Publish the target, then crash before unlinking the source. Both files physically
   contain d,d, but the matching receipt selects the archive alone. A retry retires the
   source instead of appending it twice.
3. After source and receipt retirement, a new d appended to the plain log is a distinct
   late occurrence. Read the archive followed by this new tail; the next rotation
   produces d,d,d. Deduplicating by line bytes would incorrectly produce d.

For records in file order 00:00, undated, 00:01, 00:01, 00:02, seeking from 00:01 retires
only the first record. The intervening undated diagnostic and both equal-time occurrences
remain. Seeking from 00:02 instead retires through the second 00:01 occurrence. An
unfinished last JSON record is not delivered until a newline completes it; UTF-8 byte
offsets must never become character offsets.

A sequence 00:00, 00:02, 00:01 violates the storage ordering contract. Binary probes cannot
establish that no hidden earlier eligible occurrence exists; there is no inferred safety
from sampling only part of the file. The monitor's separate observation clock can still
move backward and must invalidate time-dependent caches.

Plain seeking deliberately retires undated history before its last old dated boundary.
Compressed reads scan from the beginning and can retain earlier undated diagnostics.
These are explicit different startup policies. Month discovery assumes records are placed
in the correct writer-local monthly file. The [monitor](monitor-evidence.md) adds retained
inode cursors, archive-change replay and context restoration.

## Costs and limitations

Let A be archived bytes, P plain bytes, D decompressed archive bytes, and J distinct journal
batch IDs. Rotation hashes and copies O(A + P) bytes and may scan O(D) to collect batch
IDs; temporary disk holds the new archive, and memory is O(J + largest line) beyond codec
buffers. Plain startup seeking uses O(log P) byte probes, followed by a linear read of the
selected suffix. Each probe scans forward across at most the remaining split record and
an undated stretch; long records or long undated stretches can make the bytes read exceed
O(log P). Memory is bounded by the largest line. Compressed components remain sequential
streams. Shared locks can delay writers during long reads; no bounded writer latency is
claimed.

Atomic file replacement, stable cooperative locks, immutable compression sources, valid
archives and collision-resistant checksums are assumptions. Rotation is not exactly-once
delivery for unjournaled appends, corruption repair, or power-loss durability. Temporary
files abandoned by hard process death are not authoritative retained logs.

## Implementation and verification

[Rotation tests](../../tests/tests/standard/peri_scribe/test_logging_rotation.py),
[window tests](../../tests/tests/standard/peri_scribe/test_log_reading.py), and
[reader/rotation tests](../../tests/tests/standard/peri_scribe/test_log_reading_rotation.py)
cover concrete records and failure boundaries. The
[rotation and seeking inventory](../../tests/formal/log_rotation_seeking.md) maps the
receipt protocol to TLA+ and sequence/window reasoning to Lean, including variable byte
lengths and incomplete tails. [Reader composition](../../tests/formal/reader_rotation.md)
checks repeated coherent reads. Relevant executable connections are
[log seeking](../../tests/formal/conformance/test_log_seeking.py),
[log rotation](../../tests/formal/conformance/test_log_rotation.py), and
[log readers](../../tests/formal/conformance/test_log_readers.py). Finite file conformance
does not prove parsers, decompression, source clocks or filesystem implementations.
