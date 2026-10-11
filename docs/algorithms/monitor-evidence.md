# Monitor evidence, coverage, and cached status

## Contract and context

The monitor projects observed log evidence into command/phase history and health metrics.
It does not infer operating-system process liveness from an unfinished command. Interactive
browsing and compact health history have separate retention policies so trimming verbose
rows cannot hide a recent exception or fabricate healthy coverage. No monitor reader writes
to watched application data.

Inputs are complete structured log records, file/report snapshots, pending-work metadata,
and an aware observation time. Malformed or undated evidence remains diagnostic. Health
uses a 48-hour window, inclusive at its endpoint, while UI age/freshness deadlines can be
much shorter. File following uses binary offsets and inode identities; archive reads use
[coherent log selection](log-retention.md).

## Complexity assessment

| Dimension | Score | Concrete reason |
| --- | --- | --- |
| History and state | 2 | Restoring old command context and following rotation must not replay recent evidence. |
| Rule interaction | 3 | Coverage, failures, successful checks, artifacts and loading/error metadata jointly determine health. |
| Mathematical reasoning | 1 | Interval union and deadline calculation must preserve inclusive boundaries. |
| Scale and representation | 3 | Compact health evidence, bounded display history and streamed archives preserve different views of large logs. |
| Failure and concurrency | 3 | Retained descriptors, partial records and archive replacement interact with asynchronous shutdown. |

**Total 12: complex.** The final dimension's ownership protocol is explained separately
in
[worker lifetimes](worker-lifetimes.md).

## Approach and invariants

Retain a cursor per device/inode, buffer the incomplete last record, and deliver only
newline-completed lines. Drain a rotated old inode before retiring its handle. Detectable
truncation resets the byte offset and incomplete suffix. A poll reads at most 4 MiB per
cursor; requested interactive archives retain their last 10,000 events.

For a live cursor on inode I, a poll that finds complete line a and partial line b delivers
a and keeps b's bytes private. If the next poll on I finds the rest of b and its newline,
it delivers b once.

The health reader discovers recent months, consumes archived prefixes plus live tails,
and watches archive identity (device, inode, size, modification nanoseconds). A changed
already-seen archive resets recent ingestion and rebuilds it: a late tail may have been
appended and compressed entirely between polls. After catch-up, restore structural records
for recent runs whose command start lies before the window, scanning older months until
those starts are found. Context records precede each run's recent cutoff and are tracked
separately to avoid repeated restoration.

For a month represented by one plain file, binary-seek to the greatest missing-run cutoff
and scan backward in 64 KiB blocks. Retain only important dated records strictly before
their own run's cutoff, stopping each run at its command start. Command IDs are unique to
an invocation and its start precedes its other records. Once all selected starts are
found, reverse the selected records and ingest them in their original file order. The
recent/context timestamp partitions stay disjoint, including equal cutoff timestamps.

Publish no tentative backward result until every requested start is present. If any start
is absent from that month, use the streamed forward context pass and continue into older
months. Archived or mixed archive/plain months use that same streamed path, retaining
receipt-based occurrence identity and avoiding backward decompression. Both searches run
under the same shared rotation lock as catch-up; shutdown is checked between reverse
blocks and records. Let B be bytes examined before the last required start, C selected
context bytes, and L the longest record. Backward scanning costs O(B) time and O(C + L +
64 KiB) memory; fragments of a large record are joined once. A missing start can require
one reverse pass plus the linear fallback. No index or persistent cache is written.

Run IDs keep concurrent commands separate. Logging assigns command IDs, records nested
phase instances through context variables, validates catalogue parentage, and measures
duration with a monotonic performance clock. Readers prefer explicit instance segments,
then dotted paths with compatible parent branches, then legacy phase nesting. Phase
reconstruction starts with the recorded plan, marks observed prefixes active, and accepts
completed/failed status only from a finish record. A still-active phase becomes unfinished
when its command ends. Explicit skips outrank inferred absence; unseen descendants of an
omitted branch are hidden together. Missing starts alone never prove successful execution.
Recorded durations are converted to seconds; unusable metadata contributes zero.
Legacy records without IDs get observation-local grouping. Interactive state bounds runs
and event rows; compact health state instead keeps structural messages, exceptions and
each run's last event. Shared immutable strings and encoded phase paths reduce repeated
metadata without sharing mutable decoded containers between callers.

