# Building footprint centroids from streamed archives

## Contract and assessment

Building archives contain WGS84 longitude/latitude Polygon or MultiPolygon features.
The converter preserves every accepted feature in source order, including duplicates,
and emits one WGS84 point per feature. Unsupported geometry types are skipped. Rings
must be complete and closed, with the exterior first and holes afterward in each part.
The centroid is an area-weighted **Web Mercator** centroid transformed back to WGS84;
it is neither a geodesic centroid nor a guarantee that the point lies inside its footprint.

| Dimension | Score | Reason |
| --- | --- | --- |
| History and state | 1 | A single iterator and chunk counters retain stream position. |
| Rule interaction | 2 | Ring winding, exterior/hole position, multipart aggregation, and degenerate fallback interact. |
| Mathematical reasoning | 3 | Translated shoelace moments avoid cancellation at large projected coordinates. |
| Scale and representation | 3 | Incremental ZIP/JSON consumption and packed coordinate arrays avoid whole-archive materialization. |
| Failure and concurrency | 1 | Conversion reports stream failures; the enclosing download owner handles worker lifetime and publication. |

**Complex: 10.** Count fidelity matters to building-based fire scores. Concurrent archive
construction and its publication contract are documented in
[Compact point storage](compact-point-storage.md).

## Streaming without splitting a feature

One `ijson` iterator supplies all chunks; restarting a parser on a partially consumed
stream would lose its parsing state. Every ZIP member is exhausted before advancing,
including ignored members. Geometry collection stops after accepting a complete feature
when either the 100,000-feature limit or 2,000,000-vertex threshold is reached. The
threshold is checked **after** the feature: a single giant footprint can exceed it.
Coordinates accumulate as packed doubles with ring boundaries and part ownership arrays.

For example, these three accepted features produce two chunks:

| Feature in source order | Vertices | Chunk and boundary decision |
| --- | --- | --- |
| F1 | 0.8 million | Starts chunk 1. |
| F2 | 1.4 million, including holes | Stays in chunk 1, which now has 2.2 million vertices and closes. |
| F3 | Next complete feature | Starts chunk 2. |

Neither a hole nor a multipart component of F2 moves to the next chunk. Chunking
preserves source order and duplicates.

## Why translated moments are necessary

For a ring, translate vertices by its first point `o`, giving `q_i = p_i - o`.
Let `d_i = q_ix q_(i+1)y - q_(i+1)x q_iy`, `D = Σ d_i`, and
`N = Σ (q_i + q_(i+1)) d_i`. Its centroid is `N / (3D) + o`.
To combine rings independently of winding, retain `|D|` and
`sign(D) N + 3 |D| o`. Add exterior contributions and subtract hole contributions.
Sum those quantities across parts, then divide total numerator by three times total
double area. This restores offsets before combining differently positioned rings.

![Courtyard size and position change the building centroid](assets/centroid-moments.svg)

*The animation enlarges the courtyard at a fixed center, moving the remaining building's
centroid farther in the opposite direction. It then slides the courtyard across the
building at constant area, so the centroid moves the other way. The exterior and its
center stay fixed. Three labeled comparisons show both effects without motion, including
in reduced motion. The courtyard stays inside the building, but the resulting centroid
can lie in the courtyard.*

The off-center hole removes mass on the right, moving the centroid left. Winding alone
cannot identify a hole: positional ring ownership determines its negative contribution.

Large EPSG:3857 coordinates are roughly ten million meters; multiplying them directly
and subtracting nearby products can erase the area of a small building. Translation
shrinks the products while preserving the exact mathematical result. The alternative
of constructing a GEOS object for every footprint is simpler but adds object and
serialization costs to the national stream. The vectorized path keeps ring ownership
explicit and batches projection and reductions.

## Worked example and boundaries

A stepped building exterior starts with a projected rectangle from `(-1,0)` to `(11,10)`
and recesses each of its four corners by `2 × 2.5` units. Its area is `120 - 4×5 = 100`,
and its symmetry keeps the centroid at `(5,5)`. Remove a courtyard from `(6,4)` to
`(8,6)`, area 4 and centroid `(7,5)`.
The result is `((100×5 - 4×7)/96, (100×5 - 4×5)/96) = (4.916667,5)`.
Reversing either ring must leave that answer unchanged. Adding an independent part of
area 24 centered at `(20,5)` yields `(7.933333,5)` for the complete feature.

If the final division produces a nonfinite coordinate, the implementation uses the mean
of all recorded projected vertices, including repeated closing vertices. It does not
switch to a line-length-weighted centroid. Open, empty, invalid, nonfinite, polar, or
antimeridian-crossing input is not repaired by this calculation; projection and geometry
validity remain upstream assumptions. A centroid can fall in a hole or outside a concave
polygon even when the calculation is correct.

## Costs and verification

For `V` vertices, `R` rings, `P` parts, and `F` accepted features, collection and the
vectorized reductions take O(V + R + P + F) work, excluding library projection costs.
Working arrays are proportional to one collected chunk. The vertex threshold is not an
unconditional memory bound: one final feature may be arbitrarily large, and the parser
already holds that feature's decoded JSON. Int32 segment indexes also require actual
chunk sizes to remain within their representable domain.

Implementation: [centroid_streaming.py](../../src/spatial_data/centroid_streaming.py),
[centroid_math.py](../../src/spatial_data/centroid_math.py), and
[centroid_data.py](../../src/spatial_data/centroid_data.py).
Ordinary tests cover [streaming](../../tests/tests/standard/spatial_data/test_centroid_streaming.py)
and [numerics](../../tests/tests/standard/spatial_data/test_centroid_math.py), with generated
[math](../../tests/tests/property_based/spatial_data/test_centroid_math.py) and
[chunk](../../tests/tests/property_based/spatial_data/test_centroid_streaming.py) cases.

[BuildingCentroids](../../tests/formal/lean/centroids_monitor.md) proves exact moment
translation, winding normalization, hole subtraction, multipart combination, fallback,
and preservation through greedy splitting. The
[conformance tests](../../tests/formal/conformance/test_building_centroids.py) connect
integer projected examples and real ZIP/GDAL conversions to those definitions. The proof
does not bound floating-point error or establish PROJ, ZIP, JSON, or GDAL correctness;
its inventory records the numerical tolerances and supported finite examples.
