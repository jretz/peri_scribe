# Active and Holding fires

An agency's Active flag can survive long after a fire stops growing. Presentation
refines that flag into **Active** and **Active but Holding**, using cumulative growth
over three and seven days. Source snapshots and the fire index retain agency status.
Inactive fires remain Inactive. Holding describes the available acreage evidence; it
does not establish containment or safety.

## Contract and assessment

Inputs are agency status, independent reported and full mapped acreage histories, and
an explicit reference time. Observations carry dated, finite, nonnegative area
quantities. Naive times mean UTC. Undated, invalid, and future measurements provide no
growth evidence. Differential rings are excluded because later mapping can revise
their earlier areas. Reported area comes from the shared reconciled incident history;
mapped area comes from full measured perimeter observations.

| Dimension | Score | Reason |
| --- | --- | --- |
| History and state | 2 | Window baselines and peaks depend on observation order. |
| Rule interaction | 2 | Two windows and two independent acreage bases interact with initial-history grace. |
| Mathematical reasoning | 1 | Peak differences and strict absolute/relative thresholds use ordinary arithmetic. |
| Scale and representation | 1 | Each fire's bounded in-memory observation history is sorted. |
| Failure and concurrency | 0 | The policy is pure and publishes no persistent state. |

Total **6: involved**. The visible classification and ranked selection require a formal
policy contract in addition to ordinary numerical and integration tests.

## Windows and precedence

For a window of length W ending at T, use the latest observation at or before T−W as
its baseline. Measure the largest acreage from that baseline through T, subtract the
baseline acreage, and floor at zero. Exact-cutoff observations belong to the baseline.
The calculation does not sum positive daily changes: a decrease followed by a rebound
must not count the same acreage twice. Same-time reports retain their canonical order's
last acreage; same-time full maps use the greatest measured area.

Compare each stream with its own baseline. Never subtract a report from a map, and
never combine their acreages. Either stream can keep a fire Active:

| Window | Growth needed for Active |
| --- | --- |
| Three days | More than 10 acres **and** more than 0.5% of its baseline. |
| Seven days | More than 10 acres **and** either more than 25 acres **or** more than 1% of its baseline. |

Agency Inactive takes precedence. An agency Active fire with no usable dated past
acreage stays Active because its growth is unknown. A nonempty stream without a
three-day baseline also keeps it Active during that stream's initial three days.
A missing seven-day baseline contributes no long-window signal and grants no extra
grace. An absent stream cannot override a quiet, established stream.

Otherwise the fire is Holding. No fresh observation is required to make that decision.
As T advances without updates, the last measurement becomes the baseline and growth
becomes zero. Additional observed growth can restore Active on a later publication.
All thresholds are strict: equality does not qualify. A zero-acre baseline permits the
absolute thresholds to decide without division by zero.

## Examples and boundaries

At SISI's October 12 assessment, reported three-day growth was 19 acres from a
4,411-acre baseline (0.43%). Its seven-day growth was 87 acres from 4,343 acres
(2.00%). The three-day percentage fails; the cumulative window keeps it Active.
The selected rule kept SISI Active throughout the 52 daily September–October
assessments in the exploratory analysis. That diagnostic does not validate the rule
against all physical fire activity.

A large fire growing from 4,000 to 4,028 acres over seven days qualifies through the
25-acre route, although 28 acres is only 0.7%. A smaller fire growing from 1,000 to
1,011 acres qualifies through 1%, although it adds fewer than 25 acres. Growth of
exactly 10 acres fails both routes. A four-day-old stream with no growth and no
seven-day baseline is Holding.

The sequence 4,000 → 3,900 → 4,000 → 4,004 has four acres of growth against its
4,000-acre baseline, rather than the 104 acres obtained by summing positive steps.
A downward correction already present at the baseline can still make later growth
appear larger. These measurements describe retained acreage evidence, including its
corrections and gaps, rather than a certified physical growth history.

## Publication and selection

Shared fire preparation derives status before building report and KMZ views. An
execution scope retains one presentation time so their windows agree; standalone calls
use their current time. Explicit reference times are included in prepared-summary
cache keys. An explicit reference time also supplies the clock for subsequent views
within that execution. Derived status is never saved as an agency observation or
reused from a previous publication.

Top Fires excludes Holding owners after complete score association and identity
deduplication, before applying its 50-fire limit. This shared selection serves reports,
both KMZ Top Fires orders, and their downstream update selection. Inactive fires retain
their existing eligibility. Type 1 and the new/notable percentile population continue
to use agency activity, including Holding. Other views retain their own stated rules.

The KMZ gives Holding its own **Active but Holding** folder between Active and Inactive,
with full perimeter and progression views. The initial checked view is the first
available of Top by Name, Active, Active but Holding, and Inactive. Empty status folders
are omitted.

## Costs and verification

For N observations of one stream, sorting takes O(N log N) time and O(N) working
storage. Each of the two window scans takes O(N). Already stored measurements avoid
new geometry measurement; standalone perimeters can require their existing measurement
fallback. Source preparation, report reconciliation, and rendering have separate costs.

The [activity policy](../../src/peri_scribe/fires/activity.py) implements the pure
windows and status rules. [Shared summaries](../../src/peri_scribe/presentation/fire_data.py)
adapt authenticated histories and retain the execution's reference time. The Lean
[FireActivity specification](../../tests/formal/lean/fire_activity.md) and executable
reference check ideal acreage and time rules;
[Python conformance](../../tests/formal/conformance/test_fire_activity.py) exercises
their connection to actual quantities. Ordinary
[policy tests](../../tests/tests/standard/peri_scribe/fires/test_activity.py),
[summary tests](../../tests/tests/standard/peri_scribe/presentation/test_fire_data_activity.py),
and [KMZ tests](../../tests/tests/standard/peri_scribe/kml/test_builder.py) cover numerical
boundaries, source adaptation, cache time identity, and folder selection. These checks
establish the specified decision rule, not its statistical optimality or the truth of
agency acreage.
