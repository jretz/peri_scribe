# Observer contracts

These checks cover the browser and terminal monitor. They make no writes to production
data. The conformance suite exports TLC's complete state relations on every run; no saved
handwritten expected-state fixtures stand in for the specifications.

## Browser refresh

`tla/BrowserRefresh.tla` covers `loadUpdates` and `sameVersion` in
`src/peri_scribe/updates.html`. Four metadata classes distinguish absent validators,
colliding weak validators, changed strong validators, and an unchanged strong validator.
The finite model explores fresh and expired metadata, successful responses, unsupported
HEAD, failed HEAD, failed GET, invalid content, and overlapping polling attempts.

The invariants establish at most one refresh, agreement between committed validators and
displayed data, preservation of the snapshot and download age after failure, and a forced
download after weak metadata expires. The liveness configuration checks a healthy retry
eventually displays the stable server generation, assuming requests and polling progress
and the weak-metadata deadline has elapsed. The first round may fail; the second round is
healthy. This is a bounded recovery claim, not a guarantee against an indefinitely failing
server. Strong validators are assumed to identify content correctly.

Both configurations explore 451 states from 40 initial combinations. Conformance replays
all 80 completed first-round outcomes, with and without overlapping polling, against the
shipped inline JavaScript through the existing browser double. Every weak case runs with
both weak ETag and Last-Modified/Content-Length metadata. An immediate healthy poll after
an expired weak-metadata failure must download again, checking that failed downloads did
not renew the cached age. The healthy retry must display the server generation. Real DOM
rendering, browser implementation of request timeouts, concurrent changes during one HTTP
response, and server correctness are outside this model.

`tla/BrowserResponsiveness.tla` separately covers `createResponseMonitor` and the
response notification in `requestSnapshot`. Its 3,906 states enumerate all histories of
up to five response, rejection, elapsed-interval, delayed-interval, and timer-dispatch
events. One time unit means the viewer's 30-second polling interval; the watchdog becomes
due after two units without a response. Both HEAD and GET replies count as responses,
including error statuses. Snapshot validity remains the separate refresh contract.
Response instants in this model lie on that interval grid; ordinary timer tests cover
millisecond boundaries.

Properties require that only received responses renew the recorded time and deadline,
that the warning never appears early, that the latest response immediately clears it,
and that dispatched timers expose overdue silence. A warning remains until another
response arrives. Before the first response, the initial deadline uses page-open time
and the warning explicitly identifies that time. Delayed callbacks represent suspended
tabs: silence is shown when the browser next dispatches the due callback, without an
exact wall-clock scheduling guarantee. Monotonic timer progress is an environmental
assumption; date formatting and wall-clock adjustments do not determine the deadline.

Conformance replays every bounded history against the shipped watchdog and request
wrapper, once with successful GET replies and once with HEAD HTTP 503 replies. It checks
the displayed warning and last-response timestamp, including initial silence, rejection,
recovery, and delayed dispatch. The model also covers an indefinitely pending request
through time-only transitions. Native browser timeout implementation, unbounded
histories, and the visual prominence of the warning are outside this finite guarantee.

## Log cursors and context

`tla/MonitorReader.tla` covers `storage.Follower.poll` and `storage.read_cursor`. Its 4,299
states enumerate every legal trace through seven steps, up to three distinct records,
one rotation, complete writes, partial writes, polls, and detectable truncation. Properties
require exactly-once delivery of completed records and complete delivery after polling.
Conformance replays every trace using actual temporary files and retained file handles.

The initial file is already discovered. Rotation retains its handle and the old writer
has finished writing before that handle is drained and retired. A truncation preserves
already delivered identities, discards only an incomplete suffix, and is polled before the
replacement grows. These are explicit environment assumptions: size-based truncation
detection cannot identify a truncate-and-regrow that passes the saved byte offset between
polls. This model also does not promise recovery of unread bytes destroyed by truncation,
or appended bytes written to an old inode after the follower has retired it. Archive
discovery is exercised separately by the context checks.

`tla/MonitorContext.tla` covers `history.recent_records`, `context_records`, and
`Reader.restore_context`. Its 537 states cover every ordered history of up to two records
drawn from four times, two runs, and structural/ordinary classifications. Restored context
must precede the recent boundary, belong to a selected run, and include all eligible
records for each checked run. Recent and restored identities must be disjoint. Fair
restoration eventually checks every selected run.

Conformance compares every partial partition with the production filters. For all 273
input histories it also runs the complete reader with both phase context and command-start
context, checks restored structural context and unique identities, compresses the month,
and verifies a second catch-up does not replay records. Command-start cases include an
older unreadable archive to detect scanning past the recovered start. Ordinary records
deliberately compacted by the reader need not remain as visible events. The scope excludes
recovery from missing/corrupt archives, cancellation during a scan, undated
records, startup files already outside discovery limits, and recovery of a start record
that is absent from the available logs.

[Reader composition](reader_rotation.md) extends these checks across archive and plain
components, committed rotation receipts, and successive polls. Changed archives trigger
a bounded recent-history replay with context restoration, covering a late tail that is
appended and compressed entirely between monitor observations.

## Monitor projection and compaction

`tla/MonitorProjection.tla` specifies interval insertion/merging and cached coverage over
up to two observations. It explores all orderings, duplicate timestamps, success/failure
statuses, four evidence times, seven observation times in either order, and complete,
errored, or still-loading collection metadata. The resulting graph has 32,193 states.
Compacted intervals must represent exactly the union of original inclusive windows and
remain disjoint. Reuse between coverage boundaries must equal a fresh projection;
collection diagnostics cannot appear healthy; only a successful, nonfuture completion
may acknowledge a source check.

Conformance compares all 10,731 completed transitions against real `history.append`,
`history.extend_coverage`, `projection.refresh`, and `status.project`. One abstract time
unit maps to 24 hours, making the modeled window exactly the application's 48-hour
window. It checks the model's merged intervals, coverage health, and last successful
source timestamp. Every full cached view must also equal fresh evaluation, including
diagnostic metadata changes. Additional replays over the same 73 histories exercise
microseconds before/at/after minute, hour, six-hour freshness, day, and 48-hour expiry
boundaries, backwards clocks, new evidence, and artifact-error/pending-work changes.

The full-view comparison is implementation-conformance evidence; the TLA+ checked scope
remains the specified coverage, compaction, and success-selection contract. Detailed
exception grouping, every display string, datetime overflow, the correctness of all
source timestamps, and arbitrary histories are not proved by this finite model.
