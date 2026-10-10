# Incident evidence and mapped versus reported area

## Contract and context

Consumers need one dated area history for descriptions, charts, inclusion, and scoring.
Incident reports have their own modification and formal-report clocks, independent of
polygon capture. Preserve them from original source records before perimeter selection
can remove unchanged or losing polygons. A populated independent incident layer is
preferred; attached perimeter and point fields are the compatibility fallback.

Reports carry acres, dollars, personnel counts, and containment percentages, plus their
source and confirmation metadata. Area estimates use Pint area quantities: mapping
measurements are normally square meters and reports acres. Every selected estimate has
an effective time and a distinct supporting observation time. Histories use parsed UTC
clocks; sparse undated fallback rows must already have latest rows last.

## Complexity assessment

| Dimension | Score | Concrete reason |
| --- | --- | --- |
| History and state | 3 | Later corrections revise selected acreage, while independent confirmation ledgers and survey freshness retain earlier evidence. |
| Rule interaction | 3 | Per-field conflicts, survey evidence, report baselines, growth ratios, confirmation counts, and deadlines interact. |
| Mathematical reasoning | 2 | Geodesic area and footprint symmetric differences combine with relative and absolute policy thresholds. |
| Scale and representation | 2 | Separate report rows preserve per-field provenance, while the union of event times includes synthetic policy deadlines. |
| Failure and concurrency | 0 | Selection is a pure in-memory fold over supplied evidence. |

**Complex, total 10.** Published acreage is important independently of this classification;
consumers must share the same selector instead of independently choosing a convenient field.

## Incident reconciliation and invariants

A perimeter's attached incident fields require incident modification time; polygon time
and calculated polygon acreage cannot substitute. Missing, nonnumeric, and negative
measurements are omitted; zero remains meaningful. Confirmation requires the ICS-209
system marker and a formal report time, or explicit normalized confirmation metadata.

Sort updates by observation time, location-feed priority, serial, then source filename.
At the same instant, choose each field independently. Direct location fields win
conflicting values. For identical values, an existing newer formal confirmation survives
an unconfirmed or older-confirmed repetition. Emit separate sparse updates when fields
have different supporting metadata; never attach a winning value to another field's report.

![Winning fields travel with their supporting evidence into sparse outputs](incident-provenance.svg)

*Copies of the source fields descend into separate sparse records. The losing 100-acre
field dissolves; 200 personnel keeps the perimeter report's confirmation and source,
while the winning 120 acres keeps the incident row's unconfirmed evidence. The source
records remain visible for comparison. This is a projection of records at one observation
instant, not incident time passing. The always-visible field decisions explain the same
selection with reduced motion.*

Maintain a confirmed `(report time, value)` ledger for each field. An unconfirmed edit
citing the same or an older formal report cannot lower or replace that confirmed field;
new incident acreage growth is an exception so it can advance between formal reports.
Updates without a report-time reference do not trigger this stale-reference rule.
Confirmation in one field does not protect or overwrite another field. Replaced values
have earlier same-field support, although the emitted edit retains its own row metadata.

A separate accepted-acreage pass rejects large unconfirmed decreases: reject when
`new × 1.25 < previous accepted` and `previous − new ≥ 10 acres`. Confirmed corrections
and smaller adjustments remain eligible. This pass follows reconciliation and applies to
the most recent accepted acreage, not the greatest acreage ever reported.

## Area selection and correctness argument

Sort usable positive-area mappings by observation time. The first is surveyed. Subsequent
mappings renew survey freshness through a recognized flight source, a plausible capture
date newer than the previous survey, or a geodesically measured symmetric difference of
at least `max(1 acre, 1% of previous survey area)`. Ordinary republication remains a usable
measurement but does not reset freshness. Compare to the last survey, not the latest edit,
so many small edits cannot indefinitely postpone a meaningful cumulative change.

Build the sorted union of mapping times, accepted report times, and each mapping's one-day
and three-day policy deadlines that fall no later than the final observed event. At a
duplicate mapping/report time, the last row in that category wins. At each event, register
the report first, then mapping. A new survey records the current report baseline and
restores mapped area, even when it corrects acreage downward. A nonsurvey mapping updates
an already mapped selection, but does not displace an established reported selection.

| Route from mapping to reports | Conditions in addition to usable accepted acreage |
| --- | --- |
| Ordinary growth | Latest report is later than the survey and exceeds its report baseline; gain ≥10 acres; survey age ≥3 days; report ≥1.25 × mapped area. |
| Rapid growth | Same later-report, baseline, and absolute-gain rules; age ≥1 day; report ≥2 × mapped area; at least two distinct confirmed formal report times since the survey each reached that ratio. |
| No survey | Select the latest accepted report without mapping-age or growth requirements. |

