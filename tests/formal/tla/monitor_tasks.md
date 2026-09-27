# Monitor task ownership

`MonitorTasks.tla` checks the lifetime shared by live refresh, archive loading,
selected-evidence reads, report reads/rendering, status expiration, and unmount.
The design was checked before adding the production owner.

## Contract and implementation

The owner admits one operation at a time and holds ownership from its initial snapshot
through its worker completion and publication. Cancelling an admitted caller waits for
that operation to settle before releasing ownership. While the monitor remains mounted,
already-consumed log evidence can therefore finish publishing even if its caller cancels.
A caller cancelled while waiting for admission starts no work.

Unmount stops admission and publication immediately, signals the history reader's
cooperative stop event, waits asynchronously for admitted operations, and only then closes
both readers. Repeated cancellation of shutdown cannot abandon that cleanup. Concurrent
or repeated shutdown closes descriptors once; failed cleanup can be retried without
reopening admission. These guarantees are independent of Textual's message queue.

| Model action or property | Production owner |
| --- | --- |
| Admission, exclusive ownership, cancellation, retirement | `monitor/tasks.py`: `Owner.run`, `settle` |
| Stop, wait, descriptor retirement | `Owner.close`, `Owner.finish`; `monitor/app.py`: `MonitorApp.on_unmount`, `close_readers` |
| Snapshot through publication | `refresh_owned`, `load_older_owned`, `open_evidence_owned`, `refresh_clock_owned`, `render_report_owned` |
| No late state or notification publication | `presentation_available`, evidence error handling, report completion guard |
| Shared reader lock remains owned while waiting | `log_reading.read_lock`, called by the owned followers and history reader |

Safety includes exclusive ownership, descriptor retention while an operation is active,
publication from the current snapshot, preservation of the modeled evidence, and no
publication after stop. Workers may fail before publication. Failure relinquishes
ownership without fabricating a successful result.

`MonitorTasks.cfg` explores **12,828 states**, with three operations, up to two cancellation
deliveries per operation, success and failure, arbitrary stop timing, and an initially
held or available writer lock. `MonitorTasksLiveness.cfg` explores **1,188 states**, with
two operations, and checks eventual descriptor retirement after stop. Progress requires
the writer to release its lock, enabled reads and rendering to finish, and runnable
cleanup to be scheduled. No deadline or progress is promised for a permanently blocked
filesystem, a writer that never allows shared acquisition, or a renderer that never
finishes.

## Executable connection

`helpers/monitor_tasks.py` exports TLC's actual initial states and directed transition
graph. It retains compatible full abstract states across every concrete observation;
it does not accept independently reachable states in an arbitrary order. Read phases,
worker failure, writer release, and cancellation counters are internal transitions;
only unchanged projections may be skipped. Acquisition, publication, stop, operation
retirement, and descriptor retirement remain separate observable steps.

`conformance/test_monitor_tasks.py` checks:

- **96 schedules** of the actual production owner: six admission orders, zero/one/two/five
  repeated cancellation requests, shutdown during work or afterward, and worker success
  or failure. Five requests exercise saturation beyond the finite cancellation bound.
- **Four mounted monitor executions** using the public archive and refresh methods,
  actual compressed archives and live logs, a suspended archive projection, cancellation,
  and unmount. State observations come from the actual `MonitorApp.state`.
- **One actual blocked file-lock execution**: an exclusive writer holds `.rotation.lock`,
  a follower waits for its shared lock, and both refresh and shutdown receive repeated
  cancellation. The preexisting open streams remain usable until that worker exits;
  cleanup then closes them without publishing the late read.
- An impossible early-close trace and a reordered trace whose individual observations
  are reachable, demonstrating why a continuous path is required.

The `monitor-publication-after-unmount` defect check removes the production shutdown
publication barrier. The unchanged mounted-monitor test passes against pristine source
and rejects the mutation with `no compatible TLC execution`.

Ordinary regressions cover the same public operation races and real lock wait, selected
evidence success/error arriving during shutdown, late Markdown completion, cancellation
before and after admission, worker failure, repeated shutdown, and cleanup retry.

## Boundaries

Evidence tokens represent the distinct contributions retained during one bounded overlap
window. The model does not claim that the monitor retains every historical event forever;
retention and chronological interpretation belong to the existing monitor models.
Selected evidence and report payload semantics also remain with their existing owners.
Owner conformance exercises these operation classes through a shared lifecycle; mounted
graph replay specifically covers archive, live refresh, and blocked-lock shutdown.

Publication means initiating a new state, notification, or presentation update. An
already-started asynchronous Markdown update may finish during shutdown; its owner is
retained until it finishes, and its late completion cannot publish the rendered-report
checkpoint or scroll state. Textual's rendering internals and arbitrary direct calls to
UI-only handlers after teardown are outside this protocol.

Reader helpers used by the app must enter through this owner. The model assumes the same
cooperating file-lock and complete-record contracts as `LogReaders`; it does not establish
operating-system lock fairness, filesystem durability, or correct terminal rendering.
