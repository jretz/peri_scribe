# Perimeter and publication evidence

`PerimeterVersions.lean` adds 20 explicit theorems and
`PublicationCandidates.lean` adds 27. The default `oracleEvidence` target evaluates the
same definitions used by those proofs. The shared axiom audit includes both modules.
The eight conformance tests in `test_perimeter_evidence.py` and
`test_publication_evidence.py` compare oracle outputs with production functions.

## Retained perimeter versions

`PerimeterVersions.lean` corresponds to these functions in
`src/peri_scribe/perimeters/versions.py`:

- `new_capture` and `collapse_identical_consecutive_perimeters`: consecutive identical
  footprints collapse only without fresh capture evidence. The newest publication keeps
  the preceding effective observation time, so publication alone cannot renew that clock.
  Inheritance, individual collapse steps, and the complete collapse fold preserve exactly
  the union of the input observations' source references.
- `revision_pair` and `collapse_mapping_revisions`: each accepted revision is compared
  with the original group anchor and the retained observation. Every member of every
  resulting group stays within the anchor's five-minute window. Consecutive near-time
  edits therefore cannot extend the window indefinitely. The publication winner retains
  provenance through individual steps and the complete revision fold.
- `credible_capture_time`, `mapping_is_superseded`, and `drop_losing_source_versions`:
  absorption selects the first eligible preferred observation. A discarded observation
  always has an actual eligible witness in the supplied preferred list, and its entire
  source lineage remains represented by the resulting observations. The eligibility
  definition includes the four-hour contemporaneous window, same-year capture evidence
  at most two days old, delayed-copy timing, and the 95% footprint overlap threshold.

Conformance checks complete winners, effective times, and lineage sets for 981 histories
through both collapse functions, plus 2,128 consecutive pairs through `new_capture`.
Inputs include the exact five-minute boundary, chained revisions, publication-order
winners, source and category disagreement, flight-object changes, missing and implausible
capture dates, and existing superseded lineage. Production collapse receives reversed
inputs to exercise its own sorting. The revision fold receives chronological inputs,
matching its caller contract. Another 392 cases call `drop_losing_source_versions` with
one losing observation and two preferred alternatives, checking both no-replacement and
replacement outcomes around temporal and overlap boundaries.

The footprint domain is exact positive-width, unit-height rectangles with integer
coordinates. Intersection-over-union thresholds use rational cross multiplication.
Conformance constructs the corresponding Shapely rectangles and exercises production
GEOS equality and overlap calculations. The proofs do not establish GEOS robustness or
arbitrary polygon equivalence. Feed/source/category tokens are already normalized;
observation and publication times are present elapsed UTC seconds, and object identifiers
are nonnegative ranks. Missing-time fallback, source parsing, and geographic preference
classification are separate implementation boundaries. The source identity used in
proofs represents the complete `source_file#object_id` token; conformance gives each row
its own file and compares lineage as sets.

The supersession proof covers the complete preferred-list search for one losing record,
not induction over the outer sequence of competing records. The supplied preferred list
has production's descending order. The full `merge_identical_observations` attribute
merge, preferred-source selection, and the entire `reconcile_perimeter_versions`
composition are not claimed as proved by these modules.

## Survey freshness

The same module corresponds to `areas.new_survey` and `areas.mapping_history`. Its survey
fold keeps the last actual survey as its comparison baseline. Ordinary republication
without flight or valid capture evidence cannot establish a survey; capture evidence
cannot refer to a future instant. Insignificant geometry edits preserve the preceding
survey. An arbitrary sequence of observations that each fail the survey test against that
baseline leaves the last actual survey unchanged.

The executable survey classifier includes flight evidence, same-year capture metadata,
strictly newer capture time, the one-acre absolute footprint-change threshold, and the
1% relative threshold. The fold updates its baseline only when that classifier accepts
an observation. This closes the freshness-input boundary of the separate `AreaHistory`
model; it does not replace that model's report-selection and deadline proofs.

Conformance compares every `surveyed` flag from the real `mapping_history` on 361 complete
histories, including a small intervening edit followed by evidence that must be compared
with the last actual survey. Six actual WGS84 polygons supply a matrix of geodesically
measured symmetric differences. All stored areas in these cases are 100, 200, or 1,000
acres, making their default thresholds integral acres; flooring the measured differences
therefore preserves the threshold comparison. Flight, missing, repeated, future, and
wrong-year capture metadata vary independently. Inputs arrive in reverse chronological
order to exercise production sorting.

The proof uses exact natural acreages and elapsed seconds with the default policy. It
assumes usable, dated, positive-area mappings. Invalid/empty geometry rejection, unknown
dates, arbitrary fractional measurements, custom policies, year parsing, and floating-point
unit conversion are not proved. The real conformance path exercises the relevant pandas,
Pint, Shapely, date-parsing, and geodesic-measurement adapters on the documented inputs.

## Publication capture and candidate identity

`PublicationCandidates.lean` corresponds to `publication.first_captures`,
`candidate_fires`, `mapping_decision`, and the source-row join in `published_fires`.

