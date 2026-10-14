# Physical update logs composed with current snapshots

The order of saved update records determines which acreage becomes a fire's previous
measurement. Reading a plain tail before its older archive can therefore reverse the
meaning of a later update, even if every record is present.

`PeriScribe/UpdateLogChronology.lean` connects the `LogReaders` coherent-selection
contract to the complete projected snapshot reference. Its ten theorems and the
3,050-state `LogReaders` safety configuration were checked before changing the update
reader. This connection requires no new temporal transitions or executable oracle.

## Contract and implementation

For each logical month, an archive is the retained prefix and an unreceipted plain file
is a later tail. A receipt authenticating the published target archive means any remaining
plain file is already represented in that archive. Selection must preserve every logical
occurrence exactly once and in its original order. Equal payloads without a committed
receipt are distinct occurrences; payload deduplication is not permitted.

`updates.read_entries` takes the existing shared directory lock before discovering months,
selects each month once, and uses `log_reading.log_components` for ordered, authenticated
components. The lock spans discovery, opening, and validation of every retained record.
The reader does not recover receipts, remove plain files, or change log bytes.

Every nonblank line still passes through `updates.LogEntry` validation. A damaged final
line raises an error; a complete legacy JSON record without a trailing newline remains
readable. The diagnostic reader's policy of skipping unfinished lines is deliberately
not applied to authoritative update history.

The Lean composition proves:

- A committed physical source copy contributes no extra occurrences.
- An uncommitted plain tail follows its archive, retaining repeated equal rows.
- Coherent logical month selection followed by snapshot generation equals the existing
  complete-history reference for arbitrary following history and ownership maps.
- Removing an already archived physical source does not change the snapshot.
- The latest late occurrence supplies its current owner's historical acreage baseline.
- Chronological sorting preserves the input order of equal-time occurrences in arbitrary
  histories.

Two checked examples distinguish the historical baseline: archived acreage 100, then late
acreage 200 at the same old timestamp, followed by a visible update of 150, must use 200
as the previous acreage. Reversing those old occurrences instead produces baseline 100.

## Executable connection

`helpers/update_log_chronology.py` obtains all **20 distinct physical reader projections**
from the actual checked TLC states. It uses the shared rotation fixture to materialize
plain JSONL, Zstandard archives, and receipts with actual checksums. The expected logical
occurrence sequence comes directly from TLC, without calling a production selector.

Those states are crossed with three timestamp orders and four identity/ownership layouts,
giving **240 complete filesystem-to-snapshot comparisons**. They include equal timestamps,
clock rollback, repeated identical records, independent histories, merged histories,
one-hop cyclic ownership, and distinct local/component identity tags. Old records precede
the visible window and a current 150-acre occurrence tests their effect on its baseline.

For each case, the existing compiled Lean `projected-snapshot` oracle receives TLC's
logical sequence and the independently supplied owner map. Its output determines the
complete expected emitted sequence, current owner, and previous acreage. Conformance
compares actual `read_entries` order and every retained payload field, then calls the real
`write_updates_page` and reads back `updates.json`. Log and checkpoint bytes must remain
unchanged throughout.

An additional real concurrent schedule pauses update validation while a monthly writer
attempts its exclusive lock. The writer must wait until the complete reader returns.
It then rotates and appends using the production writer, and a subsequent read must match
the corresponding checked TLC observation. Observation wrappers retain actual parsing,
filesystem writes, and OS lock behavior.

The two ordinary chronology regressions failed before the fix: the reader placed the
plain tail first, and the current 150-acre update consequently reported growth from 100
instead of a decrease from 200. Further ordinary tests cover interruption before and after
archive publication, read-only receipt interpretation, invalid authentication, repeated
equal occurrences, strict malformed-record rejection, and legacy newline compatibility.

## Boundaries

The rotation configuration retains its finite bounds: two equal source occurrences, an
optional archived prefix, one late append, two interruptions, and two reader observations.
The Lean composition and equal-time stability theorems quantify over arbitrary lists;
the filesystem bridge exercises the finite cases above and is not a full Python refinement
proof.

As in the existing log-reader contract, active cooperating writers use a stable directory
lock. An inactive copied directory without that lock remains readable; concurrently
turning it into an active directory is excluded. External file edits, parser and compression
implementation correctness, SHA-256 collisions, and power-loss durability retain the
existing assumptions. Current ownership checkpoints are protected by the caller's year
writer ownership when the pipeline publishes a snapshot. This does not establish
an independent cross-file checkpoint/log transaction for unlocked external callers.

The shared lock covers reading and validating all retained update history. Records older
than the visible window still matter because they can supply the previous acreage.
Large histories can therefore delay cooperating appenders and rotation until validation
finishes. No latency bound is claimed.
