"""Compare classification behavior through reusable assertions."""

from __future__ import annotations

import shapely.affinity

from measurement_units import units


def assert_same_projected_coverage(
    actual: shapely.Geometry,
    expected: shapely.Geometry,
) -> None:
    """Compare coverage despite overlapping parts and overlay rounding differences.

    Args:
        actual: A projected union or an unmerged collection of observation geometries.
        expected: The complete reference union in the same meter-based projection.
    """
    merged = shapely.union_all([actual])
    # Overlay rounding can leave thin interior holes, so allow one micrometer of
    # coverage difference.
    tolerance = 1e-6 * units.meters
    assert expected.buffer(tolerance.m_as("meter")).covers(merged)
    assert merged.buffer(tolerance.m_as("meter")).covers(expected)
    assert merged.symmetric_difference(expected).area * units.Unit("meters ** 2") <= (
        (merged.length + expected.length) * units.meters * tolerance
    )