Once reports take over, accepted reports continue until a fresh survey restores mapping.
Synthetic deadlines advance eligibility without inventing evidence: the output's
`time` can be day three while `observation_time` remains day two. No deadline is added
beyond the observed horizon, and the selector never consults wall-clock time.

This order prevents a simultaneous survey/report from being mistaken for subsequent
growth: the new survey takes the same-time report as its baseline, and takeover requires
a strictly later report. Keeping the last actual survey separate from publications
prevents stale geometry from regaining freshness merely through republishing. Selected
acreage can legitimately decrease; monotonicity is not an invariant.

## Worked examples and counterexamples

Map 100 acres on day zero; report 140 on day two; freshly survey 90 on day four:

| Effective day | New evidence or policy event | Selected area | Supporting observation | Reason |
| --- | --- | --- | --- | --- |
| 0 | Survey: 100 acres | Mapped 100 acres | Day 0 | Survey freshness begins. |
| 2 | Report: 140 acres | Mapped 100 acres | Day 0 | Survey is younger than three days. |
| 3 | Three-day deadline; no new report | Reported 140 acres | Day 2 | Ordinary growth conditions now hold. |
| 4 | Survey: 90 acres | Mapped 90 acres | Day 4 | A fresh survey restores mapping. |

The day-three deadline exists because observed history extends through day four. If the
history ends on day two, there is no day-three result. If a 150-acre report was already
known when the 100-acre survey was made, a subsequent 140-acre report cannot claim new
growth beyond that baseline.

Two edits repeating one formal report time count as one rapid confirmation. Two distinct
formal reports of at least 200 acres, with the latest report satisfying all gates, can
replace that 100-acre mapping after one day. Selecting by last download time or counting
snapshot rows would give false corroboration. An unconfirmed 200→100-acre correction is
rejected; a confirmed one remains eligible and can reduce a currently reported selection.

If dated evidence produces no estimates, current area prefers the latest usable geometry,
then the last point's incident size, then the last perimeter's supplied acreage.
Historical qualifying area instead takes the maximum usable geometry or nonnegative
reported size/discovery/final acreage across sparse rows. When dated selection exists,
current area is its last value and historical area its maximum. Raw discarded reports do
not inflate that maximum. `presented_area` for growth measurements has a simpler contract:
prefer measured geometry whenever available, then supplied acreage.

## Costs and limitations

For M mappings and R reports, sorting costs O(M log M + R log R), with O(M + R) event and
result storage. Mapping footprint comparisons add geometry-overlay/measurement costs.
The current implementation copies known-report tuples and scans report confirmations at
candidate events, so report handling can be O(R² + MR), rather than a guaranteed linear
sweep. Reusing `PreparedHistory` avoids repeating the same decision for multiple consumers.

The thresholds encode current policy, not an accuracy guarantee about source reports.
Capture parsing, geodesic kernels, valid geometry, consistent time zones, and source truth
remain assumptions. Retained metadata distinguishes evidence time from eligibility time;
changing units must not change selection.

## Implementation and verification

Owners: [incident reconciliation](../../src/peri_scribe/incidents.py),
[independent storage rows](../../src/peri_scribe/fires/incident_history.py), and
[area selection](../../src/peri_scribe/areas.py).
Tests: [incidents](../../tests/tests/standard/peri_scribe/test_incidents.py),
[areas](../../tests/tests/standard/peri_scribe/test_areas.py),
[incident storage](../../tests/tests/standard/peri_scribe/fires/test_incident_history.py),
and [area properties](../../tests/tests/property_based/peri_scribe/test_areas.py).

[Incident history inventory](../../tests/formal/lean/incident_histories.md),
[AreaPolicy](../../tests/formal/lean/PeriScribe/AreaPolicy.lean),
[AreaHistory](../../tests/formal/lean/PeriScribe/AreaHistory.lean), and
[survey evidence](../../tests/formal/lean/evidence.md) cover the policy folds.
Bridges: [incident rules](../../tests/formal/conformance/test_incidents.py),
[complete incident histories](../../tests/formal/conformance/test_incident_histories.py),
[areas](../../tests/formal/conformance/test_areas.py), and
[perimeter evidence](../../tests/formal/conformance/test_perimeter_evidence.py).
The [formal inventory](../../tests/formal/lean/README.md) records exact arithmetic and
clock abstractions. These checks do not prove external reports, floating-point geometry,
or every Python execution; real unit/time conversions and selected histories provide
implementation correspondence to the executable formal policies.
