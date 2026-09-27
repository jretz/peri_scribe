# Readers composed with log rotation

[LogReaders.tla](tla/LogReaders.tla) composes the existing receipt-based
[LogRotation](tla/LogRotation.tla) protocol with reader acquisition, archive reading,
plain-tail reading, retained cursors, archive-change reset, and release. Both
[safety](tla/LogReaders.cfg) and
[liveness](tla/LogReadersLiveness.cfg) explore **3,050 states**: an optional archived
prefix, two equal diagnostic occurrences, one equal late append, at most two writer
interruptions, and two complete reads. Each delivered read contains exactly the ordered
occurrences present when it acquired the lock, including legitimate equal records.

The writer lock spans receipt replacement, archive publication, and source retirement;
a process interruption releases that lock but leaves each already completed mutation.
Readers interpret authenticated receipts without recovering or mutating them. A receipt
whose target archive is published selects only that archive. Otherwise, the retained
archive precedes the distinct plain tail. Reads cannot mix generations while a writer
moves records between those representations.

## Implementation connection

- [log_reading.py](../../src/peri_scribe/log_reading.py): `read_lock` acquires the existing
  directory lock in shared mode; `log_components` selects nonoverlapping representations;
  `complete_lines` streams the selected month while holding that lock. Timestamp filtering
  and incomplete-record handling remain covered by [LogSeeking](log_rotation_seeking.md).
- [logging.py](../../src/peri_scribe/logging.py): `rotation_committed` validates the same
  checksums used by `recover_rotation`, without deleting either source or receipt.
- [monitor/history.py](../../src/peri_scribe/monitor/history.py): `Reader.poll` selects
  the archived prefix and hands the remaining source to the follower in one shared-lock
  interval. If an already observed archive changes, it closes retained cursors and
  rebuilds the recent window with full run-context restoration. A late plain tail
  archived entirely between polls therefore remains visible without duplication.
- [monitor/storage.py](../../src/peri_scribe/monitor/storage.py): `Follower.poll` opens
  sources under the shared lock and excludes a receipted source already in its archive.
  Existing descriptors still drain before retirement.

[Conformance](conformance/test_log_readers.py) exports TLC's checked reader states and
materializes all **20 distinct durable reader projections** as real plain files,
Zstandard archives, and checksummed receipts. Both filename representations yield the
exact formal observation. The actual monitor preserves the same occurrence order,
repeated polls do not duplicate records, and all reads preserve file names and bytes.
An additional real concurrent `append_monthly_records` call reaches its exclusive lock
while a reader is streaming, waits until that reader finishes, rotates, and appends.
The observations before and after publication match the two corresponding TLC snapshots.
A further **110 pairs of successive observations** are obtained by following actual TLC
successor edges from one completed read to the next. The same real monitor survives
both observations while actual files transition between the corresponding durable
representations. This exercises unchanged cursors, conservative replay, repeated
identical records, receipt recovery states, and late tails archived between polls.

Four ordinary regressions failed before the fix:

- Reading an archived month with an identical late plain append lost archived records.
- Reading after interrupted archive publication lost its older prefix.
- Monitor startup omitted archived runs when a late plain tail existed.
- A running monitor missed late tails archived entirely between polls.

Existing tests confirm that replay restores earlier command context and does not
duplicate already observed events. Further ordinary checks cover invalid receipts,
nonexistent months, read-only behavior, retained generator locks, and monitor errors.

## Assumptions and limits

The lock file is stable and already exists for active cooperating writers. An inactive
copy without that file remains readable without creating anything; concurrent conversion
of an unlocked copied directory into an active log directory is outside this contract.
Uncooperative writers and filesystem corruption are outside the modeled transitions;
invalid receipts produce explicit reader errors. Checksum identity relies on SHA-256.

A shared lock remains held throughout iteration, so large reads can delay writers;
abandoned generators must be closed promptly. Reader callbacks must not acquire the
same directory's writer lock; current production filters and consumers are pure.
Multiple readers may share that interval.
The finite model represents one reader at a time and assumes weak fairness of reader
and writer progress, finite reads, and eventual cessation of writer failures. It does
not establish OS lock scheduling fairness or power-loss durability. Incomplete records,
log filtering, and separately requested historical archive browsing retain their
existing contracts. Archive change detection uses device, inode, size, and nanosecond
modification time, assuming cooperating atomic replacements change that signature.
The model permits conservative replay even when archive contents do not change.
Continuous monitor cursors also have their own lifecycle models; the extended model
checks archive reset and incremental drain across successive complete observations.
The Python bridge exercises finite histories and is not a proof of full refinement.
