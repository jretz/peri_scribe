# Identity through presentation and sparse evidence

`IdentityOutput.lean` and `SparseEvidence.lean` cover the composition from grouped
identity through history selection, area qualification, and shared output facts.
`OraclePresentation.lean` executes the definitions used by their proofs. Run
`mise formal-lean` and `mise formal-conformance` to build and check them.

## Identity and output guarantees

`IdentityOutput` uses the proved `Grouping.labels` component algorithm. A selected
observation belongs to exactly the component connected to its representative.
Drawing selection retains precisely the eligible observations, with multiplicity,
and orders them chronologically. Components that share drawn evidence must be
connected. Area qualification has a witness belonging to the selected component.
These results quantify over arbitrary finite edge and observation lists; they do
not assert that a compatibility edge identifies the same real-world fire.

The module distinguishes two legacy selection contracts for inputs without component
metadata:

- `presentation.selection.area_positions` tags canonical identifiers and anonymous
  names separately. An identified row cannot enter a name-keyed area history, even
  when the identifier text equals the name. Canonical area ownership is unique.
- `presentation.history_index.HistoryRowIndex.positions_for` matches identifiers
  whenever the requested fire has identifiers. Only identifierless fires use name
  matching; that lookup can include identified rows with the same name. The Lean
  `matched` definition preserves this broader descriptive contract, including a
  checked example of that ambiguity. It preserves chronological input order.

The tagged-history ownership theorem does not apply to the broader descriptive
fallback. Separate identifierless, same-name groups can share a fallback key; these
proofs do not establish unique ownership for every legacy anonymous output entry.

Source-derived outputs carry exact internal components. Their anchor uniqueness, tagged
selection, aliases, stored geography, reports, map objects, and persisted updates are
covered by [ComponentIdentity](component_identity.md).

`helpers/identity_output.py` compares the executable reference with real
`group_fire_record_indices`, `most_common_fire`, `fire_document`, `prepare_histories`,
and `prepare_fire_data`. Its 88 scenarios cross all eight identifier graphs over
three records plus three same-name spatial configurations, four geometry-eligibility
masks, and two observation orders. Six independently tagged observations per case
expose interleaved aliases, absent shapes, acreage threshold crossings, and later
decreases. The comparison checks exact source membership, no lost or duplicated
observations across groups, drawable provenance and timestamps, current and
historical acreage, and historically qualified identities.

The same scenarios run the real shared area-qualified index through
`fire_summaries` and KMZ `fire_geometries`, comparing retained identities. Only plot
construction and image rendering are replaced. This checks their shared area
eligibility boundary; report ranking, report-specific sections, geocoding, XML/ZIP
serialization, and visual layout are outside this proof and adapter.

A further 162 selector cases compare all three-identifier alias maps and tagged
identifier/name owners with `area_positions`. Another 24 cases compare every subset
of those identifiers and three names with `HistoryRowIndex`, including anonymous
lookups of identified rows. These are separate from the 88 composition scenarios.

The chronology contract exposed a production defect: concatenating alias buckets
in identifier order could place an older observation after a newer one. The
ordinary regression in `test_fire_data_chronology.py` failed before the fix.
`fire_perimeters` now stably sorts the combined observations by time, placing
undated observations first. The composition adapter checks dated interleaving;
the ordinary regression also checks the undated ordering.

## Sparse and dated evidence guarantees

`SparseEvidence` represents missing measurements as `Option Int`, keeping zero
distinct from absence and allowing negative input to exercise filtering. Positive
measured geometry is usable mapping; nonnegative reporting evidence can contribute
to the historical fallback. A usable measurement masks that perimeter row's
supplied acreage, even when the supplied value is larger.

For current size, nonempty selected dated history wins. Otherwise the selection is
the last positive measured perimeter, then the final point row's supplied size,
then the final perimeter row's supplied area. The latter two current-size branches
preserve numeric zero and negative input. A missing final point size does not reuse
an older point row's size. Independent incident rows contribute historical evidence
but do not enter this current-size fallback.

Historical size is the maximum selected dated estimate whenever that history is
nonempty. Otherwise it is the maximum usable sparse perimeter, point, or independent
incident evidence, including discovery and final acreage. Maximum selection retains
an actual evidence witness and bounds every candidate. Historical qualification is
equivalent to some selected candidate meeting the threshold; absent evidence cannot
fabricate visibility. Appending dated corrections preserves a dated history's
existing qualification.

Visibility is deliberately not monotone when the first dated estimate replaces
undated fallback. A checked example starts with undated acreage 100 and introduces
dated acreage 1: the fire ceases to meet a 25-acre threshold. This reflects the
current precedence contract, rather than imposing an incompatible monotonicity rule.

`helpers/sparse_evidence.py` compares Lean with real `areas.prepare_history` and
`presentation.index.area_qualified_index` in 395 scenarios. The inputs cross missing,
negative, zero, below-threshold, threshold, and above-threshold measurements; missing
shapes; supplied versus measured area; final and discovery evidence; a missing or
zero final point row; and dated histories that supersede larger sparse evidence.
The dated cases use fresh mappings and exercise the actual selector before fallback.
The complete mixed mapping/report chronology is covered separately by `AreaHistory`
and the incident-history conformance suite.

## Boundaries and maintenance

The proofs are unbounded over their declared finite-list, integer-acre, and
integer-time domains. Conformance is bounded and is not a proof of Python refinement.
Stored square-meter measurements in the real GeoDataFrames isolate these policies
from geodesic rounding; the adapter compares converted acreage with a small numeric
tolerance. Geometry validity, measurement truth, fractional threshold behavior,
timestamp parsing, and external source quality remain outside these proofs.

The grouping adapter obtains its compatibility graph from the existing independent
graph relation used by grouping conformance. It does not reproduce the production
union-find or spatial representative algorithm. It still relies on that declared
identifier/proximity relation and ordinary geometry operations to describe edges.

When changing aliases, fallback matching, chronology, or output area eligibility,
update the corresponding Lean definition and proofs before implementation. Then
extend the real-path adapter with inputs that would distinguish the new contract
from the old one. Keep the distinction between tagged area ownership and descriptive
name fallback explicit when adding consumers.

The `oraclePresentation` protocol uses `|`-separated sections. `compose` evaluates
grouped observation membership, chronological drawing, and area eligibility;
`keyed` evaluates tagged canonical ownership; `matched` evaluates descriptive lookup;
and `sparse` evaluates current/historical area and threshold visibility. Missing input
is `n`; the bounded adapter reserves `-99999999` for missing output. Boolean output
uses `0` or `1`. Malformed vectors fail instead of inventing default evidence.
