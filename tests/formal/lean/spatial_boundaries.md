# Spatial query, growth measurement, and differential-row boundaries

These modules check questions left outside the geography, spatial-index, and point-store
proofs: whether an indexed overlap query finds every real match, whether growth rings
retain their source evidence, whether surface measurements count only polygonal ground,
and whether coordinate rounding preserves the required query coverage.
`OracleSpatial.lean` evaluates the definitions used in these proofs. Run `mise
formal-lean` and `mise formal-conformance` together.

## Evacuation overlap queries

`PeriScribe/SpatialOverlap.lean` has 13 theorems covering
`spatial_data.overlaps.overlapping_layer_indices`, `candidate_fids`, and
`overlapping_indices`, used by evacuation evidence in fire scoring.

The executable model represents a shape as a finite union of closed integer rectangles,
including degenerate rectangles representing lines and points. It computes envelopes
from the parts and proves that those envelopes enclose every part. Every exact
intersection survives envelope filtering. Indexed matching therefore has exactly the
same original query identities as exhaustive matching. Matching any list of streamed
batches has the same identities as matching their concatenation. Empty footprints never
match; distinct queries with identical geometry keep their distinct identities.

`conformance/test_spatial_overlap.py` exercises 16 source populations against 186 query
positions in 64 actual GeoPackages. Both indexed and genuinely unindexed files are
written by GDAL, in WGS84 and Web Mercator, with sparse feature IDs, null and empty
features, disconnected unions, holes, boundary touches, degenerate features, duplicate
source features, and duplicate query geometry. Chunk sizes 1, 3, and 100 give 192
complete production queries. Exact results come from Lean, rather than another Python
spatial search. Null and empty query slots remain in the original indexing scheme.

This proves the rectangle-union abstraction, not GEOS, STRtree, PROJ, GDAL, or SQLite.
The conformance cases exercise those libraries and the real GeoPackage blob decoder. The
index is assumed complete and consistent with the layer. Stale or corrupt R-trees,
invalid geometry, arbitrary nonrectangular curves, antimeridian interpretation, and
numerical behavior under every projection remain outside the proof. Envelope false
positives are permitted; losing an actual modeled intersection is not.

## Differential source attribution and displayed ring sequence

`PeriScribe/DifferentialRows.lean` has 17 theorems covering
`peri_scribe.fires.differential.corrected_geometries`, `growth_indices`,
`representative_indices`, `growth_difference`, `differential_rows_for_fire`, and
`measure_drawn_rings`. The presentation connection includes
`presentation.fire_data.progression_ring` and `kml.colormap.progression_ring_colors`.

The executable correction uses `Geography.reverseCombine` and proves agreement with
intersection against every later footprint. Candidate groups retain a growth footprint
while subsequent non-growth observations update its representative. A whole-block proof
establishes that an arbitrary block of non-growth observations selects exactly its last
observation's metadata and preserves the candidate ring. Every final representative has
an original source witness. Candidate boundaries put representatives inside their own
block. Sparse deltas subtract the most recent prior candidate measurement that is present,
distinguish missing values from zero, and preserve negative corrections. Complete present
measurement changes telescope to the latest value, even with missing measurements
between them.

Candidate attribution precedes ring emission and visibility filtering. A candidate whose
constructed geometry disappears can still provide source measurements to a later
candidate. That is intentional: omission does not erase incident cost, containment, or
reported acreage evidence. Deltas are not claimed to telescope across only the displayed
rings. The visible sequence consists exactly of emitted, dated rings above the area
threshold and preserves candidate order.

`conformance/test_differential_rows.py` compares 620 histories at two geometric scales,
for 1,240 executions using real GEOS correction and differences. Short three-observation
histories exhaust the eight masks over three cells; fixed and seeded histories extend to
four cells and nine observations. The checks include shrinkage, empty footprints,
repeated non-growth observations, missing and tied timestamps, sparse missing numeric
fields, numeric strings, zero, negative corrections, and distinct source provenance.
Every returned row is checked against the oracle for representative identity, original
source file/object ID/time, all four cumulative fields and deltas, exact footprint,
cumulative geometry acreage, and differential geometry acreage/area.

Real surface areas are explicit inputs to the visibility abstraction, conservatively
encoded upward to integer millionths of a square meter for the one-square-meter strict
threshold. Large and submeter cell unions exercise both sides. For the oracle-selected
visible sequence, conformance independently hashes the returned ordered WKB records,
checks stored digests, compares stored added area against independently recomputed
cumulative unions, and compares the sequence with actual presentation/color selection.
The presentation fallback to a latest perimeter when no dated ring exists is separate
from this differential sequence contract.

Five further executions inject only the geometry backend's numerical-empty outcome for
selected candidates. Actual correction, candidate selection, metadata, deltas, remaining
GEOS differences, and presentation stay in use. These traces verify the documented rare
sliver branch; they do not claim to produce naturally occurring floating-point slivers.

The cells use binary-coordinate boundaries preserved by the growth precision grid. The
proofs use finite sets of exact cells, exact integer source measurements, and an
explicit area function. They do not prove geometry kernels, surface integration,
floating-point subtraction, timestamp parsing, or SHA-256 collision resistance. The
oracle uses four-cell fixtures, but the Lean algorithms and theorems are not bounded to
four cells or nine observations. Source/geometry sequences are aligned and already in
history order, as supplied by the production caller.

