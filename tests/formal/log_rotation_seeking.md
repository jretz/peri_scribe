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
times; undated records occupy bytes but cannot move the timestamp boundary. The safe
reference boundary retires only an older prefix before the first dated occurrence at or
beyond the inclusive cutoff. Within that prefix it stops immediately after the final
complete older record, retaining subsequent undated diagnostics.

The proofs establish that:

- The safe boundary is the exact end of a complete prefix containing no eligible dated
  occurrence, stays within complete bytes, and ignores unfinished tail length.
- For every timestamp ordering, no dated occurrence at or beyond the lower bound is
  skipped. A forward scan carrying the byte position and last older endpoint equals
  the independent recursive reference for arbitrary positive record lengths.
- Dropping that byte prefix and filtering dated records gives exactly the same ordered
  sequence as filtering the entire file. This preserves occurrence multiplicity, not
  merely set membership, without assuming clock monotonicity.
- Window selection filters every occurrence independently. It preserves order and
  multiplicity, applies both inclusive bounds, and distributes over appended histories.
  A too-new record cannot hide a later eligible record after rollback.
- On chronologically ordered logs the safe boundary equals the earlier last-old-record
  reference. The existing binary-search proofs remain valid under their stated
  chronological premise; production uses the checked forward scan.

`OracleLogSeeking.lean` executes both the proved forward scan and the recursive safe
reference, then applies the complete window filter. `conformance/test_log_seeking.py`
compares the actual Python seek offset, exact byte suffix, and returned occurrences with
this compiled oracle for **8,184 histories**. The cases exhaust all sequences of zero to
four dated/undated records over three dated times, with three byte-layout variants, four
cutoffs, and presence/absence of an incomplete tail. They exercise forward and backward
clock changes, Unicode byte widths, escaped quotes and braces, misleading nested
timestamps, equivalent timezone offsets, missing/unparseable timestamps, inclusion
filtering, and inclusive upper bounds. Every history uses actual plain files and
concatenated Zstandard frames, including frames split within a record. No Python search
translation supplies expected results.

Another **128 real monitor reader lifetimes** cover every three-record timestamp
ordering in plain and archived storage. The compiled oracle determines retained run
observations; repeated catch-up must not duplicate them, and file bytes stay unchanged.
Ordinary regressions were confirmed failing before the fix: a `00:00, 00:02, 00:01`
history sought from `00:02` returned EOF, and an upper-bound violation hid a matching
later occurrence in both plain and compressed logs. The regressions also cover actual
monitor startup and unchanged recorded timestamps.

### Seeking cost and limits

Seeking now scans the old byte prefix through the first eligible dated occurrence,
using bounded memory and lightweight timestamp extraction. Startup can therefore read
the entire old prefix, and upper-bound queries continue through the rest of a component.
Ordinary follower polls keep their retained cursor and do not repeat startup seeking.
Compressed reads already scan their input sequentially. Long reads hold the shared
rotation lock longer and can delay cooperating writers; no bounded latency is claimed.

The theorem proves the abstract byte-record algorithm. Finite conformance connects real
UTF-8, JSON timestamp extraction, calendar parsing, file operations, and Zstandard
decompression. It does not prove those parsers, source-clock truth, libraries, or
arbitrary concurrent mutation. The existing reader/rotation contract supplies coherent
files and stable discovery; externally placing records into the wrong monthly filename
is outside time-based month discovery.

Plain and compressed readers deliberately have different treatment of old undated
prefixes: a plain file retires the older prefix before its first eligible timestamp,
whereas a compressed file
scans from the beginning and can retain earlier undated diagnostics. The oracle checks
each policy separately. Completeness claims for plain files concern eligible dated
records and undated records remaining after prefix retirement, not all undated history.