### Batched reconstruction and bounded reuse

The representation changes retain the evidence contract above. Their separate complexity
assessment is **2/2/1/2/0 = 7 (involved)**: phase ancestry depends on record order,
retention and terminal outcomes interact, coverage uses interval union, and immutable
batching avoids repeated reconstruction. They add no external effects or ownership policy.

Decode ordinary JSON in the native decoder, falling back to the standard decoder for
valid syntax outside that decoder's accepted domain. Retained values, integer precision,
and float values remain unchanged. Slot-backed events avoid per-instance dictionaries.
Cache short timestamp parsing (4,096 entries) and short phase encodings (512 entries),
sharing only immutable results. Long inputs bypass these caches. Raw phase metadata is
decoded into independent containers on access. Other nested JSON fields also use
immutable serialized values, and each access materializes an independent container.
Copying the record's top-level mapping and isolating nested values prevents either a
caller or a subscriber from mutating a published event through a retained input alias.

Within a batch, collect each command's events and phase stack in local mutable buffers,
then freeze each changed command once. Preserve event order, sequence numbers, legacy
command grouping, ancestry, outcomes, and bounded-retention semantics. A command's latest
timestamp is computed once per immutable command version. Compaction recognizes already
normalized command objects with a bounded weak-reference identity table (4,096 entries),
so unchanged commands do not repeatedly traverse their event histories. Identity reuse
must also match the live weak reference; an integer object ID alone is insufficient.
Externally constructed histories still take the ordinary normalization path.

For example, a new batch extends command B but leaves A unchanged. Reuse A's compact
immutable events, compact B's new version, and extend coverage with timestamps from
**every** new record before discarding ordinary verbose events. Retaining only important
timestamps would create false coverage gaps. Coverage merging constructs final interval
objects after scalar endpoints are merged, avoiding one allocation per covered record.

For a batch of B records and retained R commands, ingestion traverses new records and
changed command evidence rather than every old event per batch. Retention still sorts
R commands, costing O(R log R), and final state construction remains O(R). Auxiliary
buffers are proportional to the batch and changed command evidence; caches have fixed
entry limits and do not retain complete old histories. Pure reconstruction remains
checked against the Lean oracle; focused tests cover immutable-container independence,
cache eviction, mixed explicit/legacy identities, and phase-stack carry-over across
batches. The caches alter representation and work reuse, not domain policy.

For every observed timestamp t, contribute coverage interval [t, t + 48 hours]. Sort and
merge overlapping inclusive intervals. Use all observed records for coverage, including
verbose records subsequently discarded. Future intervals remain separate until their
start; an event in the future cannot make today healthy. Collection errors, undated data
and still-loading state remain explicit diagnostics.

![Inclusive coverage union and projection deadlines](assets/monitor-coverage.svg)

*Copies of the three input intervals descend onto a common time axis. The overlapping
bands merge into [0,72], while [100,148] stays separate. The moving “now” marker then
crosses the inclusive endpoint at hour 72 into the uncovered gap: future evidence cannot
cover hour 80. Vertical motion aligns intervals without changing their timestamps;
horizontal motion advances projection time over a fixed evidence union. Three static
comparisons retain the alignment, merge, and gap with reduced motion or no animation.
Coverage expires one microsecond after hour 72; the animation does not depict time at
microsecond resolution.*

The status projection caches evidence facts separately from presentation. Reuse the
whole snapshot only with unchanged immutable state, equal metadata/files, forward time,
and no reached deadline. Reuse evidence tables until a future observation becomes current
or an exception leaves its inclusive window. Recompute health at the strict six-hour
freshness boundary and coverage start/expiry. Presentation separately updates age text at
age-unit boundaries. Backward clocks force
re-evaluation. Successful nonfuture completion can acknowledge a source check; a failed
attempt cannot be treated as a successful refresh.

### Expanding the planned phase tree

