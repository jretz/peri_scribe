# Diagnostic log rotation and byte seeking

These checks cover `logging.compress_log`, `recover_rotation`, `rotation_paths`, and
`append_monthly_records`, together with `log_reading.timestamp_after`, `seek_since`,
and `complete_lines`. Rotation and seeking have separate contracts: rotating an archive
preserves occurrences, while seeking and window selection admit arbitrary timestamp
order, including backward wall-clock adjustments.

## Rotation protocol

`LogRotation.tla` treats each durable operation separately. Compression prepares a
private archive, atomically publishes a receipt, replaces the archive, removes the
plain source, and removes the receipt. A receipt at `<month>.jsonl.rotation.json`
records SHA-256 identities of the source, previous archive, and prepared target.
Recovery authenticates the retained files before deciding whether to rebuild the target
or finish retiring a source already included in the published archive.

The directory's cooperating writer lock covers recovery, rotation, and append. Pending
receipts are discovered even when their source has already been removed or its month is
no longer eligible for compression. Recovery therefore finishes before an identical late
record can recreate that month's source. Invalid receipts or unexpected source/archive
changes fail closed, leaving the retained data available for investigation.

The checked guarantees are:

- The logical retained sequence preserves every occurrence and its order, including
  byte-identical diagnostics and a byte-identical late arrival.
- A published receipt authenticates either the previous archive or the prepared target;
  source retirement requires the target to have been published.
- Interruption before publication leaves a recoverable source. Interruption after
  publication cannot cause the source to be appended a second time on retry.
- Completed rotation has no plain source or pending receipt. With fair progress and an
  eventual end to failures, both rotation epochs finish with the complete archive.

The safety and liveness configurations each explore 156 distinct states. They include
an empty or nonempty initial archive, two identical initial diagnostic occurrences, one
identical late occurrence, two rotation epochs, and up to two process interruptions.
Private preparation, receipt publication, archive replacement, source removal, and
receipt retirement are distinct actions. This is exhaustive within those finite bounds.

`conformance/test_log_rotation.py` replays 162 histories: absent/existing archives and
all combinations of no interruption or interruption immediately before/after each of
four durable boundaries in both epochs. It runs the actual compressor and recovery on
real JSONL and Zstandard files. Every replacement and deletion is observed, and the
plain/archive occurrence sequences and authenticated receipt fields must belong to the
state graph exported by TLC. The final archive must preserve the exact occurrence order.
The [deliberate defect checks](defect_checks.md) require the unchanged replay to reject
an implementation that bypasses receipt recovery.

`UpdateJournal.tla` also separates receipt publication, archive replacement, source
removal, and receipt retirement. Its safety and liveness configurations explore 49,596
distinct states. Its batch-ID deduplication contract remains separate from diagnostic
occurrence preservation. The [journal recovery bridge](tla/journal_replay.md) continues
to exercise real builder and journal recovery against the expanded state graph.

### Rotation findings and limits

An ordinary regression first demonstrated that interruption after archive replacement
but before source removal duplicated diagnostic records on retry. The receipt protocol
fixes that defect without deduplicating legitimate identical diagnostics. Ordinary
regressions preserve both the original failing case and all publication/retirement
boundaries, malformed/stale receipts, late appends, and recovery without a source.
Archives containing duplicates from earlier executions are not rewritten.

The occurrence invariant concerns the logical retained representation. During recovery,
the plain source and archive can temporarily contain the same bytes. The authenticated
receipt distinguishes a committed source from new append work; it is not a promise that
physical bytes exist only once. The separate [reader composition](reader_rotation.md)
model checks archive/plain selection under the writer lock, including authenticated
committed receipts and successive monitor observations. Its implementation bridge
preserves the older archive prefix when the month also has a late plain tail.

The filesystem assumptions are atomic replacement, cooperative locking, immutable
closed sources during compression, valid existing archives, and collision-resistant
SHA-256 identities. Fault injection models process interruption, not power-loss
durability, filesystem correctness, arbitrary external writers, corruption recovery, or
receipt forgery. Temporary preparation directories left by a hard process death are
outside the retained-log contract. Ordinary append atomicity and journal batch identity
have their own checks; this model does not imply exactly-once delivery of an unjournaled
append.

## Seeking proof and implementation connection

`lean/PeriScribe/LogSeeking.lean` separates complete records with positive, variable
byte lengths from an arbitrary incomplete final tail. Dated records use natural-number
times; undated records occupy bytes but cannot move the timestamp boundary. Production
queries require nondecreasing dated timestamps within each logical monthly log. The
reference boundary is immediately after the last complete record older than the inclusive
cutoff; subsequent undated diagnostics and unfinished tail bytes remain available.

`chronological_byte_search_matches_reference` proves that byte-offset binary search,
using the next complete dated record after each probe, equals that reference. The proof
covers arbitrary positive record lengths, duplicate timestamps, undated positions, and
unfinished tail lengths. `safe_boundary_equals_ordered_reference` connects ordered
logs to the independently defined prefix-retirement policy. The separate window proofs
preserve occurrence order and multiplicity while applying inclusive bounds and retaining
undated diagnostics. Upper-bound violations do not terminate the stream.

`OracleLogSeeking.lean` executes the proved binary search and independent recursive
boundary. `conformance/test_log_seeking.py` compares actual Python seek offsets, exact byte
suffixes, and plain/compressed occurrences with this compiled oracle for **3,840
histories**. Cases exhaust sequences of zero to four records over three nondecreasing
dated times and arbitrary undated positions, with three byte-layout variants, four
cutoffs, and presence/absence of an incomplete tail. They exercise Unicode byte widths,
escaped quotes and braces, misleading nested timestamps, equivalent timezone offsets,
missing/unparseable timestamps, inclusion filtering, and inclusive upper bounds. Actual
files and concatenated Zstandard frames include frames split within a record. No Python
search translation supplies expected results.

Another **76 real monitor reader lifetimes** cover every three-record ordered dated/
undated sequence in plain and archived storage. The compiled oracle determines retained
run observations; repeated catch-up must not duplicate them, and file bytes stay unchanged.
The earlier arbitrary-order prefix-retirement theorems remain mathematically valid but
are not the production seek contract. A stored sequence such as `00:00, 00:02, 00:01`
violates the explicit ordering assumption and may cause binary search to skip eligible
records. Observation-clock reversal remains supported by monitor retention/projection.

### Seeking cost and limits

Plain seeking makes O(log P) byte probes for P file bytes. Probe cost includes scanning
past a split record and any undated stretch before a usable timestamp; unusually long
records or undated stretches can dominate bytes examined. Startup then reads the selected
suffix, while ordinary follower polls keep their cursor. Compressed components stream
sequentially. Shared locks can delay writers; no bounded latency is claimed.

The theorem proves the abstract byte-record algorithm. Finite conformance connects real
UTF-8, JSON timestamp extraction, calendar parsing, file operations, and Zstandard
decompression. It does not prove those parsers, source-clock truth, libraries, or
arbitrary concurrent mutation. The existing reader/rotation contract supplies coherent
files and stable discovery; records placed into an incorrect monthly filename are outside
time-based month discovery.

Plain and compressed readers have different treatment of old undated prefixes: plain
seeking retires the prefix through the last older dated record, whereas compressed reads
scan from the beginning and can retain earlier undated diagnostics. The oracle checks
each policy separately. Plain completeness concerns eligible dated records and undated
records after prefix retirement, not every undated record in history.
