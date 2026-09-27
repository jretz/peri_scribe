# Coordinate-reference selection

`PeriScribe/CoordinateReference.lean` covers the numerical filtering and candidate
selection in `arcgis_access.spatial_reference`. Its executable definitions are used by
`oracleCoordinateReference`; `conformance/test_coordinate_reference.py` calls the actual
Python selectors with real CRS metadata.

## Guarantees

The axis predicate is equivalent to every coordinate in the ordered interval having
magnitude inside the supplied nonnegative band. It includes exact endpoints and excludes
zero-crossing intervals when the minimum magnitude is positive. The longitude predicate
implies every coordinate in the supplied extent lies within the allowed longitude arc.
For an ordinary, nonwrapping area, that predicate is also necessary. A wrapping area
admits an extent wholly on either side of its excluded gap. The model interprets an
observed minimum/maximum pair as one connected interval; it does not infer wrapped
feature topology from two extrema.

Each known reference is classified as matching, outside its geographic area, or excluded
by domain/availability. The classification predicates are characterized exactly. A
unique matching candidate wins. Only when no matching candidate exists can a unique
out-of-area candidate be selected. Multiple matches remain ambiguous even when one
out-of-area candidate is present. Without geometry, selection requires a singleton
reported candidate list. Every returned key belongs to the reported candidates, and
permuting candidate order cannot change the result.

## Implementation connection

The bridge sends all finite binary floating-point inputs as integers under one common
positive power-of-two scale. It does not round decimal coordinates into an arbitrary
integer grid. Each axis and area comparison therefore preserves the actual supplied
ordering and signs, including subnormal values immediately adjacent to zero.

The conformance catalogue includes:

- Ordered magnitude intervals across zero and at geographic/domain limits, plus the
  immediately adjacent representable binary64 values on either side of those limits.
- Every ordered observed extent over nine longitude values, paired with every ordinary
  and antimeridian-wrapping area over those values.
- Every subset through size three of eight reference IDs, crossed with twelve geometry
  states, including missing geometry, California, Alaska, Hawaii, Puerto Rico, locations
  outside the United States, both sides of the antimeridian, zero extents, and projected
  coordinates. References include geographic datums, projected references, a vertical
  reference, and an unknown ID.

Complete selection checks compare the chosen reference, individual candidate classes,
rejection/ambiguity status, and presence of warnings. Each case also runs through Lean
with the candidate list reversed. The actual CRS database supplies domain and area facts;
Python does not implement a second expected selection algorithm.

## Boundaries

The arithmetic proofs use exact integers representing finite, positively scaled inputs.
They require ordered observed bounds and a nonnegative minimum magnitude. Nonfinite
coordinates and malformed extents are outside these guarantees. The candidate list
represents Python's set of distinct reported IDs.

CRS database correctness, deriving plausible projected-domain limits from projections,
unit metadata, and the truth of a provider's reported reference remain external
assumptions. The model proves the declared inference policy; it cannot establish that a
provider supplied enough information to identify the actual coordinate system. The
out-of-area fallback intentionally permits an otherwise plausible sole reference with a
warning. No production defect was found by these checks.
