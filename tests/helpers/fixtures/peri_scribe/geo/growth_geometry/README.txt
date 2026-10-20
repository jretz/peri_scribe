These operands preserve valid-input union failures observed in saved 2026 growth rings
with GEOS 3.15.0. They contain geographic perimeter coordinates, without fire attributes.

0432-left.wkt and 0432-right.wkt are the original cumulative footprint and next ring.
Their floating-precision union fills an existing hole of about 77 acres.

minimal-left.wkt and minimal-right.wkt retain the failure with a triangular exterior,
a five-vertex hole, and two triangular slivers.

hagen-left.wkb and hagen-right.wkb preserve a separate failure involving an existing
hole of about 158 acres. The left operand includes lower-dimensional overlay remnants.
Binary storage keeps this larger real regression bounded without rounding coordinates.

Regressions assert hole membership and valid polygonal output independently of whether
another GEOS release still exhibits the original floating-precision failure.
