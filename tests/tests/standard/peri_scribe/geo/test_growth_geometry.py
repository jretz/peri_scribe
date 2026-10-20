"""Tests for the fixed-precision polygonal growth representation."""

import collections.abc

import pytest
import shapely

import peri_scribe.geo.growth_geometry
import tests.helpers.factories.peri_scribe.geo.growth_geometry


@pytest.mark.parametrize(
    "geometry",
    [
        None,
        shapely.Polygon(),
        shapely.Point(0, 0),
        shapely.LineString([(0, 0), (1, 1), (1, 0)]),
        shapely.LinearRing([(0, 0), (1, 1), (1, 0)]),
        shapely.GeometryCollection([shapely.Point(0, 0)]),
    ],
)
def test_polygonal_returns_none_without_polygonal_ground(
    geometry: shapely.Geometry | None,
) -> None:
    assert peri_scribe.geo.growth_geometry.polygonal(geometry) is None


@pytest.mark.parametrize(
    "geometry",
    [
        shapely.box(0, 0, 1, 1),
        shapely.MultiPolygon([shapely.box(0, 0, 1, 1), shapely.box(2, 0, 3, 1)]),
    ],
)
def test_polygonal_keeps_polygonal_geometry(geometry: shapely.Geometry) -> None:
    assert peri_scribe.geo.growth_geometry.polygonal(geometry) is geometry


def test_polygonal_extracts_nested_members_and_merges_overlap() -> None:
    geometry = shapely.GeometryCollection([
        shapely.GeometryCollection([shapely.box(0, 0, 2, 1), shapely.Point(3, 4)]),
        shapely.box(1, 0, 3, 1),
        shapely.LineString([(0, 0), (1, 1), (1, 0)]),
    ])

    result = peri_scribe.geo.growth_geometry.polygonal(geometry)

    assert result is not None
    assert result.equals(shapely.box(0, 0, 3, 1))


def test_normalize_attaches_exact_binary_grid_and_is_idempotent() -> None:
    geometry = shapely.box(-120.123456789, 44.987654321, -120.12, 45.0)

    result = peri_scribe.geo.growth_geometry.normalize(geometry)

    assert result is not None
    grid = peri_scribe.geo.growth_geometry.GRID_SIZE.m_as("degrees")
    assert shapely.get_precision(result) == grid
    assert all(
        float(value / grid).is_integer()
        for coordinate in shapely.get_coordinates(result)
        for value in coordinate
    )
    assert peri_scribe.geo.growth_geometry.normalize(result) is result


def test_normalize_removes_subgrid_area_collapse() -> None:
    grid = peri_scribe.geo.growth_geometry.GRID_SIZE.m_as("degrees")

    assert (
        peri_scribe.geo.growth_geometry.normalize(
            shapely.box(0, 0, grid / 4, grid / 4),
        )
        is None
    )


@pytest.mark.parametrize(
    ("left", "right"),
    [(None, None), (None, shapely.Point(0, 0)), (shapely.Point(0, 0), None)],
)
def test_union_returns_none_without_polygonal_ground(
    left: shapely.Geometry | None,
    right: shapely.Geometry | None,
) -> None:
    assert peri_scribe.geo.growth_geometry.union(left, right) is None


@pytest.mark.parametrize("reverse", [False, True])
def test_union_keeps_present_polygonal_ground(*, reverse: bool) -> None:
    geometry = shapely.box(0, 0, 1, 1)
    operands = (geometry, None) if reverse else (None, geometry)

    result = peri_scribe.geo.growth_geometry.union(*operands)

    assert result is not None
    assert result.equals(geometry)


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        (peri_scribe.geo.growth_geometry.union, shapely.box(0, 0, 3, 1)),
        (peri_scribe.geo.growth_geometry.intersection, shapely.box(1, 0, 2, 1)),
        (peri_scribe.geo.growth_geometry.difference, shapely.box(0, 0, 1, 1)),
    ],
)
def test_overlay_matches_axis_aligned_ground(
    operation: collections.abc.Callable[
        [shapely.Geometry | None, shapely.Geometry | None],
        shapely.Geometry | None,
    ],
    expected: shapely.Geometry,
) -> None:
    result = operation(shapely.box(0, 0, 2, 1), shapely.box(1, 0, 3, 1))

    assert result is not None
    assert result.is_valid
    assert result.equals(expected)


@pytest.mark.parametrize("reverse", [False, True])
def test_intersection_requires_both_operands(*, reverse: bool) -> None:
    operands = (shapely.box(0, 0, 1, 1), None)
    if reverse:
        operands = tuple(reversed(operands))

    assert peri_scribe.geo.growth_geometry.intersection(*operands) is None


def test_intersection_discards_shared_line() -> None:
    assert (
        peri_scribe.geo.growth_geometry.intersection(
            shapely.box(0, 0, 1, 1),
            shapely.box(1, 0, 2, 1),
        )
        is None
    )


def test_difference_requires_current_ground() -> None:
    assert (
        peri_scribe.geo.growth_geometry.difference(
            None,
            shapely.box(0, 0, 1, 1),
        )
        is None
    )


def test_difference_keeps_ground_without_predecessor() -> None:
    geometry = shapely.box(0, 0, 1, 1)

    result = peri_scribe.geo.growth_geometry.difference(geometry, None)

    assert result is not None
    assert result.equals(geometry)


@pytest.mark.parametrize(
    ("case", "witness"),
    [
        (
            "0432",
            (-120.764, 44.971),
        ),
        (
            "minimal",
            (-120.764, 44.9692),
        ),
        (
            "hagen",
            (-118.27129150642986, 45.69025150042522),
        ),
    ],
)
def test_union_preserves_unburned_hole_at_saved_failure(
    case: str,
    witness: tuple[float, float],
) -> None:
    left, right = (
        tests.helpers.factories.peri_scribe.geo.growth_geometry.hole_union_operands(
            case,
        )
    )
    point = shapely.Point(witness)
    assert left.is_valid
    assert right.is_valid
    assert not left.covers(point)
    assert not right.covers(point)

    result = peri_scribe.geo.growth_geometry.union(left, right)

    assert result is not None
    assert result.is_valid
    assert not result.covers(point)
