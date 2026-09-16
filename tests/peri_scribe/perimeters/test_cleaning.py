"""Tests for peri_scribe.perimeters.cleaning."""

import hypothesis
import pytest
import shapely.geometry

import peri_scribe.perimeters.cleaning
import tests.geometry_strategies
import tests.peri_scribe.perimeters.cleaning_helpers
from peri_scribe.units import units


@hypothesis.given(geometry=tests.geometry_strategies.footprints())
def test_clean_perimeter_preserves_valid_nonempty_footprints(
    geometry: shapely.Polygon | shapely.MultiPolygon,
) -> None:
    cleaned = peri_scribe.perimeters.cleaning.clean_perimeter(geometry)
    assert cleaned is not None
    assert cleaned.is_valid
    assert not cleaned.is_empty
    assert cleaned.area > 0


@hypothesis.given(geometry=tests.geometry_strategies.footprints())
def test_clean_perimeter_is_idempotent_for_generated_footprints(
    geometry: shapely.Polygon | shapely.MultiPolygon,
) -> None:
    cleaned = peri_scribe.perimeters.cleaning.clean_perimeter(geometry)
    repeated = peri_scribe.perimeters.cleaning.clean_perimeter(cleaned)
    assert cleaned is not None
    assert repeated is not None
    assert repeated.equals(cleaned)


def test_clean_perimeter_returns_none_for_missing() -> None:
    assert peri_scribe.perimeters.cleaning.clean_perimeter(None) is None


def test_clean_perimeter_keeps_empty_polygon() -> None:
    result = peri_scribe.perimeters.cleaning.clean_perimeter(shapely.geometry.Polygon())
    assert result is not None
    assert result.is_empty


def test_clean_perimeter_passes_non_polygonal_geometry_through() -> None:
    line = shapely.geometry.LineString([(0.0, 0.0), (1.0, 1.0)])
    assert peri_scribe.perimeters.cleaning.clean_perimeter(line) is line


def test_clean_perimeter_removes_zero_area_parts() -> None:
    box = shapely.geometry.box(0.0, 0.0, 1.0, 1.0)
    sliver = shapely.geometry.Polygon([(5.0, 5.0), (6.0, 5.0), (7.0, 5.0), (5.0, 5.0)])
    result = peri_scribe.perimeters.cleaning.clean_perimeter(
        shapely.geometry.MultiPolygon([box, sliver]),
    )
    assert result is not None
    assert result.equals(box)


def test_clean_perimeter_removes_degenerate_holes() -> None:
    polygon = shapely.geometry.Polygon(
        [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)],
        [[(4.0, 4.0), (5.0, 4.0), (6.0, 4.0), (4.0, 4.0)]],
    )
    result = peri_scribe.perimeters.cleaning.clean_perimeter(polygon)
    assert result is not None
    assert len(result.interiors) == 0
    assert result.area == pytest.approx(100.0)


def test_clean_perimeter_keeps_real_holes() -> None:
    polygon = shapely.geometry.Polygon(
        [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)],
        [[(4.0, 4.0), (6.0, 4.0), (6.0, 6.0), (4.0, 6.0), (4.0, 4.0)]],
    )
    result = peri_scribe.perimeters.cleaning.clean_perimeter(polygon)
    assert result is not None
    assert len(result.interiors) == 1
    assert result.area == pytest.approx(100.0 - 4.0)


def test_clean_perimeter_keeps_multiple_parts() -> None:
    first = shapely.geometry.box(0.0, 0.0, 1.0, 1.0)
    second = shapely.geometry.box(2.0, 2.0, 3.0, 3.0)
    result = peri_scribe.perimeters.cleaning.clean_perimeter(
        shapely.geometry.MultiPolygon([first, second]),
    )
    assert result is not None
    assert result.equals(shapely.geometry.MultiPolygon([first, second]))


