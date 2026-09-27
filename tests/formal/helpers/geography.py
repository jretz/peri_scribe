"""Realize finite sets as disjoint exact-coordinate polygons for conformance."""

import shapely


CELL_COUNT = 4


def footprint(mask: int) -> shapely.Geometry:
    """Separate cells so shared boundaries cannot create spurious intersection area.

    Args:
        mask: Four-bit cell membership transported by the Lean oracle.

    Returns:
        A planar polygonal footprint with exactly the selected unit-square cells.
    """
    return shapely.union_all([
        shapely.box(2 * cell, 0, 2 * cell + 1, 1)
        for cell in range(CELL_COUNT)
        if mask & (1 << cell)
    ])


def assert_corrected(
    corrected: list[shapely.Geometry | None],
    expected: tuple[int, ...],
) -> None:
    """Check whole footprints rather than only areas or sampled point membership.

    Args:
        corrected: Actual footprints returned by the production GEOS operations.
        expected: Exact cell sets returned by the checked Lean recurrence.
    """
    assert len(corrected) == len(expected)
    for actual, mask in zip(corrected, expected, strict=True):
        if mask == 0:
            assert actual is None or actual.is_empty
        else:
            assert actual is not None
            assert actual.equals(footprint(mask)), (actual, mask)
