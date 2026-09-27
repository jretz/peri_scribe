# Durable update validation

`DurableUpdateValidation.tla` distinguishes absent, valid, and invalid fire-update
checkpoints and journals before recovery, a new completed publication, or viewer output.
The safety and liveness configurations were checked before changing production code.

## Contract and implementation

Missing authoritative state permits initialization. Existing unreadable or schema-invalid
state raises its error and stays in place. A rejected operation must not append records,
acknowledge mapping, retire a journal, or replace the snapshot. The generic publication
cache reader still treats an invalid cache as missing. That cache policy does not apply
to the retained update intent.

| Model action or property | Production owner |
| --- | --- |
| Validate retained checkpoint and journal | `fire_updates.read_authoritative`, `recover_updates` |
| Validate the complete incoming batch before recovery or equality checks | `fire_updates.write_updates`, `PendingUpdates` |
| Validate shared log payloads and finite, nonnegative acreage | `fire_update_records.Record`, `Acreage`, `validated_records`; `updates.LogEntry` |
| Validate encoded history keys and targets | `fire_update_records.canonical_identity`, `fire_updates.State` |
| Append, acknowledge, retire | `recover_updates`, `logging.append_monthly_records`, `publication.write_state` |
| Validate ownership before replacing viewer outputs | `updates.write_updates_page` |

Every identity key and target in the checkpoint must use the exact `json.dumps` encoding
of a supported pair. The accepted kinds are `id`, `name`, `local`, and `component`; empty
strings remain valid. Rejecting alternate whitespace or escape encodings prevents two
encoded spellings from receiving different owners before collapsing into one decoded
snapshot key. This does not prohibit owner chains, owner cycles, shared lineage, or
unclaimed historical buckets. Those are valid inputs to the one-hop ownership projection.
Previously emitted canonical checkpoints and legacy records without `log_identity` remain
readable.

Both configurations explore **797 distinct states**, starting from **252 distinct initial
states**. They cover recovery, writing, and viewing; missing/valid/invalid retained inputs;
valid/invalid incoming records; changed/equal checkpoints; empty/nonempty batches; and
already appended batch IDs. Invalid intent remains untouched. Every durable effect follows
complete validation; complete append precedes acknowledgment, which precedes retirement.
The liveness configuration checks eventual completion or rejection under weak fairness.

## Executable connection

`helpers/durable_updates.py` exports TLC's actual initial nodes and directed edges. It
follows each complete path to its terminal state and replays all **252 input combinations**
through the actual filesystem owners. Observation wrappers call the real operations and
compare the exact ordered append, acknowledgment, retirement, new-journal, rotation, and
viewer effects with that path. They also compare the resulting checkpoint, journal
presence, complete ordered record payloads, original completion timestamps, and batch IDs.
Every rejected case must preserve all file names and bytes, including invalid evidence.
Two distinct records per nonempty batch expose partial-batch mistakes.

Ordinary schema and boundary regressions exercise malformed JSON, unknown schema fields
and versions, invalid timestamps, empty batch IDs, incomplete records, unsupported units,
negative and nonfinite acreage, malformed identities, noncanonical encodings, and mutable
or unvalidated nested model instances. The entire incoming batch is checked before an
older pending journal can be recovered, including when the new checkpoint appears equal.
The original corruption and equality regressions failed before the implementation fix.

The `invalid-intent-treated-as-missing` defect check changes only the strict reader to
return `None` on validation errors in an isolated source copy. The unchanged conformance
test passes with pristine source and rejects this mutation with a missing-exception
diagnostic. Existing journal crash and continuous builder-path checks remain applicable
to accepted inputs.

## Boundaries

The model abstracts schema parsing into missing/valid/invalid classifications; ordinary
schema tests connect concrete invalid forms to rejection. It does not prove the Pydantic
or JSON parser implementation, diagnose arbitrary semantically wrong but schema-valid
content, or repair corruption. Invalid evidence is intentionally retained for diagnosis.
The view validates its checkpoint and readable log records; it does not recover a pending
journal. Only recovery and writing consume and validate that journal.

Validation and subsequent writes assume one cooperating writer with stable files during
the invocation, as supplied by the existing pipeline ownership contract. Concurrent
external edits, new corruption after validation, filesystem atomicity, power loss, and
eventual I/O completion remain outside this model. Existing journal, process-crash,
rotation, and publication protocols cover accepted-input interruption behavior. Validation
adds work proportional to retained checkpoint and batch size; it does not rewrite logs or
claim a latency bound.
