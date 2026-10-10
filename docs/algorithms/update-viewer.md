# Update snapshots and browser reconciliation

The update viewer combines retained acreage history with a live browser presentation.
Server generation preserves each chronological acreage predecessor; browser refresh
preserves controls and row identity while records age into different time groups.

## Contract and assessment

Inputs are validated retained log records, current history ownership, fire summaries,
and generation time. The server writes a versioned JSON snapshot and a packaged HTML
viewer. The browser accepts validated snapshots and ages their entries using its clock.

| Dimension | Score | Reason |
| --- | --- | --- |
| History and state | 3 | Current ownership projects immutable historical buckets before comparison. |
| Rule interaction | 2 | Snapshot validity, connectivity, eligibility, and UI state are independent. |
| Mathematical reasoning | 1 | Stable sorting, grouping, and layout transforms are established operations. |
| Scale and representation | 2 | Record-signature queues preserve repeated rows while reusing DOM elements. |
| Failure and concurrency | 3 | Overlapping refreshes, timeouts, and partial outcomes retain the displayed state. |

Total **11: complex**. Durable update identity and journaling are explained in
[history ownership](history-ownership.md) and [update journal](update-journal.md).

## Compare before filtering

The previous acreage can come from outside the visible 48-hour window. Filtering first
would manufacture an initial increase.

Read retained logs using their archive-prefix/plain-tail ordering and stable-sort by
timestamp. Project each original log bucket to its current owner. For every nonfuture
entry, remember the prior entry for that owner, update the remembered value, and only
then decide whether the entry has a nonzero change inside the window. No prior entry
means initial acreage from zero; separate inherited records are never summed.

After ownership projection, compare one owner's retained observations in order:

1. **Hour −50: 100 acres.** This entry is outside the visible window but supplies the
   baseline for the next observation.
2. **Hour −2: 130 acres.** Display a +30-acre increase, not an initial +130 acres.
3. **Hour −1: 120 acres.** Display a −10-acre correction. Compare history rather than
   summing its observations.

Equal timestamps retain input occurrence order. Even a zero-change entry can become
the next entry's predecessor. Missing months simply supply no evidence.

Previews and locations are associated through current ownership and source identities.
Repeated updates share one current fire preview. Display refresh does not rewrite
durable log records or create mapping events. Unmatched geometry retains logged text.

## Refresh and response clocks

The browser makes an immediate GET and polls every 30 seconds, with a 15-second request
timeout and a guard against overlapping loads. A displayed ETag is sent unchanged.
A 304 with an existing validator preserves the display. A full successful response is
validated and rendered before saving its ETag. Invalid data, failed requests, and
unexpected 304 responses preserve the previous snapshot.

Separately, every HTTP response restarts a 60-second watchdog. A 500 response establishes
connectivity even though it cannot replace data; a rejected or timed-out request does
not. Expiry shows the last response time, or page-open time before the first response.
Browser timer delays can postpone the notice; this is not a network availability proof.

## Row reconciliation and animation

Before replacement, group existing row objects by a signature of identity, timestamp,
name, location, and acreage values. Consume one retained object per matching new record.
Update its preview separately; new signatures create new rows. Preserve name filter,
per-group sorting, and collapse controls. Group counts count distinct current owners,
while the rows retain every update.

For example, old rows with signatures `[X, X, Y]` form queues `X: [X1, X2]` and
`Y: [Y1]`. A replacement snapshot with signatures `[X, X, Z]` consumes those queues:

1. The first X reuses row X1.
2. The second X reuses row X2.
3. Z creates a new row.
4. Y has no successor, so remove row Y1.

A set keyed by signature would collapse the second legitimate X occurrence. Queues
preserve both occurrences while the filter and group controls remain unchanged.

Time ranges are half-open: 0–60 minutes, 1–4 hours, 4–12 hours, 12–24 hours, and 24–48
hours. Browser timers move entries, update minute labels, end recent highlights, and
remove expired rows independently of polling. Layout measurement before and after
reconciliation drives movement. A move involving one collapsed group uses its header;
two collapsed groups skip movement. Reduced-motion preference cancels movement.
Heading/time/location fitting uses actual measured widths so names remain complete.

A newly loaded qualifying recent row in an expanded, matching group starts the
30-second favicon notification. Changing the filter or expanding a group alone does
not. Subsequent qualifying additions restart the notification interval.

## Costs, limits, and verification

Server sorting costs `O(N log N)` for retained entries and holds `O(N)` records. Browser
replacement uses signature maps and queues; repeated array shifts can be quadratic
within a large duplicate group. Rendering sorts matching entries and performs DOM
measurement, so its cost includes browser layout. Current browser time controls aging;
clock skew and throttled timers can affect presentation.

- [Snapshot builder](../../src/peri_scribe/updates.py) and
  [browser implementation](../../src/peri_scribe/updates.html).
- [Projected snapshots](../../tests/formal/lean/projected_snapshots.md),
  [BrowserRefresh](../../tests/formal/tla/BrowserRefresh.tla), and
  [BrowserResponsiveness](../../tests/formal/tla/BrowserResponsiveness.tla).
- [Chronology conformance](../../tests/formal/conformance/test_update_log_chronology.py),
  [refresh conformance](../../tests/formal/conformance/test_browser_refresh.py), and
  [responsiveness conformance](../../tests/formal/conformance/test_browser_responsiveness.py).
- The [browser suite](../../tests/tests/browser/peri_scribe/) checks actual layout,
  animation, and resizing; [testing guidance](../testing.md#browser-viewer-tests)
  distinguishes those observations from finite protocol checks.
