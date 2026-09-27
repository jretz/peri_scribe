# Complete notable views and chart evidence

`NotableViews.lean` and `ChartEvidence.lean` cover eligibility and evidence that remain
after identity association and history reconciliation. `OraclePolicyDetails.lean`
executes the definitions used by all 38 theorems. Build with `mise formal-lean` and run
the actual Python/SVG comparisons with `mise formal-conformance`.

## Complete new-and-notable selection

The owners are `presentation.views.notable_score_threshold`,
`new_notable_signals_qualify`, and `new_notable_fires`. The reference first calls the
already checked `RankedViews.associations` on unresolved fires and score rows. It
attaches fire status and discovery dates by owner, and score signals by source serial.
Input owner IDs and score serials are unique source positions, as in the Python adapter.

The model proves that association retains unique owners and the exact selected score
source. It then computes the complete active-owner population. For a nonempty population
of size `n`, the top-fifth count is exactly `(n + 4) / 5`: it is positive, no larger than
`n`, and satisfies `n <= 5 * count < n + 5`. The threshold theorem partitions descending
active scores at that precise rank, with every earlier score at least the threshold
and every later score no greater. The threshold is absent exactly when that population
is empty. Inactive rows cannot change the threshold.

The complete selector has an exact membership theorem. A selected row must have a
discovery time in the inclusive five-day window and either reach the threshold or
qualify by signals. Signals require known acreage of at least 100 acres, followed by
at least 1,000 acres, evacuation overlap, or at least 100 buildings. Ties at the cutoff
qualify, and strong signals can admit a lower score. Future discoveries are excluded.
Selection retains unique owners, winning score provenance, and descending score/name
order.

The existing behavior intentionally uses active fires to establish the threshold but
does not require every selected fire to remain active. A recently discovered inactive
fire may qualify. Without any active scored owner, the entire view is empty, including
otherwise signal-qualified fires. These policies are represented explicitly rather than
inferred from a generic ranking theorem.

The bridge checks 648 complete populations with sizes zero through 26, active/inactive
subsets, missing score rows, unknown owners, colliding names, identifier aliases,
name-only fallback, repeated values, winner-dependent signals, reversed score order,
and a missing reference time. Another 980 cases cross acreage/building boundaries,
missing and zero measurements, evacuation flags, active status, and discovery times
immediately before, at, and after both window boundaries. Expected thresholds and
selected owner/source pairs come from the compiled oracle; Python does not calculate
an independent copy of the selection policy.

Names are order-preserving natural tokens and timestamps are integral UTC seconds.
The proofs use the default top fifth and integral acreage/count thresholds; arbitrary
Unicode collation, customized fractions, and floating-point rounding for populations
beyond the bridge's bounds are outside the claim. Association ambiguity follows the
documented policy in [ranked views](output_references.md), not external identity truth.

## Independent containment ledgers

`kml.plot_data.contained_perimeter_points` combines exterior-length measurements with
independently dated containment reports. The reference receives both raw input streams,
uses the last input value at duplicate source times, and forms their sorted union of
event times. The timeline is proved chronological, duplicate-free, and exactly equal
in membership to the source time union.

The streaming fold retains separate optional values for the two sources. An independent
reference scans each complete history prefix backwards for its last supplying event.
The main theorem proves the streaming fold equals that reference for arbitrary history
lengths and initial ledgers. Further theorems establish source support, absence of a
later replacement, chronological maximality of selected evidence, preservation across
missing fields, and no estimate before both measurements are known. Appending later
events cannot rewrite the earlier output prefix.

Conformance checks 1,849 pairs of raw streams with up to two observations each over
three times, including reverse order, conflicting same-time values, zero lengths, and
zero/complete containment. Real `pint` values alternate among miles, kilometers, and
feet. Added missing-length, undated-length, and containment-free incident rows must not
invent output events. Three more cases exercise real GeoDataFrame parsing of stored
exterior meters and independently parsed incident rows before combining them.

The model carries exact integral miles and percentages; arithmetic comparison applies
a tolerance only at real unit-conversion boundaries. Perimeter measurement, the truth
of containment reports, and the separate incident-reconciliation policy are not proved
here. Duplicate timestamps deliberately follow last-input priority at this boundary.

## Source styles through serialized charts

`kml.plot_data.fire_plots` translates selected mapped/reported area evidence into solid
and dashed points. `svg_charts.time_series.line_segments`, `legend_entries`, and
`draw_plot` then produce the visible line and legend.

The formal reference builds every consecutive source edge and groups adjacent edges
by their destination point's style. Its flattening theorem proves the groups conserve
every original edge in order, including multiplicity; this rules out dropped edges,
fabricated connections, and duplicate transitions. Every group is nonempty and all of
its edges have its style. The legend contains exactly the styles represented by those
edges and equivalently exactly the rendered segment styles. An isolated observation
has neither a segment nor a legend entry.

The bridge covers all 1,022 histories of zero through eight solid/dashed observations,
once with distinct times and once with paired equal times. Actual `AreaEstimate`
objects use separately retained observation and effective times, source files, and
area-unit conversion. The real `fire_plots` builder must use the effective times and
mapped/reported styles. Actual segment identities and legend entries are compared
with oracle output. For the 1,020 nonempty histories, the bridge renders and parses
actual SVG bytes, checking every path's point sequence and style and every legend
swatch and label against the same reference.

SVG coordinate placement is checked at the production layout boundary; this model
does not prove axis layout, font metrics, decimal coordinate rounding, XML parser
correctness, or renderer appearance. The new checks compose with existing area-history,
cache-dependency, and output-resource checks, rather than claiming a full proof of
all preparation and browser rendering behavior.

These bridges establish conformance for their executions. They are not an unbounded
Python refinement proof, even though the Lean list/rank/evidence theorems are unbounded.
