# Cancellation and monitor resource ownership

## Contract and context

Cancelling an asynchronous coordinator does not stop its Python worker thread. Resources
used by that thread must stay alive until work settles. The generic blocking-worker
adapter preserves cancellation as the caller's outcome while waiting for worker cleanup.
The monitor adds exclusive ownership spanning snapshot, worker execution and publication,
plus a stop barrier before descriptor shutdown.

Inputs are an operation, its optional cooperative thread-stop event, and monitor lifecycle
requests. Outputs are either its completed result/error or cancellation after settlement.
The contract assumes awaited work and cleanup eventually finish; it establishes ownership
and ordering, not a cancellation deadline.

## Complexity assessment

| Dimension | Score | Concrete reason |
| --- | --- | --- |
| History and state | 2 | Admission, active work, cancellation, stop and descriptor retirement have distinct states. |
| Rule interaction | 2 | Caller cancellation and monitor shutdown permit different publication outcomes. |
| Mathematical reasoning | 0 | The protocol introduces no numerical derivation. |
| Scale and representation | 1 | One admitted operation and bounded owner state coordinate each monitor. |
| Failure and concurrency | 3 | Repeated cancellation must not abandon threads, locks, files or in-flight publication. |

**Total 8: complex because failure/concurrency is 3.** Few functions implement a protocol
whose correctness spans resource lifetimes.

## Approach and invariants

The blocking-worker adapter preserves resource ownership through caller cancellation:

1. `run_blocking` starts `asyncio.to_thread`, propagating context variables, and shields
   the worker task. The thread owns its files, temporary storage, and write resources.
2. On caller cancellation, set the optional cooperative stop event. Cancelling the
   awaiting task cannot terminate the Python thread.
3. Wait for settlement. `finish_worker` gathers the worker with exception capture and
   repeatedly shields the gathering task, tolerating further cancellation while the
   worker still owns its resources.
4. Once the worker finishes, re-raise the caller's cancellation. The enclosing owner may
   now release resources; a later worker error does not replace the cancelled outcome.

`cancellable` checks its stop event before starting each blocking read and after that read
returns. The second check prevents delivery of bytes that arrived after cancellation.
A thread already blocked in a library read must still finish that read; no unsafe thread
termination is attempted.

For the monitor, `Owner.run` acquires an asynchronous lock, refuses admission after stop,
and retains ownership while an independently shielded operation settles. Cancellation
while waiting admits no work. Cancellation after admission can still let consumed evidence
publish while the monitor is mounted, because otherwise the reader cursor could advance
without that evidence reaching the visible state.

![Shutdown sets the publication barrier before waiting](assets/monitor-shutdown.svg)

*Shutdown first closes admission/publication, then waits for the admitted operation, then
closes descriptors. The worker can finish after stop but cannot publish a new UI result.*

Unmount sets the owner stop flag and the health reader's cooperative stop event. The app's
post-await guards prevent new state, notifications, report checkpoints or scroll-state
publication after stop. `Owner.close` asynchronously waits for the same lock, calls reader
cleanup in a thread, and marks closed only after success. Repeated/concurrent close requests
therefore close descriptors once; failed cleanup can be retried without reopening admission.
An already-started Markdown rendering call may finish, but its completion cannot advance
the app's rendered-report checkpoint after shutdown.

## Worked examples and boundaries

A refresh is waiting on the shared log lock because a writer is rotating. The caller
cancels twice, then the app unmounts. Closing the reader immediately would invalidate a
stream the blocked thread still owns. Instead shutdown blocks admission and publication,
signals cooperative stop, waits asynchronously for the writer to release its lock and the
worker to finish, then closes descriptors. The late read does not publish.

If only the caller cancels while the app remains mounted, the already-admitted operation
can finish publishing the evidence it consumed. A different operation cannot take a stale
snapshot in the middle because ownership includes publication. Serializing just the I/O
call would allow two operations to overwrite one another's evidence after their awaits.

A cleanup exception leaves `closed` unset, permitting a later close retry. Stop remains
set, so that retry does not accidentally admit new work. A worker that never returns also
prevents resource retirement; safety is favored over falsely reporting completed cleanup.

## Costs and limitations

The generic adapter uses one worker task and one gathering task, with constant protocol
memory beyond the work itself. Monitor ownership serializes admitted work, so latency can
include all preceding work and file-lock waits. Cancellation settlement is unbounded if
a dependency hangs. There is no OS lock-fairness, hard thread-kill or deadline guarantee.
Workers must retain their resources and cooperate where stop checks are supported.

Pure UI presentation helpers do not need a separate formal lifecycle model; any helper
that reads shared evidence or publishes after an await must enter the owner and check the
stop barrier. Direct calls to UI-only handlers after teardown and Textual internals are
outside the contract. File consistency remains the [log reader](log-retention.md) contract.

## Implementation and verification

Owners: [concurrency.py](../../src/peri_scribe/concurrency.py),
[monitor/tasks.py](../../src/peri_scribe/monitor/tasks.py), and
[monitor/app.py](../../src/peri_scribe/monitor/app.py), especially `refresh_owned`,
`load_older_owned`, `open_evidence_owned`, `render_report_owned` and unmount.
Ordinary [owner tests](../../tests/tests/standard/peri_scribe/monitor/test_tasks.py) and
[app task tests](../../tests/tests/standard/peri_scribe/monitor/test_app_tasks.py) exercise
repeat cancellation, worker failure, blocked locks, cleanup retry and late completion.

The [ingestion protocol inventory](../../tests/formal/tla/ingestion.md) maps generic
worker lifetime to its resource-owning consumers. The
[monitor task inventory](../../tests/formal/tla/monitor_tasks.md) describes the bounded
MonitorTasks safety/liveness graphs and exact progress assumptions.
[Worker lifetime conformance](../../tests/formal/conformance/test_worker_lifetime.py)
and [monitor task conformance](../../tests/formal/conformance/test_monitor_tasks.py)
check concrete schedules against continuous TLC execution paths, including an actual
blocked file lock. The deliberate publication-after-unmount defect check establishes that
the bridge rejects removal of the stop guard. Finite conformance is not a proof of every
possible Python scheduler or library implementation.
