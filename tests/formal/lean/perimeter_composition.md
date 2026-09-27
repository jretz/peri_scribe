# Complete perimeter reconciliation and border classification

`PerimeterComposition.lean` adds 27 theorems and `BorderClassification.lean` adds 18.
The `oraclePerimeters` executable evaluates the definitions appearing in those proofs.
The six conformance tests compare complete production results with that executable and
exercise actual geometry, unit conversion, timestamps, and source-specific projection.

## Reconciliation through every pass

The reference follows `perimeters.history.reconcile`: split the two perimeter feeds,
sort and collapse same-source republications, combine the histories, merge identical
contemporaneous shapes, absorb competing observations into preferred observations,
collapse anchored revisions, and reject implausibly small geometry. Its output contract
requires chronological ordering. The reference canonicalizes that order explicitly;
conformance requires Python's composed output to satisfy the same complete ordered result.

The provenance proofs extend through each complete fold and their composition, including
an arbitrary number of competing-source observations. Before size rejection, every source
reference in the input occurs in retained lineage, and no foreign reference can appear.
Successful absorption requires an eligible preferred witness. After rejection, any source
reference no longer represented has a specific rejected row that carried it. Every final
row has an intermediate retained witness and fails neither size threshold.

Attribute merge gives the winner precedence on a present key and takes the losing value
only for an absent key. Every merged value has same-key support from a merge input. The
winner retains its geometry and corresponding measurement. These local attribute proofs
are separate from the unbounded complete-lineage theorem; the latter does not constitute
an independent whole-pipeline theorem for every attribute. Complete attribute composition
is additionally checked against Python, including attributes introduced by a losing feed
that later cause size rejection.

`helpers/perimeter_composition.py` supplies 1,013 histories, each under both source
preferences, comparing both the pre-filter and final results: 4,052 full-result comparisons.
Each row comparison includes its original source identity, effective time, complete source
lineage, reported computed/incident areas, and three independently conflicting or absent
attributes, raw source/category keys, and capture presence/year. Cases cross revision
and contemporaneous deadlines, capture metadata, source
and category agreement, input permutations, repeated geometry, publication winners,
existing lineage, missing/zero attributes, and final size rejection. Five hundred seeded
histories contain up to seven observations. The adapter invokes the actual full pipeline;
it does not mock GEOS or implement a second Python reconciliation policy. Another 320
histories vary missing, null, primary, alias, and conflicting policy keys. Merging updates
the normalized source/category/capture fields before subsequent absorption and revision
passes. A present null remains a present key; an absent key can inherit the losing feed's
capture, which may change the later policy decision.

The inherited geometric domain is positive-width unit-height rectangles, with exact
rational overlap thresholds. Conformance realizes their ratios with geographic rectangles
near longitude -120 and latitude 35, and measures their actual geodesic areas. Area inputs
are microacres; converting those measurements by flooring changes them by less than one
microacre. Test rejection thresholds have substantial separation from that rounding bound.
It is not a proof of arbitrary floating-point threshold equality.

The temporal domain uses present effective times, publication times, and positive object
IDs. Source and category values use normalized nonblank tokens; their primary and alias
keys distinguish absence, explicit null, and present values. Capture keys separately
retain absence, explicit null, elapsed time, and year validity. Arbitrary malformed text,
null-valued numeric measurement attributes, missing effective dates, alternate configured
size thresholds, and invalid geometry remain outside this composition model. Earlier
local models and ordinary tests retain their separately documented coverage. External
source truth and whether a source preference is scientifically appropriate are not
conclusions of these proofs.

## Border evidence and source preference

`BorderClassification` proves that a crossing classification needs geometric crossing
evidence, identifiers contribute only evidence, inside non-crossing fires prefer FIRIS,
and crossing fires prefer WFIGS. Geometry crossing requires positive inside and outside
area. A crossing cannot also be classified as merely near the border. Fractions use exact
cross multiplication, with configurable integer percentage and absolute-area thresholds.

Finite footprint union has exact membership, stays on the same side when all its parts
do, and counts every cell at most once despite overlap and duplicate input parts. The
exterior optimization's classification decisions equal the general geometry decisions.
These statements combine a set-union specification with decision-policy proofs; they do
not prove GEOS operations or the complete NumPy/PROJ implementation.

The extent reference chooses existing maximal evidence by observation clock then snapshot
serial, preserving the first input on exact ties. Missing clocks precede dated clocks;
two undated observations can be contemporaneous. Extent disagreement requires both feeds,
contemporaneous selected observations, and larger WFIGS area when the ratio threshold is
at least one. This prevents an older favorable observation from standing in for the
freshest but incompatible source pair.

Conformance covers:

- All 32 combinations of crossing, near, inside, extent, and identifier signals, including
  contradictory input flags to verify priority and the resulting preferred source.
- All 343 triples of seven exact cell rectangles, with overlapping, duplicated, wholly
  inside/outside, and crossing parts. Eighteen threshold combinations give 6,174 geometry
  decisions. The actual optimized signal equals the independently constructed GEOS union
  in every scalar field, and its decisions equal Lean's reference. The empty footprint's
  union is also checked. Twenty-one additional point, line, and collection cases check
  nonempty zero-area geometry, including the configured zero inside threshold: fraction
  zero then meets that threshold. Empty geometry's separate infinite-distance sentinel
  remains an ordinary implementation-test boundary.
- 122 complete extent histories, including missing feeds, missing clocks, serial ties,
  stale alternatives, and both sides of the 24-hour deadline. Original FIRIS and WFIGS
  coordinates pass through the production source-specific reprojection. Ideal projected
  areas and symmetric differences are exact integers with threshold margins larger than
  projection error; equality at a floating-point projection boundary is not claimed.
- 75 real reprojection/union scenarios comparing every geometry-signal field, including
  overlapping outside parts and duplicate source observations. Their independent baseline
  unions the actual reprojected parts, so this checks optimization equivalence without
  assuming a projection round trip has no numerical error.

The collection shortcut exposed an internal area inconsistency: two overlapping outside
parts with individual area 400 square meters each reported 800 rather than their union's
600. The ordinary regression failed before the correction. The outside-area field now
measures the union; classification and source preference were unchanged by this example.
The field is internal to `GeometrySignal`, not persisted in `FireClassification`.

## Executable interface

`OraclePerimeters.lean` accepts complete entry vectors for `reconciled` and `compose`;
`classify` checks signal priority and preferred feed; `geometry` evaluates exact numeric
thresholds; `union` returns unique cell membership; and `extent` evaluates the complete
freshest-source policy with supplied shape measurements. Malformed vectors fail. Numeric
attribute absence and missing clocks use `-1`; lineage masks transport bounded test
identities, while the proofs quantify over arbitrary finite histories and natural keys.
