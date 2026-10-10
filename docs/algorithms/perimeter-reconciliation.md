# Perimeter reconciliation and survey evidence

## Contract and context

A fire's retained FIRIS and WFIGS observations become one chronological perimeter history.
Inputs carry geometry, effective observation time, snapshot time/serial, object ID, raw
attributes, and source lineage; classification chooses the preferred feed. Geometry is
already in a common coordinate domain for equality and overlap. Output retains source
attribution and is suitable for cleaning and full-history measurement.

The effective clock is the observation date, then the row's edit/modification date, then
its snapshot date. Snapshot time is only a fallback: a newly downloaded old polygon is
not automatically a new survey. This policy runs both in generation and historical replay.

## Complexity assessment

| Dimension | Score | Concrete reason |
| --- | --- | --- |
| History and state | 3 | Later publications replace earlier versions while preserving evidence and original freshness. |
| Rule interaction | 3 | Feed preference, capture credibility, overlap, attribute precedence, and rejection interact across passes. |
| Mathematical reasoning | 2 | Topological equality and intersection/union overlap determine distinct retention decisions. |
| Scale and representation | 2 | Complete provenance and source attributes must survive reductions in differently ordered histories. |
| Failure and concurrency | 0 | Selection is an in-memory policy; persistence belongs to generation. |

**Complex, total 10.** Discarded mappings must remain explainable from their retained
lineage or final rejection witness.

## Approach and invariants

Pass order matters: inherited attributes and capture metadata can affect later revision
or size decisions. Cleaning follows reconciliation and cannot retroactively justify a
selection decision.

1. Split by source and sort by `(effective time, serial, object ID)`, using the earliest
   sentinel for undated observations. Collapse consecutive equal footprints unless
   advancing capture evidence establishes a new survey. A republication keeps the newest
   attributes and lineage, but the earlier effective time.
2. Combine the two sorted histories. Merge contemporaneous equal shapes, with the preferred
   feed supplying geometry and values on present attribute keys. Missing keys can inherit
   from the loser; a present null is still present. Both source lineages survive.
3. Compare each nonpreferred observation directly against preferred observations, newest
   first. Absorb it when publication times are within four hours or credible capture and
   sufficiently similar geometry show a delayed older survey. A comparison to an absorbed
   nonpreferred observation cannot create a transitive chain of preference.
4. Collapse close revisions, requiring agreement with both the group's first observation
   and its currently retained version. Retain the greatest publication time, serial, and
   object ID within the eligible group; retain all source references.
5. Reject implausibly small final mappings using measured area and merged computed/incident
   area attributes.
   [Geometry policy](perimeter-geometry-policy.md) describes the final thresholds and
   subsequent cleaning.
6. Clean the derived geometry to remove rendering artifacts, then measure the retained
   cleaned shape.

The default preferred feed is FIRIS, including inside-near-border fires. Crossing and
outside classifications prefer WFIGS because its mapping is intended to cover the full
extent. The classification is a feed-selection policy within nationwide processing.

A delayed capture is credible only when it is in the publication year and between zero
and two days old. It is superseded when a preferred observation is no later than that
publication, the candidate capture is no later than the preferred capture (or effective
time) plus four hours, and intersection/union area is at least 0.95. Substantial footprint
changes remain eligible even with a stale capture field.

Revision pairs require the same feed, nonblank matching source and feature-category
metadata, a nonnegative effective-time gap of at most five minutes, and overlap at least
0.99. Missing or invalid geometry cannot establish overlap. Equality and overlap are
separate predicates: equal shape is topological, while overlap uses planar area ratios
in the shared coordinate domain.

![An anchored revision window prevents chaining](perimeter-revision-window.svg)

*Edits at 00:00 and 00:04 can form one revision group. The 00:08 edit is close to 00:04,
but outside the first observation's five-minute window, so it starts another group.*

The correctness argument follows preservation across these passes. Collapse or absorption
adds the losing source reference to the winner. Before size rejection every original
reference remains represented, and none is invented. Every competing-feed loss has a
preferred witness; after size rejection, a missing reference must have been carried by
an explicitly rejected row. This is a provenance guarantee, not a guarantee that every
original attribute survives: winner precedence intentionally resolves conflicts.

## Worked examples and boundaries

An inside fire has a FIRIS survey at 10:00 and a WFIGS observation at 12:00. The latter
is
within four hours, so FIRIS wins even if shapes differ; WFIGS remains in the winner's
lineage. If WFIGS instead publishes at 17:00 with capture 09:30 and 0.98 footprint overlap,
credible delayed-capture evidence can still justify absorption. A 0.80 overlap cannot
justify that delayed-copy route. A truly newer capture outside the capture tolerance
also stays eligible.

A repeated footprint at a later publication time normally keeps its first effective time.
A different flight object from a recognized flight source, or a plausible capture date
newer than the preceding effective time, preserves a separate survey even if the shape
is identical. Blind geometry deduplication would incorrectly hide that survey.

Revision chain 00:00 → 00:04 → 00:08 illustrates why pairwise closeness alone is wrong:
it can combine observations spanning an unbounded time interval. The anchor bounds the
whole group; the retained-member check additionally prevents drift in geometry/source
compatibility. Arbitrary regrouping or globally picking the newest snapshot cannot
preserve these distinctions.

Point histories use a different contract: sort by snapshot serial and retain one version
per distinct normalized attribute state. A location-only move updates the retained
version's geometry and source snapshot without creating a new incident state. Independent
incident reporting is extracted before perimeter removal; see
[incident and area selection](incident-area-selection.md).

## Costs and limitations

For N observations, sorting is O(N log N). Equal-observation search and preferred-witness
search may each examine O(N²) pairs. Equality, overlay, and geodesic measurement costs
also depend on vertex counts and intersection complexity; they are not constant-time
operations. Retained rows are O(N), while repeatedly copying growing lineage can require
quadratic work and transient storage. Source attribute byte size is another input bound.

The fixed tolerances deliberately express policy. There is no claim of optimal scientific
source selection, exact real-world capture truth, or robustness for arbitrary invalid
polygons. Dateless histories and exact input ties retain implementation ordering rules;
the formal composition model's narrower timed domain is documented below.

## Implementation and verification

Owners: [history composition](../../src/peri_scribe/perimeters/history.py),
[versions](../../src/peri_scribe/perimeters/versions.py), and
[full-history rows](../../src/peri_scribe/fires/history.py).
Tests: [version regressions](../../tests/tests/standard/peri_scribe/perimeters/test_versions.py),
[version properties](../../tests/tests/property_based/peri_scribe/perimeters/test_versions.py),
and [size filtering](../../tests/tests/standard/peri_scribe/perimeters/test_size_filtering.py).

[PerimeterComposition and BorderClassification](../../tests/formal/lean/perimeter_composition.md)
explain complete-lineage preservation, attribute precedence, and rejection witnesses.
[PerimeterVersions evidence](../../tests/formal/lean/evidence.md) explains anchored revision
and survey freshness. Bridges are
[complete composition](../../tests/formal/conformance/test_perimeter_composition.py) and
[local evidence](../../tests/formal/conformance/test_perimeter_evidence.py).
The composition uses finite rectangle fixtures, valid effective times, normalized tokens,
and bounded numerical margins. It does not prove GEOS or arbitrary floating-point equality,
malformed attributes, all missing-date paths, or that feed preference is scientifically
correct. Ordinary tests cover additional parsing and geometry boundaries.