[phases.planned_paths](../../src/peri_scribe/phases.py) performs a depth-first preorder
expansion of the shared, finite, acyclic `CHILDREN` catalogue. Each output is a complete
tuple of phase/branch segments. Emit the parent before recursively expanding its children;
attach a feed/source name only at its owning collection segment. Descendants inherit that
segment, so identical `query-features` phases under two feeds remain distinct instances.
The configured feed/source names come from
[catalog.configured_phase_branches](../../src/peri_scribe/sources/catalog.py), and a
recorded run plan preserves those names even if current configuration later changes.

Gated and ungated plans differ at fetch. The gate needs evacuation and city checks before
it decides whether expensive downstream collection is worthwhile:

| Plan | Direct fetch children and external-source placement |
| --- | --- |
| Ungated | Administrative boundaries, fire collection, source index, external refresh. Every configured external source appears under external refresh. |
| Gated | Fire collection, evacuation check, city check, publication gate, deferred fetch. Boundary preparation, source index and external refresh move beneath deferred fetch. Evacuations/cities appear only beneath their dedicated checks and are excluded from deferred external refresh. |

For feeds A/B and external sources Buildings/Evacuations/Cities, both plans have separate
`collect-feed[A]/query-features` and `collect-feed[B]/query-features` paths. The gated plan
places `collect-external-source[Cities]` beneath `city-check`, and only Buildings remains
under deferred external refresh. Expanding every external source in both places would
show duplicate city work that the coordinator never performs. Omitting the branch segment
would instead merge independent feed progress into one phase.

An empty configured feed/source list normally emits an unnamed collection placeholder;
the dedicated evacuation/city checks use their supplied names, even when empty. Gated
filtering may remove an unnamed external placeholder when its name equals an empty
dedicated name. The catalogue is trusted acyclic data; the recursion does not detect a
new catalogue cycle. If P expanded paths have maximum depth D, creating/copying paths and
recursively collecting them costs O(PD) time and output storage, with O(D) call depth.
The current catalogue has fixed shallow depth. The catalogue is a plan of possible work;
recorded selection/skip evidence separately explains which branches were executed.

[Phase tests](../../tests/tests/standard/peri_scribe/test_phases.py),
[catalogue tests](../../tests/tests/standard/peri_scribe/sources/test_catalog.py), and
[logging-phase tests](../../tests/tests/standard/peri_scribe/test_logging_phases.py)
check branch expansion, gated placement, recorded configuration and execution parentage.
The existing Lean reconstruction connection checks planned visibility and omission
composition; correctness of the catalogue itself is an ordinary-test assumption.

### Status evidence precedence

Status first orders observations by timestamp and event sequence, then excludes future
evidence from timed metrics. The following rules explain why recent activity is not
sufficient evidence of healthy output:

| Metric | Evidence and decision |
| --- | --- |
| Output freshness | Prefer last successful producing-phase completion, falling back to file modification time. Missing output is bad; other read errors or future/unknown time warn. Age under five hours is good; five through six hours warns; strictly over six hours is bad. |
| Report alignment | A report older than the latest KMZ is in progress while compatible work is active; otherwise warn. Preserve any worse freshness severity. |
| Activity | Ignore lock-skipped invocations when choosing the latest working run. An open command is observed activity, not proof of a live process. |
| Source check | Only successful nonfuture fetch/fire-collection completion renews the check; age over six hours warns. |
| Publication | Read errors and pending requirements take precedence over the latest gate decision; active work explains pending stages as in progress. |
| Failure recovery | A later successful completion of the failed phase or a containing phase establishes recovery; unrelated success does not. |
| Coverage | Loading, read errors, absent current coverage and undated records prevent an unqualified healthy-history claim. |

Exception grouping uses the final exception line, normalizing UUIDs, timestamps and hex
addresses while preserving meaningful error codes. A matching propagated exception on a
containing phase/command finish in the same run is suppressed; distinct attempts still
count. Group by normalized description and phase scope, count occurrences and distinct
runs, and retain the worst unresolved outcome. The overview selects the most severe
problems across output, activity, source, publication, failure, coverage and exceptions;
"no exceptions" cannot override unavailable history.

## Worked examples and boundaries

At hour 0 a verbose event is observed and later trimmed; it still contributes coverage
through hour 48. Another event at 24 extends the merged end to 72. A future event at 100
must not fill the gap (72,100). Keeping only the largest timestamp would lose the evidence
that distinguishes current coverage from future data.

