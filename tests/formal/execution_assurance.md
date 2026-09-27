# Execution paths and abrupt process termination

These checks strengthen the connection between the existing specifications and actual
executions. They add no production state transitions and do not replace the separately
documented invariant, liveness, and data-transformation contracts.

## Continuous paths through the checked graph

`helpers/tlc.py::graph` requests TLC's DOT dump with action labels. The same successful
model-checking run supplies the full variable valuations, marked initial states, and
directed successor edges. The reader checks the distinct-state and initial-state counts,
requires every edge endpoint to exist, and rejects unsuccessful or unfinished
exploration. It does not infer possible transitions from two states merely being
reachable.

`helpers/paths.py` retains every full abstract state compatible with the **entire**
concrete prefix. Initial observations must match an initial state. Each changed durable
observation must follow an actual checked edge. Between observations, the matcher can
traverse explicitly classified internal edges only when the observed projection remains
unchanged. Repeated unchanged concrete observations are stutters. A changed observation
cannot skip an intermediate change to a separately durable field.

Crashes consume explicit crash edges rather than being hidden inside that closure.
Builder generation changes and log aging are also explicit events. Explicit transitions
bind the action to its actual resulting projection, including events that change bytes.
Exiting after an already completed protocol is a documented terminal stutter: there is
no unfinished operation for its crash action to restart. Model fingerprints retain the
hidden phase, failure allowance, target, and other control state throughout matching;
identical projections do not merge unrelated graph nodes.

The following bridges now require continuous paths:

| Bridge | Checked model | Concrete observations |
| --- | --- | --- |
| `helpers/log_rotation.py` | `LogRotation` | Plain and archived occurrence sequences, receipt presence, and authenticated source/base/target identities |
| `helpers/journal_builder.py` | `UpdateJournal` | KMZ and publication generations, journal and checkpoint, viewer generation, per-batch plain/archive multiplicities, and rotation receipt presence |
| Hard-crash fetch coordinator | `FetchCrash` | Both persisted source revisions, pending derived-stage set, and forcing flag |
| Pipeline composition | `PipelineComposition` | Persisted source/output generations, pending/deferred markers, KMZ identity, and publication checkpoint across complete invocation histories |
| Parsed-cache recovery | `ParsedCache`, `ParsedCacheRebuild` | Committed full row payloads, receipts, memberships, and schema presence across rollback/reset and retry |
| Geography publication and reading | `GeographyPublication`, `GeographyReaders` | Exact artifact/signature identities, acknowledgment, held locks, and ordered layer results |

The rotation bridge still covers all 162 two-epoch interruption histories. The builder
bridge covers the same 50 before/after fault scenarios, retaining its real
serialization, per-fire payload, timestamp, idempotency, and viewer checks. The
fetch-only path contract excludes the model's `Derive` action because these subprocesses
do not execute derived stages. Successful recovery therefore retains required work
instead of explaining its removal through an unperformed stage.

Seven adversarial checks exercise the matcher against an actual exported `LogRotation`
graph. They accept internal steps and stutters, reject backwards reordering of states
that are individually reachable, reject skipping a durable operation, enforce the crash
budget, reject a reachable noninitial start, bind explicit actions to their observed
mutation, and reject changed projections at terminal-exit stutters. The
[pipeline/cache/geography extension](execution_paths_extensions.md) documents additional
continuous histories and a publication-specific reordered-signature negative control.

The [deliberate defect checks](defect_checks.md) also roll an acknowledged mapping
checkpoint back to its previous contents before restoring it. Each transient projection
is individually reachable in the model, and the final result is restored. The unchanged
builder conformance test rejects the incompatible execution path. This checks the
specific distinction between reachable-state membership and whole-prefix conformance.

The resulting evidence is trace conformance for the executions observed. It is not an
unbounded refinement proof of Python, a proof that unobserved fields are irrelevant, or
a guarantee that every possible thread schedule was exercised. Projection mappings and
the classification of internal/environment steps remain reviewable parts of the bridge.

## Actual process death and fresh recovery

`helpers/crash_worker.py` runs real production writers inside isolated subprocesses.
Each fresh interpreter imports only its selected family from `helpers/crash_workers/`,
so SQLite and rotation checks avoid loading unrelated builder and pipeline dependencies.
`helpers/process_crashes.py` starts a separate interpreter to seed a prior generation, a
second interpreter that dies at the selected operation, and a third that recovers the
same files. It verifies distinct process IDs and the exact exit status. Half the cases
use `os._exit(91)` and half send the worker `SIGKILL`.

An `atexit` handler and an enclosing `finally` would each leave a sentinel if they ran.
Both must remain absent. Ordinary exceptions, missing fault injection, assertion errors,
and successful child returns cannot count as process-crash evidence. Worker timeouts
also fail the check. All application files, SQLite databases, abandoned private staging,
and harness evidence live in each test's temporary directory.

The curated matrix contains 36 crashes and 108 separate interpreter executions:

| Area | Cases | Interruption and recovery |
| --- | ---: | --- |
| Fetch recovery requirements | 8 | Before/after pending-marker replacement, after fire-source persistence, and after evacuation persistence, with each boundary using both termination methods |
| Builder and update journal | 14 | Before/after KMZ replacement, publication checkpoint, pending journal, atomic log append, mapping checkpoint, journal removal, and viewer replacement |
| Diagnostic rotation | 8 | Before/after receipt publication, archive replacement, source removal, and receipt retirement, starting with an existing archive and repeated diagnostic occurrences |
| SQLite product generation | 6 | After each of two payload statements, after manifest publication, after pruning, and immediately before/after transaction commit |

All 36 scenarios are separate parametrized pytest items, allowing workers to schedule
them independently. Each scenario's seed, crash, and recovery interpreters still run
sequentially over the same private files. The checked model corpus is shared as immutable
data within one pytest run and published only after TLC completes successfully; session
fixtures prepare each worker's contracts once. No checked results carry over from a
previous run, and no application state is shared between scenarios.

Fetch subprocesses retain real coordinator, marker, and locking code; only external
source work is replaced with isolated persisted revisions. The unchanged retry uses the
surviving files to decide truthfully whether another revision was written. Builder
subprocesses reuse the existing controlled input geometry/rendering fixture and retain
the real KMZ, JSON, journal, log, checkpoint, and viewer persistence stack. Rotation
subprocesses acquire the actual directory `.rotation.lock`; builder and fetch workers
acquire the actual year lock. Fresh recovery must reacquire those locks after the
previous process dies.

For fetch, builder, and rotation, observations emitted on both sides of durable
operations are checked as one continuous abstract path across all three interpreters,
including the actual process-exit event. Fixture metadata records how concrete
serialized content maps to generation tokens; it does not supply expected transitions.
Recovery additionally checks exact occurrence counts and complete per-fire records.

SQLite subprocesses execute the real `row_index.store_generation` through production
`product_cache.scope`, `put`, and `prune`. The commit boundary uses a real SQLite
connection subclass solely to terminate immediately before or after `commit`. Statement
prefixes and post-crash durable outcomes come from `ProductCache`'s exported trace
states. Fresh recovery must expose the prior complete generation for every uncommitted
prefix, or the new complete generation after commit, and its authenticated row reader
must return that generation's exact groups. Python never closes or rolls back the killed
worker's transaction.

These are process-loss checks on the local filesystem and SQLite runtime. They do not
simulate storage power loss, kernel failure, writes torn inside a filesystem operation,
remote locking semantics, or arbitrary storage corruption. The matrix is curated; the
larger exception-based suites continue to explore more input combinations and
interruption histories. Tests do not contact external feeds or operate on user data.
