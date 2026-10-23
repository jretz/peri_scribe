# Shared fire selection and ranking

Maps, reports, and update previews must agree about which evidence belongs to each fire.
Shared selection rules keep unrelated fires with the same name from acquiring each
other's facts. They also keep multiple aliases for one fire from taking multiple places
in a ranking. Row indexes preserve identity, historical area determines qualification,
and one shared association connects scores to current fires.

## Contract and assessment

Inputs are the complete fire index, authenticated full/differential/incident histories,
scores, and a reference time. Outputs are shared fire summaries and ordered report/map
views. Historical area policy is defined in [incident area selection](incident-area-selection.md).
Derived history must preserve source order and component identities.

| Dimension | Score | Reason |
| --- | --- | --- |
| History and state | 2 | Earlier qualifying dated estimates survive later downward corrections. |
| Rule interaction | 3 | Aliases, components, legacy names, and ranked views must resolve one owner. |
| Mathematical reasoning | 1 | Indexed selection, sorting, and quantile cutoffs are established operations. |
| Scale and representation | 2 | Row-position indexes and prepared facts avoid repeated frame scans. |
| Failure and concurrency | 1 | Invalid disposable facts are recomputed through cache adapters. |

Total **9: complex**.

## Evidence selection

History selection and score association use different explicit precedence rules. Both
preserve component identity and restrict legacy name fallback to the appropriate cases.

Build row-position indexes once per history layer. A recorded component selects exactly
its rows. A legacy identified fire selects its identifier aliases; a legacy anonymous
fire selects its name. Positions retain source order and raw key types. Do not coerce
an integer identifier into a string match.

Prepare incident and area history once per identity, then test historical selected area
against the inclusion threshold. A dated estimate that reached 25 acres remains
qualifying after a later measured correction to 20 acres. A conflicting large incident
report does not bypass the area's freshness policy. Undated fallback evidence follows
the same shared policy rather than a presentation-specific maximum.

Perimeter objects retain geometry, observation time, source references, and stored
measurements. Reusing added-area measurements requires the exact ordered ring-sequence
digest. The [growth-ring note](corrected-growth-rings.md) explains this order dependence.
Descriptions, geometry views, and charts consume these prepared facts; they do not
independently select a different current area.

## Sharing columns during history preparation

Every fire reads a small selection from the same source layers. Materialize each source
column as a tuple once, then give the area and incident policy a view containing only
that fire's ordered row positions. A row reads its fields from those shared tuples.
For example, positions `(7, 2, 7)` retain that order and repeated evidence even when the
source frame has duplicate index labels. The view never sorts or deduplicates evidence.

This adapter is involved: history 1, rules 1, mathematics 1, representation 2, effects 0;
total 5. Its invariant is that each selected field comes from the same source column
and positional row. Missing fields remain distinct from present fields containing
`None`, `NaN`, `NaT`, or a pandas nullable scalar. Geometry and source-attribute objects
are borrowed; consumers must not mutate them during preparation. The tuple structure
and its field mapping are immutable, but the adapter does not recursively freeze source
objects. Source columns with duplicate or non-string names retain pandas selection.

The cache fingerprints the original frames, including their schemas, row order, CRS,
and field values. Keys and serialized `PreparedHistory` records use the same codecs and
dependencies for both representations. Only a cache miss materializes shared columns;
an all-hit run reads its prepared histories without that cost. Empty input also requires
no column materialization. The first miss pays for all source layers, even when only one
fire changed, so a sparse miss can cost more than selecting that fire directly.

For `N` rows and `C` fields, materialization takes `O(NC)` time and references. It copies
column structure and boxes source scalars where required by pandas, while borrowing
geometry and attribute objects. A selection holds `O(K)` positions for its `K` rows.
Reading one field is `O(1)`; reading a selected column takes `O(K)` time and references.
Area sorting, geometry measurements, reconciliation, and serialized cache I/O retain
their own costs. The gain depends on how much time those operations leave for pandas
slicing and row construction.

This is a data-access adapter with no new policy or persistence protocol. The
[AreaHistory](../../tests/formal/lean/domain.md) and
[incident reconciliation](../../tests/formal/lean/incident_histories.md) definitions remain
the policy references. Their existing executable-reference tests run the complete area
fold and stored normalized incident histories through both representations. Ordinary
and generated tests compare complete serialized histories, including sparse fallbacks
and source provenance. These checks connect the representations to the existing
definitions; they do not prove arbitrary pandas or geometry-library behavior.

## Score association and views

Resolve aliases to their current owner before selecting ranked places. Two saved score
rows for the same current fire cannot consume two places in the view.

Resolve scores against the complete showable collection. Sort score rows by descending
score and case-folded name. Match a score's identifier first, then its component when
present; only scores without a component can use legacy name fallback. The owner retains
its first matching row, hence the highest-ranked one. Legacy duplicate names resolve to
the final same-name input position, an explicit compatibility rule rather than evidence
that the names denote the same fire.

Views have distinct eligibility rules. Top Fires excludes Holding owners after complete
score association and before its limit. This keeps an excluded owner's score from
falling back to another same-name fire, and leaves its ranked place available for the
next eligible owner. Type 1 and the new/notable percentile population use agency
activity, including both Active and Holding. The other views retain their own stated
status and evidence rules.

