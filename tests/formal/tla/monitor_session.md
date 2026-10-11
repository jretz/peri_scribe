# Observable monitor session

`MonitorSession.tla` checks versioned immutable publication, bounded subscription
mailboxes, request priority and promotion, and session stop/close boundaries. The design
was checked before implementing `monitor.session` and rechecked before adding promotion.
The [algorithm note](../../../docs/algorithms/monitor-sessions.md) records the contract,
costs, assumptions, worked examples, and composition with reader ownership.

`MonitorSession.cfg` explores **19,166 states** with three distinct requests, one initial
urgent request, two independently delayed subscribers, request success/failure, queued
cancellation, queued promotion, subscription/disconnection, and arbitrary stop timing.
Every request can finish once; reconnecting a subscriber obtains the current version.

| Model transition or guarantee | Implementation |
| --- | --- |
| Submit, priority admission, queued cancellation | `MonitorSession.request`, `dispatch`, `Pending` |
| Promote without interrupting ownership | `MonitorSession.promote` |
| Complete, monotonic version, no publication after stop | `execute`, `publish` |
| Subscribe, coalesce, receive, disconnect | `subscribe`, `offer`, `Subscription` |
| Stop admission before retirement | `MonitorSession.close`, `finish`, `release` |
| Retain blocking workers through caller cancellation | Existing `tasks.Owner` and `MonitorTasks` contract |

The subscription conformance adapter projects actual versions, connection membership,
and returned snapshot versions onto TLC's complete directed graph. Request admission and
payload calculations are internal in this projection. A deliberately obsolete-delivery
trace demonstrates that reachable individual states do not suffice; observations must
belong to one continuous model execution. Priority ordering and identity-based promotion
have ordinary behavioral tests. The separate `MonitorTasks` adapter observes admission,
actual evidence publication, stop, and resource retirement through real domain requests.

Snapshot payload meaning is owned by the existing reconstruction and health contracts.
The session graph does not prove Python thread behavior, filesystem fairness, record
retention, or terminal output. It assumes one event loop, immutable shared snapshots, and
one consumer per subscription. Strict priorities do not guarantee starvation freedom.
Versions are unbounded Python integers; the finite model increments at most once for
each of its three requests. Existing owner liveness remains conditional on blocking
workers and cooperating writer locks eventually completing.
