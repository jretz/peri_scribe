# Reconstructing the interstate border and classification box

## Contract and assessment

The classification boundary is derived from California and its three neighboring U.S.
state polygons in WGS84 degree coordinates. Output includes one shared interstate border
per neighbor with geodesic length, and an ordered border path closed offshore and south
of California into a classification polygon. This regional boundary supports a feed
preference within nationwide fire processing; it is not a national inclusion boundary.

The input state layer must contain exactly California, Arizona, Nevada, and Oregon,
with nonmissing geometry. Construction raises `AdministrativeBoundariesError` when the
expected states or a single usable border path cannot be established. Source retrieval
and atomic file publication are described in [external refresh](external-source-refresh.md).

| Dimension | Score | Concrete reason |
| --- | --- | --- |
| History and state | 1 | Path traversal carries the preceding segment and current snapped vertex. |
| Rule interaction | 2 | Intersection tolerance, collapsed segments, graph degree, endpoint selection, and complete traversal must agree. |
| Mathematical reasoning | 2 | Approximate geometric alignment becomes an undirected graph, then a polygon with explicit closure assumptions. |
| Scale and representation | 2 | Snapped adjacency keys identify corners while original coordinates determine the returned path. |
| Failure and concurrency | 0 | Geometry construction operates on supplied in-memory data. |

**Involved, total 7.** A malformed boundary could alter source preference, so failure
conditions and approximation limits are part of its policy contract.

## Shared border and graph construction

For each neighbor, intersect California's boundary with both the original neighbor
polygon and its buffer of `10⁻⁵` degrees. Keep the candidate with the greatest summed
planar line length. Extract line components recursively; points cannot establish a
shared border. This deliberately tolerates slight misalignment between state copies,
but can extend a shared boundary near its ends. Measure the retained lines geodesically
on WGS84 for reported kilometers, rounded to two decimal places.

The three border polylines can meet only approximately, so exact `line_merge` would
leave disconnected pieces. Split them into individual consecutive-coordinate segments.
Round each endpoint to four decimal places for its adjacency key, and drop segments
whose endpoints collapse to the same key. Retain original coordinates for the output.
Snapping defines an equivalence relation by rounding cells; it does not mean all points
within a fixed Euclidean distance are merged.

For example, these original endpoints share a rounded adjacency key:

| Endpoint | Original coordinates | Rounded key |
| --- | --- | --- |
| A, end of one segment | `(−120.00003°, 39.00002°)` | `(−120.0000°, 39.0000°)` |
| B, start of the next segment | `(−120.00002°, 39.00003°)` | `(−120.0000°, 39.0000°)` |

Their incident segments therefore meet at one degree-two graph vertex even though the
original coordinates differ.

Create undirected adjacency lists and require exactly two odd-degree vertices and no
vertex of degree greater than two. Choose the westernmost odd endpoint and walk forward,
excluding the segment just traversed. In an accepted path, every interior vertex has
degree two and the endpoints degree one, so there is one continuation at each step.
Reject unless the output contains exactly one more coordinate than retained segments.
This final coverage check catches a disconnected cycle that degree checks alone permit.

For example, path A–B–C plus disconnected cycle D–E–F–D has two odd endpoints and maximum
degree two, yet walking from A never reaches the cycle. The coordinate-count check rejects
it. A branch at B fails the degree check. A complete closed loop has no odd endpoint and
fails before traversal. Choosing a geographically nearest next segment instead would
hide these malformed topologies by inventing connections.

## Polygon closure and assumptions

![The ordered border closes outside California's southern and western extent](assets/border-closure.svg)

*The retained path runs from the Pacific/Oregon end to the Mexico/Arizona end. The added
southern and offshore edges close a classification box that deliberately absorbs ocean
and Mexico-side area. The schematic is not a legal state-boundary map or to scale.*

Append points from the southeast endpoint due south to latitude 31°, due west to
longitude −126°, due north to the northwest endpoint's latitude, then back to that
endpoint. The closure avoids treating the coast or international border as the interstate
boundary relevant to FIRIS-versus-WFIGS preference. Downstream
[geometry policy](perimeter-geometry-policy.md) projects this polygon before measuring
inside/outside fractions.

The geographic interpretation assumes the westernmost path endpoint is the
Pacific/Oregon corner, the other is the Mexico/Arizona corner, the offshore/southern
constants lie beyond the intended state extent, and the path is geometrically usable.
Graph acceptance alone proves none of these geographic facts or polygon validity.
Crossing lines without a shared vertex, inaccurate source polygons, excessive rounding
collisions, or closure that intersects the path remain geometry/source limitations.
Rounding can join very close points on opposite sides of a rounding boundary differently;
there is no universal meter tolerance at every latitude. The approximate join can replace
a tiny gap with the transition between retained original coordinates.

## Costs and verification

For V retained source coordinates, graph assembly, traversal, and the coverage check
use O(V) time and memory after geometric intersection. Intersections and buffering depend
on vertex and intersection counts; geodesic length visits retained line coordinates.
There is no all-pairs endpoint search. Input segment multiplicity matters: duplicate
edges can raise degrees and cause a valid-looking shape to be rejected as an invalid
path representation.

Owner: [border construction](../../src/peri_scribe/sources/borders.py).
[Ordinary tests](../../tests/tests/standard/peri_scribe/sources/test_borders.py) and
[property-based tests](../../tests/tests/property_based/peri_scribe/sources/test_borders.py)
exercise extraction, ordering, snapping, degenerate segments, invalid graphs, and closure.
The [border-classification proof](../../tests/formal/lean/perimeter_composition.md)
assumes supplied boundary geometry; it does not prove this construction or source truth.
No dedicated formal construction model currently covers the snapped graph and geographic
closure. This note records existing behavior; changing that contract requires the
[formal design assessment](../formal_verification.md#design-before-implementation).
