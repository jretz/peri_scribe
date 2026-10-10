# Nearest place descriptions

Location descriptions name the populated place nearest to the fire's mapped interior,
or to its incident point when no perimeter is available. All eligible U.S. places can
compete across state boundaries; population does not affect selection.

## Contract and assessment

Inputs are a usable WGS84 fire geometry and named point locations with state codes.
Output is a place, distance, and bearing, or no location when evidence is unusable.
Distances carry units. A place inside or on the fire has distance zero and no bearing.

| Dimension | Score | Reason |
| --- | --- | --- |
| History and state | 0 | Selection uses the supplied current geometry and places. |
| Rule interaction | 1 | Eligibility and deterministic tie rules are independent. |
| Mathematical reasoning | 3 | Candidate pruning depends on a geometric bound and local projections. |
| Scale and representation | 2 | A cheap vectorized filter limits expensive geometry projections. |
| Failure and concurrency | 0 | The selection computation has no external effects. |

Total **6: complex**, because mathematical reasoning scores 3.

## Candidate bound and exact candidate comparison

![Centroid distance bounds narrow the candidate places](assets/nearest-place-bound.svg)

The centroid is used to prune candidates. Final distance is measured to the fire's
interior, which can be much closer than its center.

Let `c` be the geometry centroid and `r` a radius containing the geometry in the
distance metric. If the closest place to `c` has distance `d0`, its distance to the
geometry is at most `d0 + r`. A place farther than `d0 + 2r` from `c` is farther than
`d0 + r` from every point of the geometry, by the triangle inequality. It therefore
cannot beat the centroid-nearest place. This argument assumes `r` really bounds the
complete geometry in the metric used.

The implementation estimates radius from geodesic distances to boundary vertices and
adds a 1,000-meter margin. It retains places within `d0 + 2 * (radius + margin)`.
That concrete vertex approximation and fixed margin are not an unbounded proof for
arbitrary geographic polygons or projection distortion. The implementation is intended
for fire-scale mapped geometries; the numerical contract must be revisited if that
domain changes.

For each remaining place, project the fire into an azimuthal equidistant CRS centered
on that place. Intersecting the projected place with the fire yields zero distance.
Otherwise find the nearest point on the projected geometry, measure distance, and use
`atan2(east, north)` for bearing. Convert to a compass direction for text. The CRS
preserves radial distance and direction from its center, while transformed straight
polygon segments and floating-point operations still impose numerical limits.

## Example, alternatives, and costs

![A nearby edge can change the winning place](assets/nearest-place-example.svg)

*The fire and places stay fixed while each solid distance line moves its endpoint from
the centroid to the nearest point in the fire. The bars track those changing lengths:
A is nearer the centroid, but B wins when distance is measured to the actual area. Both
endpoint comparisons remain visible below for static and reduced-motion viewing. The
transition explains the change in what is measured, not an iterative nearest-point
search. Values use planar schematic units; the code projects separately for each place.*

Place A is closest to the center, but place B is closest to the fire's eastern edge.
The candidate filter retains both so the final comparison can select B.

With `d0 = 10 km` and a true bounding radius `r = 4 km`, every possible winner is within
18 km of the centroid. A place at 15 km can still be only 11 km from the nearest edge;
choosing the center-nearest place without comparison would be unjustified. A place
inside the fire always has distance zero. Ties are resolved by case-folded place name,
state code, and original row order, with the first minimum retained.

For `P` places and `V` boundary vertices, pruning takes `O(P + V)` geodesic work and
arrays. The `K` retained places require `K` geometry transformations and nearest-point
operations; worst case `K = P`. Exhaustive comparison avoids pruning assumptions but
does all those projections. The source's place catalog limits which settlements can
be named; it does not establish that no closer real settlement exists.

## Implementation and verification

- [Location selection](../../src/peri_scribe/report/locations.py) and
  [city database](../../src/peri_scribe/sources/cities.py).
- [Location tests](../../tests/tests/standard/peri_scribe/report/test_locations.py)
  exercise concrete geometry and naming behavior.
- [Spatial proof boundaries](../../tests/formal/lean/spatial_boundaries.md) and
  [formal verification boundaries](../formal_verification.md#proof-boundaries) distinguish
  ideal geometry from projection and floating-point behavior. The pruning derivation
  above is conditional on a true radius bound; it is not presented as a proof of the
  fixed-margin implementation for every polygon.
