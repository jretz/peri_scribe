# Observable monitor sessions

## Contract and context

`monitor.session.MonitorSession` owns diagnostic readers, recent health history,
artifact metadata, the report reader, filesystem notifications, and the reconciliation
clock. Consumers request domain data and observe immutable versioned snapshots. The
session imports no terminal framework and makes no decisions about when a consumer
should prepare or present its data.

Startup obtains complete recent health before starting ongoing observation. Diagnostic
records and the report have independent requests and are subsequently reconciled once
requested. A selected command's complete evidence is returned separately from the
bounded diagnostic stream. Loading an older month prepends archive records before the
current stream and preserves the existing reconstruction and retention contracts.

Input records, reader coherence, chronological assumptions, and collection diagnostics
belong to [monitor evidence](monitor-evidence.md). The underlying resource owner retains
the [worker lifetime](worker-lifetimes.md) contract. The session never writes observed
application data.

## Complexity assessment

The score is **2/2/0/1/3 = 8**, classified complex because cancellation spans resource
lifetimes. Publication versions and subscriptions depend on prior events (history 2).
Request priority, queued cancellation, notification coalescing, and stopping interact
(rules 2). Mailboxes and a standard priority heap have ordinary representation costs
(scale 1). An admitted request can outlive cancellation while another caller initiates
shutdown (failure and concurrency 3). No additional mathematical derivation is needed.

## Admission and publication

A request joins a priority heap with a strictly increasing submission number. Stronger
priority wins; equal priorities retain submission order. A consumer can promote the
identical queued request object, allowing it to join existing work without creating a
second reader operation. Promotion leaves an admitted request uninterrupted. Queued
cancellation removes the request's eligibility; admitted cancellation waits until the
reader and its publication decision have settled.

One dispatcher enters the existing `tasks.Owner` for each request. The owner covers
the initial snapshot, worker completion, and publication. Every new publication replaces
the whole frozen snapshot and increments its version. A stopped owner rejects that
publication even if the filesystem work succeeded. No consumer callback executes inside
publication: each subscription receives a bounded mailbox entry.

The following relationships explain the retained ownership and independently scheduled
consumers. An admission boundary is the only place priority can change which request
owns the readers.

| Boundary | Required relationship |
| --- | --- |
| Queued request | May be promoted or cancelled; owns no reader. |
| Admitted request | Holds the owner through calculation and publication decision. |
| Published snapshot | Is immutable; every subscriber receives the same object/version. |
| Pending subscription | Contains at most the newest complete version. |
| Consumed subscription | May retain its immutable snapshot while newer ones arrive. |
| Stop | Closes admission and publication before waiting for any worker. |
| Descriptor retirement | Follows completion of every admitted reader operation. |

Mailboxes coalesce versions because these are complete snapshots, not incremental
changes. A consumer that received version 4 and next receives version 8 loses no data
needed to interpret version 8. Consumers that require every individual log event use
the retained evidence within snapshots and its existing retention policy; subscriptions
do not promise an unbounded event journal. Closing a subscription releases its pending
snapshot and wakes its waiter. Closing the session terminates every subscription after
the owned resources settle.

## Worked examples and failure boundaries

Suppose archive ingestion owns the readers, a periodic refresh is waiting, and another
consumer requires the report. Promoting that queued report request places it before
the periodic refresh, while the archive operation finishes with exclusive ownership.
Both published snapshots retain the archive result because each admitted operation
starts from the current committed snapshot.

If shutdown begins while archive ingestion is blocked on a cooperating writer's lock,
the session immediately stops new admission and publication. It signals cooperative
history cancellation and native-watcher shutdown, resolves queued callers with the
final committed snapshot, and waits asynchronously. Repeated cancellation of shutdown
does not close streams used by the worker. Once the writer releases its lock, the
worker finishes, its late candidate snapshot is rejected, and the readers close once.
A cleanup failure can be retried while admission remains stopped.
Observation-task failures are reported after readers, observers, and subscriptions have
settled; cleanup does not discard failed background outcomes.

Native filesystem hints set a dirty flag. The clock consumes a hint before refreshing,
so a hint arriving during that refresh remains pending for the next pass. A monotonic
reconciliation deadline repairs missed notifications. Without dirty input, a clock
request ages and expires health evidence using wall time without advancing file
cursors. Wall-clock reversal is handled by the health projection's own cache contract.

## Costs and limitations

With `q` queued requests and `s` subscriptions, admission costs `O(log q)`, promotion
costs `O(q)`, and publication costs `O(s)`. Retained pending delivery costs `O(s)` snapshot
references; immutable unchanged components remain shared. Reader and reconstruction
costs remain those documented by their domain algorithms. Automatic reconciliation has
only one outstanding sequence; independently submitted requests remain caller-bounded.

An admitted blocking operation is not preemptible. Progress assumes its filesystem and
cooperating writer eventually allow it to finish. Continuous urgent arrivals may delay
lower-priority work; the protocol does not claim starvation freedom. Subscriber delivery
is single-consumer per subscription and all session coordination occurs on one event
loop. The session does not promise hard real-time deadlines or persist snapshot versions
across process restarts.

## Implementation and verification

The owning implementation is [session.py](../../src/peri_scribe/monitor/session.py).
`MonitorSession.tla` was checked before implementing the protocol and again before
adding promotion. Its three-request, two-subscriber configuration explores **19,166
distinct states**, including failures, queued cancellation, promotion, delayed delivery,
coalescing, disconnection, and arbitrary stop timing. It checks exclusive admission,
resource retention, newest pending versions, monotonic delivery, and no publication
after stop. The existing `MonitorTasks` safety and conditional-liveness models own the
blocking-worker and descriptor-retirement guarantees.

`tests/formal/conformance/test_monitor_session.py` compares real subscription executions
with complete paths in TLC's exported graph and rejects obsolete deliveries. The monitor
task conformance suite exercises real archive ingestion, incremental reads, cancellation,
and a retained shared-lock wait through the session. Standard session tests additionally
cover request priority and identity-based promotion, report replacement, selected-run
errors, expiry, native hints, repeated shutdown, and independent subscribers.
