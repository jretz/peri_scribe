"""Tests for peri_scribe.perimeter_cleaning."""

import pytest
import shapely.geometry

import peri_scribe.perimeter_cleaning


def noisy_top_edge_polygon() -> shapely.geometry.Polygon:
    """Return a square whose top edge carries many small wiggles.

    The wiggles are far smaller than the cleaning deviation but far larger than the
    collinear epsilon, so they exercise the slit-killing simplification rather than the
    collinear removal alone.

    Returns:
        The noisy square.
    """
    points = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
    for index in range(99, 0, -1):
        x = index / 100.0
        y = 1.0 + (0.00001 if index % 2 == 0 else -0.00001)
        points.append((x, y))
    points.extend(((0.0, 1.0), (0.0, 0.0)))
    return shapely.geometry.Polygon(points)


def test_clean_perimeter_returns_none_for_missing() -> None:
    assert peri_scribe.perimeter_cleaning.clean_perimeter(None) is None


def test_clean_perimeter_keeps_empty_polygon() -> None:
    result = peri_scribe.perimeter_cleaning.clean_perimeter(
        shapely.geometry.Polygon(),
    )
    assert result is not None
    assert result.is_empty


def test_clean_perimeter_passes_non_polygonal_geometry_through() -> None:
    line = shapely.geometry.LineString([(0.0, 0.0), (1.0, 1.0)])
    assert peri_scribe.perimeter_cleaning.clean_perimeter(line) is line


def test_clean_perimeter_removes_zero_area_parts() -> None:
    box = shapely.geometry.box(0.0, 0.0, 1.0, 1.0)
    sliver = shapely.geometry.Polygon(
        [(5.0, 5.0), (6.0, 5.0), (7.0, 5.0), (5.0, 5.0)],
    )
    result = peri_scribe.perimeter_cleaning.clean_perimeter(
        shapely.geometry.MultiPolygon([box, sliver]),
    )
    assert result is not None
    assert result.equals(box)


def test_clean_perimeter_removes_degenerate_holes() -> None:
    polygon = shapely.geometry.Polygon(
        [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)],
        [[(4.0, 4.0), (5.0, 4.0), (6.0, 4.0), (4.0, 4.0)]],
    )
    result = peri_scribe.perimeter_cleaning.clean_perimeter(polygon)
    assert result is not None
    assert len(result.interiors) == 0
    assert result.area == pytest.approx(100.0)


def test_clean_perimeter_keeps_real_holes() -> None:
    polygon = shapely.geometry.Polygon(
        [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)],
        [[(4.0, 4.0), (6.0, 4.0), (6.0, 6.0), (4.0, 6.0), (4.0, 4.0)]],
    )
    result = peri_scribe.perimeter_cleaning.clean_perimeter(polygon)
    assert result is not None
    assert len(result.interiors) == 1
    assert result.area == pytest.approx(100.0 - 4.0)


def test_clean_perimeter_keeps_multiple_parts() -> None:
    first = shapely.geometry.box(0.0, 0.0, 1.0, 1.0)
    second = shapely.geometry.box(2.0, 2.0, 3.0, 3.0)
    result = peri_scribe.perimeter_cleaning.clean_perimeter(
        shapely.geometry.MultiPolygon([first, second]),
    )
    assert result is not None
    assert result.equals(shapely.geometry.MultiPolygon([first, second]))


def test_clean_perimeter_keeps_close_parts_from_overlapping() -> None:
    notched = shapely.geometry.Polygon(
        [
            (0.0, 0.0),
            (1.0, 0.0),
            (1.0, 0.4),
            (0.9999, 0.4),
            (0.9999, 0.6),
            (1.0, 0.6),
            (1.0, 1.0),
            (0.0, 1.0),
            (0.0, 0.0),
        ],
    )
    neighbor = shapely.geometry.box(0.99995, 0.45, 0.99999, 0.55)
    polygon = shapely.geometry.MultiPolygon([notched, neighbor])
    assert polygon.is_valid
    result = peri_scribe.perimeter_cleaning.clean_perimeter(polygon)
    assert result is not None
    assert result.is_valid
    assert result.area == pytest.approx(polygon.area, rel=1e-3)


def test_clean_perimeter_removes_collinear_points() -> None:
    polygon = shapely.geometry.Polygon(
        [(0.0, 0.0), (0.5, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)],
    )
    result = peri_scribe.perimeter_cleaning.clean_perimeter(polygon)
    assert result is not None
    assert len(result.exterior.coords) < len(polygon.exterior.coords)
    assert result.area == pytest.approx(polygon.area)