A long command starts 60 hours ago and emits an exception now. Recent-window loading finds
the exception, then restores the earlier command/phase structure without replaying recent
records. It can label the command and phase even though ordinary old chatter is omitted.
An exception at `fetch/feed A/read` followed by successful `fetch/feed B` has no matching
recovery; successful enclosing `fetch` does supply recovery evidence. Repeated propagation
of that same exception through the enclosing failed-phase and command-finish records
must not count as three independent attempts. At exactly 48 hours an exception is still
in the window; its table deadline is one
microsecond later. Refreshing only on file changes would leave stale health visible.

A partial UTF-8 JSON record split between polls remains buffered. If its file is replaced,
its old open inode is drained before retirement. Size-based truncation detection cannot
recognize a truncate-and-regrow beyond the old offset between polls; this is an explicit
source assumption, not exactly-once delivery for arbitrary file mutation.

## Costs and limitations

For N incoming records and K existing coverage intervals, coverage insertion sorts
O((N + K) log(N + K)) intervals; compact retention sorts runs by evidence time. Cached
snapshot reuse avoids these status calculations between relevant boundaries, but new
evidence can require sorting/grouping all retained events. Exception recovery currently
scans later observations
for each origin, so E retained exceptions among N observations can cost O(EN), with
O(N + groups) evidence/summary memory. File polling is bounded per
cursor, while startup, changed-archive replay and context recovery can scan substantial
history. Archive decode is streaming; an individual oversized record and retained
exceptions/structural events can still be large. Interactive row limits do not bound
all progress evidence or all 48-hour exception history.

Stable report reads compare metadata before/after reading one open file; a changed file
retains the prior snapshot. Directory notifications are hints, with periodic reconciliation
and retry after watcher failure. Missing/corrupt archives, arbitrary timestamp truth,
late writes to already-retired inodes, OS scheduling and terminal rendering are outside
complete-history guarantees. UI formatting, striping and screenshot wrappers add no new
health policy and rely on their ordinary tests.

## Implementation and verification

Core owners: [history.py](../../src/peri_scribe/monitor/history.py),
[storage.py](../../src/peri_scribe/monitor/storage.py),
[model.py](../../src/peri_scribe/monitor/model.py),
[events.py](../../src/peri_scribe/monitor/events.py),
[status.py](../../src/peri_scribe/monitor/status.py),
[projection.py](../../src/peri_scribe/monitor/projection.py),
[sharing.py](../../src/peri_scribe/monitor/sharing.py), and
[changes.py](../../src/peri_scribe/monitor/changes.py).
Ordinary [history](../../tests/tests/standard/peri_scribe/monitor/test_history.py),
[rotation](../../tests/tests/standard/peri_scribe/monitor/test_history_rotation.py),
[projection](../../tests/tests/standard/peri_scribe/monitor/test_projection.py),
[status](../../tests/tests/standard/peri_scribe/monitor/test_status.py), and
[storage](../../tests/tests/standard/peri_scribe/monitor/test_storage.py) tests cover concrete
behavior; [model](../../tests/tests/standard/peri_scribe/monitor/test_model.py) and
[sharing](../../tests/tests/standard/peri_scribe/monitor/test_sharing.py) cover reconstruction
and representation independence.

The [observer inventory](../../tests/formal/observers.md) maps MonitorReader,
MonitorContext and MonitorProjection with their bounds and assumptions.
[Reader composition](../../tests/formal/reader_rotation.md) covers archived-prefix/live-tail
coordination. [Projection conformance](../../tests/formal/conformance/test_monitor_projection.py),
[context conformance](../../tests/formal/conformance/test_monitor_context.py), and
[reader conformance](../../tests/formal/conformance/test_monitor_reader.py) exercise actual
implementations. The finite models cover selected health/retention properties, not every
display string, exception grouping, unbounded history or UI-library behavior.

[Lean reconstruction inventory](../../tests/formal/lean/centroids_monitor.md#monitor-run-and-phase-reconstruction)
and [reconstruction conformance](../../tests/formal/conformance/test_monitor_reconstruction.py)
cover isolation across run interleavings, omission precedence and structural retention.
Their batch/stream equivalence premise is unbounded processing; bounded run eviction
intentionally forgets older in-memory contexts.
