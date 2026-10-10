# Recoverable fire update publication

## Contract and context

After a complete KMZ is published, its interesting mapping updates must survive an
interruption between log append and checkpoint acknowledgement. A pending journal freezes
the batch records, checkpoint, aware completion timestamp, and unique batch ID. Recovery
finishes that intent before comparing any later inputs. An absent checkpoint is a fresh
start; an invalid authoritative checkpoint or journal is an error whose bytes are retained.

The contract spans [fire_updates.py](../../src/peri_scribe/fire_updates.py),
[fire_update_records.py](../../src/peri_scribe/fire_update_records.py), journal-aware
[logging.py](../../src/peri_scribe/logging.py), and its caller
[kml/builder.py](../../src/peri_scribe/kml/builder.py). The year writer and log-directory
writer locks exclude cooperating writers. Individual replacements are atomic across
process interruption. The protocol does not claim power-loss durability.

## Complexity assessment

| Dimension | Score | Concrete reason |
| --- | --- | --- |
| History and state | 2 | A retry must finish an earlier batch with its original completion time. |
| Rule interaction | 2 | Empty, unchanged, gated and fresh-input publications acknowledge different outputs. |
| Mathematical reasoning | 0 | No mathematical derivation is introduced by the persistence protocol. |
| Scale and representation | 2 | Complete schema validation and batch identity connect checkpoint, journal and logs. |
| Failure and concurrency | 3 | KMZ, journal, append, checkpoint and viewer have independently interruptible writes. |

**Total 9: complex.** Exactly-once applies to a retained, valid journaled batch, not to
arbitrary unjournaled publication attempts.

## Approach and invariants

Preparation resolves [history ownership](history-ownership.md) and freezes records without
acknowledging them. The builder then performs these independently interruptible writes
in order:

1. Replace the completed KMZ.
2. Commit its publication checkpoint when fresh frozen publication inputs are available.
3. Replace the update journal, freezing records, mapping checkpoint, completion timestamp,
   and stable batch ID.
4. Under the log lock, recover pending rotation and append the complete batch atomically
   if its ID is absent from retained logs.
5. Replace the mapping checkpoint to acknowledge the updates.
6. Remove the journal.
7. Replace the viewer.

Recovery resumes the journaled obligations at step 4 using the frozen inputs.

The batch ID and timestamp are created once in the journal. Under the log lock, recovery
rotates pending months, looks for the batch in both plain and compressed representations,
and skips an already retained batch. A new journaled append copies the destination to a
private file, writes the complete batch, and replaces the destination atomically.
Recognizing any occurrence of a batch is sufficient only because its append is all-or-none.

Validate every record before writing any journal or batch: finite nonnegative acreage in
acres, schema fields, and canonical encoded identity pairs. Invalid stored intent must
never be treated as absence. The disposable publication measurement cache has a different
error policy and is not authoritative update intent.

The surviving journal identifies the recovery action at each interruption point:

| Retained state | Next recovery action |
| --- | --- |
| Journal, no retained batch, old mapping checkpoint | Append using the journal's time and batch ID, replace the checkpoint, then remove the journal. |
| Journal and complete retained batch, old mapping checkpoint | Skip append, replace the checkpoint, then remove the journal. |
| Journal, complete retained batch, current mapping checkpoint | Skip append, rewrite the same checkpoint idempotently, then remove the journal. |

Keeping the journal until acknowledgement closes both the append and checkpoint
interruption windows.

## Worked examples and boundaries

A batch b is journaled at 23:59 on September 30 and appended successfully. The process
stops before checkpoint replacement. On October 1, recovery uses the September timestamp
and b, finds b already retained, replaces the checkpoint, then removes the journal.
It does not append an October occurrence or shift the update time. If rotation has since
moved b to an archive, the same membership check applies.

An empty batch still advances all mapped-fire baselines and rotates older months. If the
new state is already the acknowledged state, `write_updates` performs an empty rotation
check without creating another journal. This is necessary because becoming interesting
alone must not manufacture a new mapping update.

Counterexamples explain the ordering. Removing the journal before replacing the mapping
checkpoint loses the acknowledgement after a crash. Appending individual records in place
and treating one matching ID as a complete batch can omit the remaining records. Retrying
with a fresh ID duplicates records. Regenerating a pending batch from newer inputs changes
what the completed KMZ is supposed to acknowledge.

A KMZ-only gated build without fresh geography invalidates its publication checkpoint
after the viewer returns. An ungated/standalone build may leave an older checkpoint file,
but that file cannot authorize a skip unless it identifies the current KMZ. Mapping and
publication checkpoints therefore have distinct meanings.

## Costs and limitations

For B serialized batch bytes and L existing destination bytes, atomic append requires
O(L + B) I/O and temporary disk space. Batch lookup scans retained lines and may decompress
an archive; memory includes all prepared records and serialized entries. Checkpoint work
is proportional to retained history. Rotation costs are covered in
[log retention](log-retention.md).

Hash/UUID collisions, forged metadata, corrupt archives, noncooperating writers, and
power loss are outside the recovery guarantee. A KMZ overwritten before its journal is
created has no retained intent to replay. Viewer freshness is eventual after successful
recovery and rebuilding, not atomic with the other files. Progress requires future
invocations and an eventual end to failures.

## Implementation and verification

[Recovery regressions](../../tests/tests/standard/peri_scribe/test_fire_updates_recovery.py)
and [validation regressions](../../tests/tests/standard/peri_scribe/test_fire_updates_validation.py)
exercise interruption and invalid retained bytes. [Record tests](../../tests/tests/standard/peri_scribe/test_fire_update_records.py)
exercise the serialized contract.

The [TLA+ update-publication inventory](../../tests/formal/tla/README.md#update-publication-and-journal-recovery)
identifies every durable action and the bounded two-batch/two-interruption model.
[Journal replay](../../tests/formal/tla/journal_replay.md) and
[durable update validation](../../tests/formal/tla/durable_update_validation.md) describe
actual-file and schema conformance. [Execution assurance](../../tests/formal/execution_assurance.md)
adds abrupt-process recovery; it does not extend the fault model to storage power loss.