| View | Eligibility and ordering |
| --- | --- |
| Top fires | First 50 distinct matched owners outside Holding status in descending score/name order; inactive fires remain eligible. |
| New and notable | Discovery in the inclusive five-day interval ending at reference time, then qualifying score or signals; sorted by descending score/name with no 50-fire cap. |
| Type 1 | Agency Active, including Holding, and latest point-history designation is Type 1; sort by case-folded name. |
| Fast growth by acres | At least 1,000 mapped acres added over the 48-hour window; greatest growth first, then name, limited to 50. |
| Fast growth by percent | Known positive baseline and at least 10% mapped growth over that window; greatest percentage first, then name, limited to 50. |
| Most personnel | Known personnel with description observation time in the inclusive seven-day interval; greatest count first, then name, limited to 50. |

New/notable's threshold is the score at rank `max(1, ceil(active_scored_count × 0.20))`
among descending scores of matched owners agencies mark Active, including Holding.
Ties can admit more than that nominal fraction. If no such scored owner exists, the
entire view is empty, including otherwise strong signal cases. A recently discovered
inactive fire can qualify once that threshold exists. Signal qualification requires
known area of at least 100 acres and then either at least 1,000 acres, evacuation overlap,
or at least 100 buildings. The score route does not itself impose that acreage minimum.
Future discoveries are excluded.

Personnel is the latest known reported count from prepared description facts. Its
freshness gate uses the description's observation time, not an independently recomputed
timestamp for the last personnel field. A zero count is known and can qualify. The three
time-window view families require a reference time and return empty without one.
Time-sensitive facts are regenerated for that reference time.

For scores `A-old: 10`, `A-new: 8`, and `B: 7`:

1. Resolve both A aliases to current fire A against the complete showable collection.
2. Keep one winner per owner: A retains score 10 and B retains score 7.
3. Select the top two owners: A and B. Selecting two raw score rows before association
   would incorrectly omit B.

Identifierless fires with distinct components remain distinct even when their display
names match. A display name alone is not evidence that identified fires should merge.

## The mapped growth window

Fast-growth ranking uses measured full-perimeter geometry rather than selected reported
current area. Sort dated perimeters whose dates are no later than the reference time.
The latest supplies current mapped area; the last observation at or before `reference −
48 hours` supplies the baseline. Exact-cutoff observations belong to the baseline, and
future observations cannot supply either endpoint. No interpolation creates a perimeter
at the cutoff.

At reference time T, the cutoff is T−48 hours. The same current mapped area has
different meaning depending on the available baseline:

| Fire | Baseline at or before cutoff | Latest map at or before T | Absolute growth | Percentage growth |
| --- | --- | --- | --- | --- |
| A | 1,000 acres at T−50 hours | 2,500 acres at T−12 hours | +1,500 acres | +150% |
| B | No pre-window map; zero for absolute growth | First map: 2,500 acres at T−12 hours | +2,500 acres | Unknown |

Fire B's whole mapped area counts as absolute growth, but no percentage can be inferred.
Dividing by a fabricated positive baseline would invent a ranking; treating the absent
baseline as zero for percentage would divide by zero. Reports do not substitute for
mapped geometry. An explicit zero-area baseline also yields unknown percentage. Downward
mapping corrections can make growth negative and therefore fail the positive view thresholds.

This window selection is involved (history 2, rules 2, mathematics 1, representation 1,
failure 0; total 6), within the complete presentation algorithm's complex assessment.
Its ordering prevents future observations from changing a current result. For K perimeters
of one fire, filtering and endpoint search are O(K), with O(K log K) sorting and O(K)
working storage. Stored geodesic measurements avoid repeated geometry measurement.

## Costs and limitations

For `N` history rows, indexing takes `O(N)` time and positions. A lookup merges matching
buckets and may sort `K` selected positions in `O(K log K)`. Score association sorts `S`
rows in `O(S log S)` and builds maps over current identities. Ranking views sort their
eligible populations. Geometry, area-history, and rendering costs are additional.

Prepared fact keys include their actual dependencies and canonical serialization.
Cache reuse does not make wall-clock policy decisions permanent. Legacy name fallback
is inherently weaker evidence than explicit identifiers or components.

## Implementation and verification

- [History index](../../src/peri_scribe/presentation/history_index.py),
  [column views](../../src/peri_scribe/history_columns.py),
  [selection](../../src/peri_scribe/presentation/selection.py),
  [shared summaries](../../src/peri_scribe/presentation/fire_data.py),
  [score association](../../src/peri_scribe/presentation/score_association.py), and
  [views](../../src/peri_scribe/presentation/views.py).
- [Presentation specification](../../tests/formal/lean/presentation.md),
  [component identity](../../tests/formal/lean/component_identity.md),
  [complete notable policy](../../tests/formal/lean/policy_details.md), and
  [cache codec](../../tests/formal/lean/cache_codec.md).
- [Ranked-view conformance](../../tests/formal/conformance/test_ranked_views.py),
  [notable-view conformance](../../tests/formal/conformance/test_notable_views.py), and
  [identity output conformance](../../tests/formal/conformance/test_identity_output.py).
  These specifications separate finite checks and ideal policy from numerical geometry.
- [Area-history conformance](../../tests/formal/conformance/test_area_history.py) and
  [stored incident-history conformance](../../tests/formal/conformance/test_incident_histories.py)
  exercise pandas and column views against the same compiled Lean definitions.
- [View regressions](../../tests/tests/standard/peri_scribe/presentation/test_views.py)
  check growth-window endpoints, missing/zero baselines, personnel freshness, and view
  eligibility. These ordinary checks do not establish external source truth.