def test_clean_perimeter_removes_collinear_points_without_deviation() -> None:
    config = peri_scribe.perimeter_cleaning.PerimeterCleaningConfig(
        maximum_deviation_in_meters=0.0,
    )
    polygon = shapely.geometry.Polygon(
        [(0.0, 0.0), (0.5, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)],
    )
    result = peri_scribe.perimeter_cleaning.clean_perimeter(polygon, config)
    assert result is not None
    assert len(result.exterior.coords) < len(polygon.exterior.coords)


def test_clean_perimeter_simplifies_noisy_ring() -> None:
    polygon = noisy_top_edge_polygon()
    result = peri_scribe.perimeter_cleaning.clean_perimeter(polygon)
    assert result is not None
    assert len(result.exterior.coords) < len(polygon.exterior.coords)
    assert result.area == pytest.approx(polygon.area, rel=1e-3)


def test_clean_perimeter_makes_invalid_polygon_valid() -> None:
    polygon = shapely.geometry.Polygon(
        [
            (0.0, 0.0),
            (4.0, 0.0),
            (4.0, 2.0),
            (2.0, 2.0),
            (2.0, 1.0),
            (3.0, 1.0),
            (3.0, 4.0),
            (0.0, 4.0),
            (0.0, 0.0),
        ],
    )
    assert not polygon.is_valid
    result = peri_scribe.perimeter_cleaning.clean_perimeter(polygon)
    assert result is not None
    assert result.is_valid


def test_clean_perimeter_keeps_geometry_when_everything_is_below_area_floor() -> None:
    config = peri_scribe.perimeter_cleaning.PerimeterCleaningConfig(
        minimum_part_area_in_square_degrees=100.0,
    )
    box = shapely.geometry.box(0.0, 0.0, 1.0, 1.0)
    result = peri_scribe.perimeter_cleaning.clean_perimeter(box, config)
    assert result is box


def test_clean_perimeter_is_idempotent() -> None:
    polygon = noisy_top_edge_polygon()
    cleaned = peri_scribe.perimeter_cleaning.clean_perimeter(polygon)
    assert cleaned is not None
    result = peri_scribe.perimeter_cleaning.clean_perimeter(cleaned)
    assert result is not None
    assert result.equals(cleaned)


def test_polygonal_parts_flattens_multipolygon() -> None:
    first = shapely.geometry.box(0.0, 0.0, 1.0, 1.0)
    second = shapely.geometry.box(2.0, 2.0, 3.0, 3.0)
    parts = peri_scribe.perimeter_cleaning.polygonal_parts(
        shapely.geometry.MultiPolygon([first, second]),
    )
    assert parts == [first, second]


def test_polygonal_parts_flattens_nested_multipolygon() -> None:
    first = shapely.geometry.box(0.0, 0.0, 1.0, 1.0)
    second = shapely.geometry.box(2.0, 2.0, 3.0, 3.0)
    collection = shapely.geometry.GeometryCollection(
        [shapely.geometry.MultiPolygon([first, second])],
    )
    parts = peri_scribe.perimeter_cleaning.polygonal_parts(collection)
    assert parts == [first, second]


def test_polygonal_parts_skips_empty_members() -> None:
    box = shapely.geometry.box(0.0, 0.0, 1.0, 1.0)
    collection = shapely.geometry.GeometryCollection(
        [shapely.geometry.Polygon(), box],
    )
    parts = peri_scribe.perimeter_cleaning.polygonal_parts(collection)
    assert parts == [box]


def test_polygonal_parts_ignores_non_polygonal_members() -> None:
    box = shapely.geometry.box(0.0, 0.0, 1.0, 1.0)
    collection = shapely.geometry.GeometryCollection(
        [box, shapely.geometry.Point(5.0, 5.0)],
    )
    parts = peri_scribe.perimeter_cleaning.polygonal_parts(collection)
    assert parts == [box]


def test_polygonal_parts_returns_empty_for_line() -> None:
    line = shapely.geometry.LineString([(0.0, 0.0), (1.0, 1.0)])
    assert peri_scribe.perimeter_cleaning.polygonal_parts(line) == []


def test_simplify_tolerance_in_degrees_floors_at_collinear_epsilon() -> None:
    config = peri_scribe.perimeter_cleaning.PerimeterCleaningConfig(
        collinear_epsilon_in_degrees=1e-6,
        maximum_deviation_in_meters=0.0,
    )
    geometry = shapely.geometry.box(0.0, 0.0, 1.0, 1.0)
    tolerance = peri_scribe.perimeter_cleaning.simplify_tolerance_in_degrees(
        geometry,
        config,
    )
    assert tolerance == pytest.approx(1e-6)
