# Fire score evidence and spatial signals

## Contract and context

Scoring ranks each fire from current area, largest mapped growth step, first-mapping size,
nearby building count, evacuation overlap, and the latest official complexity level.
The current score is recomputed from current evidence, independent of earlier score files.
Results contain each weighted contribution and an explanation, sorted by descending score
then name. Missing spatial datasets contribute zero rather than inventing observations.

Inputs are authenticated full/differential/incident histories where available, plus the
current building-centroid and evacuation datasets. Geometry uses WGS84 for queries;
acreage is converted from Pint at the tier boundary. Histories preserve fire identity
keys and chronological order. Full histories supply current size through the shared
[area policy](incident-area-selection.md); differential history supplies mapped growth.

## Complexity assessment

| Dimension | Complete score preparation | Tier arithmetic alone | Concrete reason |
| --- | --- | --- | --- |
| History and state | 2 | 0 | Current area, first mapping, greatest step, and latest complexity refer to different historical positions. |
| Rule interaction | 2 | 1 | Evidence must remain aligned across histories; tier rules are independent inclusive thresholds. |
| Mathematical reasoning | 2 | 1 | Reprojection, buffering, and spatial predicates feed an ordinary weighted sum. |
| Scale and representation | 2 | 1 | Batched/indexed queries and exact row-position signatures preserve identities during sharing. |
| Failure and concurrency | 2 | 0 | Dataset/cache reads, parallel buffers, and separate JSON/chart writes have distinct failure boundaries. |

**Complete preparation is complex, total 10; tier arithmetic is straightforward, total 3.**
The detailed note is required by the composed algorithm and also records the simple score
contract because its thresholds determine which fires readers see first.

## Evidence selection and invariants

Group rows by external identifier, anonymous component, then legacy name fallback, using
[distinct key namespaces](fire-grouping-and-ownership.md). Prefer perimeter rows for the
name/identifier, with point rows filling missing fire entries. Current area comes from
`areas.latest_area`. Growth is the greatest differential geometry acreage, falling back
to supplied differential acreage when geometry measurements are unavailable. First mapping
uses cumulative measured acreage on the earliest differential observation, again with a
supplied-area fallback. It is not the current reported acreage at that time.

Shared current-area policy prevents scores and descriptions from disagreeing, while
reported growth alone does not invent a mapped first size or growth ring.

The latest point-history row alone determines official importance. An omitted or unknown
complexity level gives zero, even if an earlier row had Type 1. This is a current status
signal rather than maximum historical importance. When reusing presentation-prepared area
histories, require identical ordered row-position groups in all three layers; alias
normalization or a string-key collision can otherwise join different evidence. Missing
or invalid source indexes cause local recomputation rather than fabricated aliases.

Use each fire's latest full perimeter for spatial signals; if absent, use the union of
its point geometry. Differential rings are not re-unioned to estimate current exposure.
Build building-distance buffers in Web Mercator using 1 mile converted to meters, then
transform back to WGS84. Preserve original positions around missing geometries during
vectorized reprojection and ordered parallel buffer results.

![Different geometry predicates feed building and evacuation signals](scoring-spatial.svg)

*Buildings use strict point containment in the buffered footprint; a centroid exactly on
that boundary is excluded. Evacuation overlap tests the unbuffered fire geometry, including
a boundary touch. Shapes are schematic, not a scale drawing.*

Building queries count stored centroids, including duplicates, with strict containment.
Evacuations use geometric intersection. Buffering in Web Mercator uses projected distance;
its real ground distance varies with latitude, so “within a mile” is the current display
label and configured projected buffer, not a guarantee of a geodesic one-mile offset.
Projection limits and antimeridian geometry retain the underlying geometry assumptions.

## Tier policy and worked example

For each descending threshold list, take the first threshold the input meets using `>=`.
Unknown or below-minimum values earn zero. Thresholds are inclusive even when generated
English explanations say “over.” These are policy points, not probabilities or calibrated
predictions of losses.

