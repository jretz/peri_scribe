# Update snapshots and browser reconciliation

The update viewer shows how each fire's mapped acreage changed. The snapshot builder
compares each observation with its chronological predecessor, including one that is too
old to display. The browser then refreshes that history while preserving controls and
row identity as records move into older time groups.

## Contract and assessment

Inputs are validated retained log records, current history ownership, fire summaries,
and generation time. The pipeline writes a versioned JSON snapshot and a packaged HTML
viewer. The browser accepts validated snapshots and ages their entries using its clock.

| Dimension | Score | Reason |
| --- | --- | --- |
| History and state | 3 | Current ownership projects immutable historical buckets before comparison. Older rows can reconstruct an image from the retained mapping at their cutoff. |
| Rule interaction | 2 | Saved previews take precedence over reconstruction, which requires agreement between mapping dates and logged acres. Snapshot validity, connectivity, eligibility, and UI state are independent. |
| Mathematical reasoning | 2 | Growth rings must be recomputed for the dated prefix because later geometries can change the earlier rings. |
| Scale and representation | 2 | Record-signature queues preserve repeated rows while reusing DOM elements. |
| Failure and concurrency | 3 | Overlapping refreshes, timeouts, and partial outcomes retain the displayed state. |

Total **12 (complex)**. Durable update identity and journaling are explained in
[history ownership](history-ownership.md) and [update journal](update-journal.md).

## Compare before filtering

The previous acreage can come from outside the visible 48-hour window. Filtering first
would make the first visible observation look like growth from zero.

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

Current ownership and source identities associate rows with current fires for location
descriptions. Rows without a matched fire or usable location evidence retain their
logged locations.

## Previews at publication

Each new record stores the image rendered from the same prepared fire summary that
supplies its acreage and KMZ geometry. The viewer copies that image from the record
even after a later correction changes its fire's shape or ownership. An explicit null
means no preview was available from that publication.

When a row has no saved preview field, use the fire associated through current
ownership and source identities. Take the dated perimeter observations at or before
the row's publication time. Render that prefix only when exactly one perimeter has the
latest eligible timestamp, has nonempty geometry, and matches the logged value in
measured acres. The acreage check helps reject histories that have since changed.
A missing fire, an empty prefix, a tie at the latest timestamp, empty latest geometry,
or an acreage mismatch leaves the row without an image.

Recompute the [corrected growth rings](corrected-growth-rings.md) from the dated
perimeters in observation order. The same differential calculation used for the KMZ
works backward through the prefix, so only corrections through the row's cutoff can
trim its earlier rings. Then use the usual [preview renderer](preview-orientation.md)
to color the recomputed rings and draw the outlines.

For example, a 100-acre observation at 09:00 and a 130-acre observation at 11:00
can supply previews for a 100-acre row published at 10:00 and a 130-acre row at noon.
The first image stops at the 09:00 perimeter. If the 11:00 perimeter grows east and
withdraws a western lobe, the 10:00 preview still shows that lobe. Filtering the
current rings by date would leave the earlier preview with the lobe already removed.
If a correction later replaces the 09:00 geometry with a 105-acre perimeter, the
10:00 row loses its reconstructed image. A row with an image saved at publication
continues to show that image.

Reconstruction uses the history available when the viewer is built. A late-arriving
observation can have a date before the cutoff, and a replacement shape can have the
same acreage as the original. Saving the rendered image at publication preserves the
original map through both cases. Display refresh leaves the durable records intact.

## Refresh and response clocks

The browser makes an immediate GET and polls every 30 seconds, with a 15-second request
timeout and a guard against overlapping loads. A displayed ETag is sent unchanged.
A 304 with an existing validator preserves the display. A full successful response is
validated and rendered before saving its ETag. Invalid data, failed requests, and
unexpected 304 responses preserve the previous snapshot.

Separately, every HTTP response restarts a 60-second watchdog. A 500 response
establishes connectivity even though it cannot replace data; a rejected or timed-out
request does not. Expiry shows the last response time, or page-open time before the
first response. Browser timer delays can postpone the notice. The watchdog describes
observed responses; it doesn't prove network availability or the exact time a connection
was lost.

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

Snapshot sorting costs `O(N log N)` for retained entries and holds `O(N)` records plus
their saved image bytes. For each visible row that needs reconstruction, filtering the
matched fire's P perimeters takes `O(P)` time and space. Each eligible prefix then
incurs the [cost of differential geometry](corrected-growth-rings.md#costs-and-limitations)
for that prefix and the [cost of rendering](preview-orientation.md). Browser replacement
uses signature maps and queues, where repeated array shifts can be quadratic within a
large duplicate group. Rendering sorts matching entries and performs DOM measurement,
so its cost includes browser layout. Current browser time controls aging. Clock skew
and throttled timers can affect presentation.

Journal recovery treats preview data as part of the saved record. Reconstruction only
decorates the snapshot, so it adds no recovery transitions. Preview regressions check
historical selection and the renderer's own tests cover image construction.

- [Snapshot builder](../../src/peri_scribe/updates.py) and
  [browser implementation](../../src/peri_scribe/updates.html).
- [Shared growth-ring calculation](../../src/peri_scribe/fires/differential.py).
- [Update preview regressions](../../tests/tests/standard/peri_scribe/test_updates_previews.py)
  and [image construction tests](../../tests/tests/standard/peri_scribe/test_previews.py).
- [Projected snapshots](../../tests/formal/lean/projected_snapshots.md),
  [BrowserRefresh](../../tests/formal/tla/BrowserRefresh.tla), and
  [BrowserResponsiveness](../../tests/formal/tla/BrowserResponsiveness.tla).
- [Chronology conformance](../../tests/formal/conformance/test_update_log_chronology.py),
  [refresh conformance](../../tests/formal/conformance/test_browser_refresh.py), and
  [responsiveness conformance](../../tests/formal/conformance/test_browser_responsiveness.py).
- The [browser suite](../../tests/tests/browser/peri_scribe/) checks actual layout,
  animation, and resizing; [testing guidance](../testing.md#browser-viewer-tests)
  distinguishes those observations from finite protocol checks.