## Polygonal surface measurement and cumulative growth

`PeriScribe/GrowthMeasurement.lean` has seven theorems covering the polygon-only policy
in `spatial_data.surface_measurements.area` and the ordered coverage fold in
`peri_scribe.perimeters.progression.added_areas`. The model was compiled before the
production numerical adapters were implemented.

A geometry tree contains polygon surfaces, nonpolygon coordinate contributions, and
nested binary collections. Polygon contributions are nonnegative integer inputs to this
abstraction. The proofs establish that filtering retains every polygon contribution and
that arbitrarily changing every nonpolygon coordinate contribution cannot change area.
Binary collections preserve the nesting of arbitrary collection sizes. This models the
surface policy; it does not establish equality of every floating-point addition order.

A separate exact model represents footprints by Boolean membership in finite cells and
surface area by nonnegative integer cell weights. Cumulative union cannot reduce area.
Revisiting covered ground adds zero. The successive added areas telescope from an
explicit initial footprint to the final union; an empty initial footprint counts final
coverage once. The theorem holds for arbitrary cell weights and history lengths. It
depends on an additive measure and exact union, rather than assuming the geodesic area
of a vertex representation is an additive planar measure.

`conformance/test_growth_measurement.py` compares the real polygon-only adapter with the
executable collection definition on polygons, holes, reversed winding, empty shapes,
points, open and closed lines, multipart geometry, and nested collections. It compares
the real progression measurement with the executable weighted-cell definition on 639
histories. Short histories exhaust all eight masks over three cells through length
three; longer fixed and seeded histories use four cells, duplicate ground, partial
overlap, decreasing source footprints, and empty inputs. The cells have binary-coordinate
boundaries at four United States latitudes, so the declared growth grid preserves these
fixture boundaries exactly.

Measured individual polygon areas are explicit inputs to the exact model, rounded to
integer millionths of a square meter. Comparisons allow 0.0001 square meters for input
quantization and binary64 arithmetic. These conformance checks establish collection
filtering and cumulative policy on the sampled geometries; they do not independently
establish the accuracy of the WGS84 surface integral. Ordinary numerical regressions
exercise its rectangle references, edge splitting, winding, holes, latitude range, and
raw longitude/latitude edge interpretation.

The numerical growth backend applies fixed-precision overlay. Even segments with lattice
endpoints can intersect off the lattice, and snapping the intersection can change their
point sets. The existing `Geography` and `DifferentialRows` proofs remain ideal set-policy
guarantees. Neither those proofs nor this weighted-cell model prove arbitrary GEOS
overlays, snap-rounding refinement, a universal boundary error, quadrature accuracy, or
floating-point monotonicity. Real-library regressions retain the confirmed hole-filling
and line-contribution failures. A valid GEOS result alone does not establish its
agreement with the intended operands.

## Coordinate quantization and query envelope conversion

`PeriScribe/CoordinateQuantization.lean` has nine theorems covering
`spatial_data.point_store.encode_longitude`, `encode_latitude`, `quantize_centroids`,
and `encoded_box`, with a conformance connection through `point_counts_within`.

The executable algorithm rounds an exact signed rational to the nearest integer, with
even-integer ties. Euclidean division handles negative ties. The proofs establish the
half-tick error bound, fixed integral coordinates, both even and odd tie cases, and
preservation of any stored integer point enclosed by lower/upper rational bounds. Valid
geographic coordinates stay within their encoded limits, and valid coordinates and
offset intermediates fit signed 32-bit storage.

`conformance/test_coordinate_quantization.py` covers 16,121 distinct longitude values
and 8,561 latitude values, including both binary64 neighbors of half ticks, integral
ticks, every half-degree tile boundary, signed zero, world endpoints, and seeded
interior values. Padding the shorter axis with zero yields 32,242 scalar comparisons
against the actual vectorized NumPy encoding and Lean's exact rational algorithm. The
oracle receives `as_integer_ratio()` of the actual binary64 scaled value, separating the
proved rounding operation from the unproved floating-point multiplication.

A real SQLite point store retains 170 point records, including duplicates, and is
queried with 1,530 very narrow, one-sided, and half-tick envelopes. All four encoded
bounds are compared with Lean. Each decoded stored point enclosed by the floating-point
bounds must survive the integer envelope filter. Actual database counts must equal
exhaustive GEOS containment over the decoded point bag; strict polygon-boundary
exclusion and duplicate multiplicity remain observable.

This establishes exact rational rounding and conservative ideal envelopes, with bounded
numerical evidence for the binary64 adapters. It does not prove IEEE-754 multiplication,
NumPy, SQLite, or GEOS. Inputs are finite valid WGS84 centroids; malformed, nonfinite,
or out-of-range ingestion remains an upstream validation responsibility. Queries may
extend slightly outside the world domain. Rounding can move a raw centroid across a
polygon boundary: the contract concerns decoded stored coordinates, not preservation of
every unquantized centroid's polygon membership.

No production defect was found by these additions.