| Signal | Thresholds, descending | Tier points | Weight |
| --- | --- | --- | --- |
| Current acres | 100,000; 50,000; 25,000; 10,000; 1,000 | 5; 4; 3; 2; 1 | 27 |
| Largest growth acres | 50,000; 25,000; 10,000; 5,000 | 4; 3; 2; 1 | 15 |
| First-mapping acres | 5,000; 1,000; 100 | 3; 2; 1 | 11 |
| Buildings | 1,000; 250; 50; 5 | 4; 3; 2; 1 | 4 |
| Evacuation intersection | True | 3 | 11 |
| Current complexity | Type 1; Type 2; Type 3 | 3; 2; 1 | 120 |

With current size 10,000 acres, growth 5,000, first mapping 1,000, 50 buildings, evacuation
intersection, and Type 2, contributions are 54 + 15 + 22 + 8 + 33 + 240 = **372**.
Exactly 10,000 acres qualifies for size tier 2. Removing the latest complexity value drops
importance to zero; carrying Type 2 forward from an older row would be wrong.

The maximum under the current nonnegative tiers is 135 + 60 + 33 + 16 + 33 + 360 = 637.
Each independent signal is monotone at fixed other inputs, but real scores need not be:
new surveys can reduce area, official complexity can decrease, and external datasets can
change. A reported current area can raise size points while mapped growth remains fixed.

Summing all reached tier awards would overcount. Reusing area by canonical name alone
could combine namesakes or aliases differently from scoring's identity groups. Reusing
building counts across changed dataset bytes could retain stale exposure even when a
fire's geometry is unchanged. Those shortcuts violate separate invariants.

## Costs, caching, and limits

For N history rows and F fires, grouping is normally O(N), chronological selection and
final ordering add O(N log N + F log F), and current-area computation has the per-fire
costs documented in the area note. Tier evaluation is O(F) for the fixed lists. Geometry
projection and buffering depend on total coordinates; at most eight workers buffer fires.
Input history frames and output geometry remain materialized in memory.

Building and evacuation indexes reduce candidate reads, but dense candidate populations
still require full exact predicate checks. Tile decompression, building-count encoding,
and evacuation envelope guarantees are owned by their spatial implementations. Product
keys include exact ordered WKB/SRID, buffer distance and projection definitions, and for
counts the authoritative dataset checksum and counting metadata. Damaged products are
misses; a live SQLite WAL bypasses count reuse. Geometry-equivalent reordered WKB can miss
the cache safely. [Geography generations](geography-generations.md) covers cache and
publication contracts; separate JSON and chart writes are not one atomic pair.

## Implementation and verification

Owners: [score preparation](../../src/peri_scribe/fires/scores.py),
[tier model](../../src/peri_scribe/fires/scoring.py),
[buffers](../../src/peri_scribe/fires/buffering.py), and
[spatial products](../../src/peri_scribe/fires/spatial_products.py).
Tests: [scoring](../../tests/tests/standard/peri_scribe/fires/test_scoring.py),
[score preparation](../../tests/tests/standard/peri_scribe/fires/test_scores.py),
[shared histories](../../tests/tests/standard/peri_scribe/fires/test_score_sharing.py),
[component identities](../../tests/tests/standard/peri_scribe/fires/test_score_components.py),
and [tier properties](../../tests/tests/property_based/peri_scribe/fires/test_scoring.py).

[Scoring proofs](../../tests/formal/lean/PeriScribe/Scoring.lean) and
[conformance](../../tests/formal/conformance/test_scoring.py) cover tier bounds and
monotonicity under their ordered-award/exact numeric domain. The
[formal inventory](../../tests/formal/lean/README.md) records unit/rounding boundaries.
[Spatial boundary inventory](../../tests/formal/lean/spatial_boundaries.md) documents
indexed evacuation queries and strict spatial assumptions. These are compositional
contracts and sampled implementation checks, not a proof that the ranking predicts
importance, that external data is complete, or that all native spatial operations are exact.