Capture propagation uses the earliest supplied capture in each connected component.
Minimum selection returns existing evidence and is no later than any member. Component
members share a capture clock; propagation is idempotent and cannot move clocks forward.
The concrete capture graph references only existing mapping vertices. Its representative
lookup is connected to the `Grouping` table refinement theorem, establishing that
connected mappings receive the same earliest clock in the executable definition.

The graph relates mappings sharing an identifier and a shape. Production instead walks
identifier/shape vertices. Their correspondence is checked by 726 mapping streams,
including alias bridges, all permutations of a four-mapping chain, isolated records with
no identifiers, distinct shapes sharing aliases, and repeated collection. The unbounded
proof covers the mapping graph and its component minimum; it does not include a separate
bipartite-graph refinement proof for Python's identifier traversal or SHA-256 collisions.

Candidate selection begins with a supplied unique published ownership relation. Multiple
known owners or missing identifiers require a build; accepting a key preserves any known
owner. Collapsed observations leave candidates unchanged, and uncertainty remains
absorbing through the complete candidate fold. Candidate replacement selects the latest
mapping under the supplied lexicographic order rank and cannot select an observation
older than the current candidate. The executable fold also carries newly learned aliases
forward and preserves the first candidate when observation-order keys tie.

Conformance compares the full ordered candidate dictionary in 2,904 streams and checks
that each retained candidate carries the actual checkpoint baseline for its selected key.
Cases include initial ownership, shared and conflicting owners, aliases learned during
the fold, empty identifiers, collapsed observations, older candidates, and ties. Mapping
order ranks are realized with real observation times, snapshot serials, and object
identifiers, including absent observation times. Identifier tokens `i0` through `i2`
make their natural-number order agree with the production canonical identifier order.
General identifier normalization and the special canonical preference for unique fire
identifiers are not proved. Existing published aliases are assumed consistent.

## Publication area comparisons and raw baselines

Older observations are excluded before area uncertainty is assessed. Unknown eligible
measurements require a build. Known comparisons retain the signed change with largest
absolute magnitude, including shrinkage, and preserve the earlier result on equal
magnitudes. The maximum dominates every eligible change and has an actual measurement
witness, so it cannot invent a larger signal. A refinement theorem connects the executable
comparison fold with the independently specified list of eligible signed changes and its
maximum. Positive threshold equality treats growth and shrinkage symmetrically; an
all-zero change set remains below threshold even when the configured threshold is zero.

Conformance runs 3,124 complete comparison sets through the real `mapping_decision`,
checking proceed, uncertainty reason, signed square-meter change, and selected fire.
It includes absent baselines, unknown current and baseline areas, older observations with
unknown area, zero measurements, ties, several candidates, and changes around thresholds.
Areas are exact natural square meters in Lean and real Pint quantities in Python.
Python's relative `isclose` tolerance, nonintegral measurements, overflow, and floating
roundoff remain numerical boundaries; this proof establishes the exact discrete policy.
The separate [numerical policy model](numerical_policy.md) covers finite rounded
comparisons, fractional areas, unit conversion order, and the relative tolerance.

For displayed source rows, the executable raw-source selector requires exactly one match
on both source file and object identifier. Its theorem supplies that matching raw witness
and excludes all other matches. Duplicate source keys cannot supply a baseline. A valid
source for a fire excluded from the output yields no displayed area baseline.
Conformance exercises 680 real `published_fires` joins over exhaustive inventories of
zero to three raw rows on four possible source keys. It checks missing and duplicate
matches, distinct raw measurements, numeric object-ID parsing, inclusion through an
identifier or an alias, and excluded fires. The proof's inclusion Boolean abstracts the
index's visibility relation. [Publication baseline ownership](publication_baseline.md)
extends this source-association proof to complete row streams, accumulated aliases,
repeated owners, explicit index entries, and anonymous-name inclusion. Its separate
implementation connection exercises the actual history-to-index and visible-output path.

## Executable interface

`OracleEvidence.lean` accepts one command per line and produces integer tuples. Empty
lists produce empty response lines. All proof definitions quantify over arbitrary finite
lists; the oracle uses 32-bit membership vectors solely to transport finite test identities.
Time and measurement fields are natural numbers, with `-1` for optional values.

| Command | Evaluation |
| --- | --- |
| `capture PREVIOUS CURRENT` | Fresh capture classification. |
| `collapse OBSERVATION ...` | Retained source identity, effective time, and lineage mask. |
| `revisions OBSERVATION ...` | Anchored revision winners and their time/provenance. |
| `absorb LOSER PREFERRED ...` | Updated preferred observations, or `-1` without a witness. |
| `survey DIFFERENCE_MATRIX SURVEY ...` | Survey flags from the complete baseline fold. |
| `first MAPPING ...` | Component-minimum capture time for every mapping. |
| `candidates ALIASES MAPPING ...` | Ordered key/source pairs, or `-1` for ambiguity. |
| `compare THRESHOLD CURRENT:BASELINE ...` | Proceed, uncertainty, signed change, selected source. |
| `raw FILE OBJECT INCLUDED SOURCE ...` | Raw source identity, `-1` for invalid association, or `-2` for an excluded baseline. |

Comma-separated record fields are defined in the typed parser and the matching helper
transport methods. Geometry measurements and normalized identities are explicit inputs,
not conclusions of the proof. Conformance uses these compiled definitions directly and
does not implement a second Python policy to generate expected results.
