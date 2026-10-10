# Source interpretation and validation

Source interpretation establishes which coordinates and attributes may be compared.
Validation then checks whether saved observations cover a complete provider response.
Content digests answer the separate question of whether an external layer changed.

## Contract and assessment

Inputs are source fields, geometry, coordinate-reference metadata, and stored frames.
Outputs include typed values, an accepted coordinate reference or explicit failure,
coverage diagnostics, and deterministic content identities. Invalid fields must not
hide a later usable field; zero remains a value. Source timestamps normalize to UTC.

| Dimension | Score | Reason |
| --- | --- | --- |
| History and state | 1 | Candidate fields are considered in a defined preference order. |
| Rule interaction | 2 | Coordinate plausibility and schema/ID checks have distinct precedence. |
| Mathematical reasoning | 2 | Coordinate domains, topology, and numerical validity constrain comparisons. |
| Scale and representation | 2 | Typed framing and sorted row digests preserve schema and multiplicity. |
| Failure and concurrency | 1 | Unreadable comparison inputs fail validation or trigger recomputation. |

Total **8: involved**. Explicit source contracts are required because an incorrect
coordinate interpretation can silently relocate every downstream geometry.

## Coordinate reference selection

Plausibility narrows the metadata candidates; it does not invent a coordinate system
when multiple candidates remain credible.

1. Collect WKIDs reported by the layer and response. With no candidates, fail. With no
   geometry, accept a single candidate; multiple candidates remain ambiguous.
2. With geometry, compare coordinate bounds against each candidate's plausible axis
   domain derived from its CRS. Projected candidates use heuristic magnitude bands.
3. Check geographic candidates' area of use, including longitude ranges that wrap
   across the antimeridian. Exactly one surviving candidate wins; multiple plausible
   matches remain an error.
4. If no candidate survives but exactly one was excluded only by area of use, select
   that candidate with a warning. Otherwise report failure.

For projected candidates, the upper bound normally comes from transforming area-of-use
corners into that CRS's native coordinate units. The minimum bound uses the numeric
meter magnitude 1,000 on each axis; the fallback upper bound similarly uses 25,000,000.
Those fixed numbers are not converted for non-meter CRSs, so they cannot be presented
as uniform physical-distance limits across units. Degree-scale coordinates and
meter-scale coordinates can disambiguate contradictory metadata, but the procedure
does not establish the provider's true CRS.

## Coverage and content identity

Coverage permits extra historical observations. A content digest retains every row's
multiplicity, so an added duplicate is still a content change.

Coverage requires unique object IDs in both frames, the same known CRS, and every
attribute column supplied by the complete response. For each complete ID, the saved
row must have matching normalized attributes and topologically equivalent geometry.
Extra stored IDs and columns are permitted. Missing IDs, changed rows, duplicate IDs,
missing columns, and CRS mismatch remain explicit diagnostics.

External-layer digests sort attribute names, encode CRS meaning, tag value types, hash
each row, and sort the row hashes before the final hash. Null representations share a
tag. Literal zero bytes are escaped and fields terminated before hashing, so values
`[ab, c]` and `[a, bc]` cannot acquire the same field stream by concatenation. Row and
column permutation is immaterial; duplicate row hashes are retained. Geometry uses WKB
in this digest, so topological equivalence alone does not imply identical digests.

| Comparison | Example | Result |
| --- | --- | --- |
| Coverage | Complete IDs `{2, 3}`; stored IDs `{1, 2, 3}` | Covered if values, CRS, and required columns match; extra stored ID `1` is allowed. |
| Coverage | Complete IDs `{2, 3}`; stored IDs `{1, 2}` | Not covered: ID `3` is missing. |
| Content digest | Rows `[A, A]` versus `[A]` | Different digests: multiplicity changed. |
| Content digest | Rows `[A, B]` versus `[B, A]` | Same digest: row order is immaterial. |

## Costs, limits, and verification

For `N` rows and `C` fields, content encoding takes `O(NC)` work plus geometry byte
processing and `O(N log N)` row-hash sorting. It retains `O(N)` fixed-size row hashes.
Coverage uses ID lookups plus field comparisons and geometry-equality work. CRS bounds
require coordinate scanning; candidate checking scales with the reported CRS count.
Hash collision resistance, CRS library behavior, and floating-point geometry are
assumptions outside ideal relational proofs. The projected bands also reject an axis
crossing zero and do not prove that valid coordinates lie inside sampled corner extrema.
This is a plausibility heuristic for resolving supplied metadata, not a general CRS
validator or an exhaustive projection-domain calculation.

- [Coordinate selection](../../src/arcgis_access/spatial_reference.py),
  [raw field parsing](../../src/peri_scribe/geo/parsing.py),
  [coverage validation](../../src/peri_scribe/sources/validation.py), and
  [external content digests](../../src/peri_scribe/sources/digests.py).
- [Coordinate reference specification](../../tests/formal/lean/coordinate_reference.md),
  [raw decoding](../../tests/formal/lean/raw_decoding.md),
  [source validation](../../tests/formal/lean/source_validation.md), and
  [source digest](../../tests/formal/lean/source_digest.md).
- [Coordinate conformance](../../tests/formal/conformance/test_coordinate_reference.py),
  [raw decoding conformance](../../tests/formal/conformance/test_raw_decoding.py),
  [coverage conformance](../../tests/formal/conformance/test_source_validation.py), and
  [digest conformance](../../tests/formal/conformance/test_source_digest.py).

The linked specifications describe their abstraction boundaries. Concrete checks exercise
the actual parser, CRS adapter, framing, and geometry comparisons.
