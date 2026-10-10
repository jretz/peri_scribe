# Time series and distribution charts

Charts preserve the distinction between observation evidence and selected area, use
stable visual styles, and choose readable axes. Distribution knees are numerical fit
results that explain the displayed curve, rather than a fire-selection policy.

## Contract and assessment

Inputs are ordered, labeled numerical series with units supplied by callers, or numeric
distribution samples. Outputs are SVG or raster charts with explicit axes, legends, and
annotations. Domain adapters own which evidence belongs in each series.

| Dimension | Score | Reason |
| --- | --- | --- |
| History and state | 2 | Independent containment and length events retain separate latest-value ledgers. |
| Rule interaction | 2 | Evidence styles, missing observations, and legends must agree. |
| Mathematical reasoning | 3 | Distribution knees minimize a three-segment least-squares objective. |
| Scale and representation | 1 | Sample arrays and generated plot elements reside in memory. |
| Failure and concurrency | 0 | Rendering is a computation over supplied evidence. |

Total **8: complex**, because mathematical reasoning scores 3. Individual tick-formatting
and style helpers are straightforward parts of this behavior. Within this family,
empirical CDF rendering is involved (history 1, rules 2, mathematics 2, representation 1,
failure 0; total 6): ordered samples, zero-duration log placement, observed-rank quantiles,
and shared axes interact. The independent containment join is involved (2, 2, 1, 1, 0;
total 6): two asynchronous evidence streams supply one derived timeline.

## Time and style continuity

![A stroke transition shares its preceding endpoint](assets/chart-strokes.svg)

The destination point determines the connecting segment's style. Sharing the previous
endpoint avoids a gap when mapped and reported evidence change style.

Time-series layout selects observation span, calendar ticks, numeric ticks, margins,
and legend width. Numeric tick steps use a readable step scale; the y-axis rounds up
to a multiple and uses a nonzero fallback for an all-zero series. Lines preserve
chronological points. A new stroke style starts with the preceding point so the
transition remains connected. Legend entries describe only styles actually drawn.

Domain chart preparation uses independently reconciled incident measurements and shared
area estimates. A report's observation time and an area's effective policy time have
different meanings; caller adapters choose the appropriate series rather than changing
the evidence date. Rendering must not transfer formal confirmation between different
reported values.

## Independent containment and length clocks

A contained-perimeter estimate combines the latest mapped exterior length with the latest
reported containment percentage, using `length × percentage / 100`. A mapping update and
a report can arrive at different times. Build one map per evidence stream, with the last
input value winning at duplicate timestamps, then sort the union of both event-time sets.
Carry forward each stream's most recently supplied value independently. Emit nothing until
both have a value; a later event updates only the stream it actually supplies. Zero length
and zero percent remain valid evidence. Missing or undated values do not create events.

For example, each event changes only its own ledger:

| Event time | New evidence | Latest exterior length | Latest containment | Estimated contained length |
| --- | --- | --- | --- | --- |
| 09:00 | Mapping: 10 miles | 10 miles | Unknown | No estimate yet |
| 10:00 | Incident report: 20% | 10 miles | 20% | 2 miles |
| 11:00 | Mapping: 12 miles | 12 miles | 20% | 2.4 miles |

The new mapping changes length without inventing another containment report. Joining
only simultaneous timestamps would produce nothing; assigning the 10:00 percentage to
09:00 would use future evidence. A subsequent 0% report produces a zero-length estimate
rather than a missing one. These are estimates from independently dated inputs, not
measurements of which physical segments are contained. The join does not interpolate
containment.

For M length events and R report events, dictionary construction is O(M + R), sorting
unique times is O((M + R) log(M + R)), and the fold and stored results are linear. Source
reconciliation precedes this join and remains governed by the incident-area note.

## Empirical latency CDF and observed quantiles

The latency chart uses a different distribution contract from complementary score share:
its vertical coordinate is the fraction of samples **at or below** each elapsed time.
Sort each series in seconds. For sorted sample i, draw horizontally to its time at share
i/n and vertically to (i + 1)/n; repeated times add adjacent vertical steps at one x
position. Extend the curve to both horizontal boundaries. An empty series stays at zero.

![A moving elapsed-time cutoff counts samples on the empirical CDF](assets/chart-cumulative.svg)