def test_clean_perimeter_keeps_close_parts_from_overlapping() -> None:
    notched = shapely.geometry.Polygon([
        (0.0, 0.0),
        (1.0, 0.0),
        (1.0, 0.4),
        (0.9999, 0.4),
        (0.9999, 0.6),
        (1.0, 0.6),
        (1.0, 1.0),
        (0.0, 1.0),
        (0.0, 0.0),
    ])
    neighbor = shapely.geometry.box(0.99995, 0.45, 0.99999, 0.55)
    polygon = shapely.geometry.MultiPolygon([notched, neighbor])
    assert polygon.is_valid
    result = peri_scribe.perimeters.cleaning.clean_perimeter(polygon)
    assert result is not None
    assert result.is_valid
    assert result.area == pytest.approx(polygon.area, rel=1e-3)


def test_clean_perimeter_removes_collinear_points() -> None:
    polygon = shapely.geometry.Polygon([
        (0.0, 0.0),
        (0.5, 0.0),
        (1.0, 0.0),
        (1.0, 1.0),
        (0.0, 1.0),
        (0.0, 0.0),
    ])
    result = peri_scribe.perimeters.cleaning.clean_perimeter(polygon)
    assert result is not None
    assert len(result.exterior.coords) < len(polygon.exterior.coords)
    assert result.area == pytest.approx(polygon.area)


def test_clean_perimeter_removes_collinear_points_without_deviation() -> None:
    config = peri_scribe.perimeters.cleaning.PerimeterCleaningConfig(
        maximum_deviation=0.0 * units.meters,
    )
    polygon = shapely.geometry.Polygon([
        (0.0, 0.0),
        (0.5, 0.0),
        (1.0, 0.0),
        (1.0, 1.0),
        (0.0, 1.0),
        (0.0, 0.0),
    ])
    result = peri_scribe.perimeters.cleaning.clean_perimeter(polygon, config)
    assert result is not None
    assert len(result.exterior.coords) < len(polygon.exterior.coords)


def test_clean_perimeter_simplifies_noisy_ring() -> None:
    polygon = tests.peri_scribe.perimeters.cleaning_helpers.noisy_top_edge_polygon()
    result = peri_scribe.perimeters.cleaning.clean_perimeter(polygon)
    assert result is not None
    assert len(result.exterior.coords) < len(polygon.exterior.coords)
    assert result.area == pytest.approx(polygon.area, rel=1e-3)


def test_clean_perimeter_makes_invalid_polygon_valid() -> None:
    polygon = shapely.geometry.Polygon([
        (0.0, 0.0),
        (4.0, 0.0),
        (4.0, 2.0),
        (2.0, 2.0),
        (2.0, 1.0),
        (3.0, 1.0),
        (3.0, 4.0),
        (0.0, 4.0),
        (0.0, 0.0),
    ])
    assert not polygon.is_valid
    result = peri_scribe.perimeters.cleaning.clean_perimeter(polygon)
    assert result is not None
    assert result.is_valid


def test_clean_perimeter_keeps_geometry_when_everything_is_below_area_floor() -> None:
    config = peri_scribe.perimeters.cleaning.PerimeterCleaningConfig(
        minimum_part_area=100.0 * units.degrees**2,
    )
    box = shapely.geometry.box(0.0, 0.0, 1.0, 1.0)
    result = peri_scribe.perimeters.cleaning.clean_perimeter(box, config)
    assert result is box


def test_clean_perimeter_is_idempotent() -> None:
    polygon = tests.peri_scribe.perimeters.cleaning_helpers.noisy_top_edge_polygon()
    cleaned = peri_scribe.perimeters.cleaning.clean_perimeter(polygon)
    assert cleaned is not None
    result = peri_scribe.perimeters.cleaning.clean_perimeter(cleaned)
    assert result is not None
    assert result.equals(cleaned)


def test_simplify_tolerance_floors_at_collinear_epsilon() -> None:
    config = peri_scribe.perimeters.cleaning.PerimeterCleaningConfig(
        collinear_epsilon=1e-6 * units.degrees,
        maximum_deviation=0.0 * units.meters,
    )
    geometry = shapely.geometry.box(0.0, 0.0, 1.0, 1.0)
    tolerance = peri_scribe.perimeters.cleaning.simplify_tolerance(geometry, config)
    assert tolerance.m_as("degrees") == pytest.approx(1e-6)