*The moving cutoff shows which fixed observations contribute to the share at or below its
elapsed time. Both two-second samples enter together, making the jump from 25% to 75%
visible. The marker moves continuously along the logarithmic time axis but changes share
only at observations; it does not interpolate the CDF. The labeled complete curve remains
visible without animation. For these samples [1, 2, 2, 4], P50 is an observed two-second
sample and P90 is four seconds.*

For probability p, select sorted index `ceil(n × p) − 1`. The legend reports P50, P90,
maximum, and count; an empty series displays absent statistics. This inverse empirical
CDF returns an observed duration. An interpolated percentile would answer a different
question, especially for short series and ties.

All compared series share a logarithmic elapsed-time axis and linear cumulative share.
The axis extends from the smallest positive sample / 1.4 to the largest positive sample
× 1.4. With no positive samples it uses 1/1.4 through 14 seconds. Zero observations retain
their rank and statistics but are placed at the positive lower axis boundary. Finite,
nonnegative durations are the caller's input contract; the renderer does not validate
that contract. Candidate time ticks span milliseconds through days and are greedily
retained only when their estimated label bounds leave 16 pixels of separation. A fixed
chart and two-line legends are intended for a small set of compared series, not an
unbounded series count.

Sorting N total samples costs at most O(N log N), followed by O(N) curve work and storage.
The fixed-size raster is rendered at twice its final resolution and downsampled. Bundled
font metrics and vector substitutes for arrow/dash glyphs reduce platform-dependent
layout. These rendering measures do not change the CDF or statistical definition.

## Complementary share and knee search

![Complementary share excludes the zero-share endpoint](assets/chart-distribution.svg)

For samples `[1, 2, 2, 4]`, the visible curve contains `(1, 0.75)` and `(2, 0.25)`.
The largest value's zero share cannot appear on a logarithmic share axis.

Sort/group sample values and count multiplicities. At each distinct value `x`, compute
the fraction strictly exceeding `x`. Drop zero-share points and transform remaining
shares with `log10` for fitting and logarithmic display.

With enough visible points, enumerate two ordered breakpoint indexes. Each candidate
splits the curve into three overlapping-at-boundary segments. Fit `y = ax + b` to each
segment with least squares and sum squared residuals in `(value, log10 share)` space.
Choose the first candidate with minimum computed error, retaining deterministic loop
order for equal errors. Fewer than five visible points cannot produce two breakpoints.

This is an exhaustive optimum among the enumerated breakpoint pairs for that objective,
subject to numerical least-squares behavior. It does not locate a universal physical
threshold or minimize error in linear-share space. A hand-picked percentile would be
cheaper but answer a different question.

## Costs and limitations

For `N` samples, unique-value preparation requires sorting work of `O(N log N)` and
linear storage. For `U` visible distinct values, the knee search examines `O(U²)` pairs;
each refits segments totaling `O(U)` points, yielding approximately `O(U³)` arithmetic
for fixed-width least-squares systems. It does not use an optimized prefix-sum fit.
Ordinary series drawing is linear in points plus layout and text measurement.

Raster font metrics and SVG text estimates can differ. Floating-point least squares,
unit conversion, and degenerate distributions remain concrete numerical boundaries.
The plotted objective and selected data do not establish that a threshold is useful
for fire policy. The stroke-sharing and complementary-share figures keep simultaneous
comparisons static; the CDF animation instead exposes how a moving cutoff changes the
counted set.

## Implementation and verification

- [Time series](../../src/svg_charts/time_series.py),
  [distribution and knees](../../src/svg_charts/distribution.py),
  [cumulative latency plots](../../src/svg_charts/cumulative.py), and
  [fire plot data](../../src/peri_scribe/kml/plot_data.py).
- [Chart tests](../../tests/tests/standard/svg_charts/),
  [chart evidence conformance](../../tests/formal/conformance/test_chart_evidence.py), and
  [chart and containment specification](../../tests/formal/lean/policy_details.md).
  [Containment/plot-data tests](../../tests/tests/standard/peri_scribe/kml/test_plot_data.py)
  and [empirical CDF tests](../../tests/tests/standard/svg_charts/test_cumulative.py)
  retain ordinary boundary coverage.
  Evidence checks cover provenance and policy; numerical knee fitting and visual layout
  are exercised by ordinary tests and rendering rather than claimed as proved geometry.
