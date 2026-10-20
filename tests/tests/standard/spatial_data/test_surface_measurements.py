"""Regression and independent-reference checks for straight-edge surface area."""

import math
import unittest.mock

import numpy as np
import pytest
import shapely

import spatial_data.measurements
import spatial_data.surface_measurements
import tests.helpers.reference.spatial_data.surface_measurements
from measurement_units import units


@pytest.mark.parametrize(
    "text",
    [
        "POLYGON EMPTY",
        "MULTIPOLYGON EMPTY",
        "GEOMETRYCOLLECTION EMPTY",
        "POINT EMPTY",
        "POINT (-100 40)",
        "MULTIPOINT ((-100 40), (-99 41))",
        "LINESTRING EMPTY",
        "LINESTRING (-100 40, -99 41, -98 40)",
        "LINEARRING (-100 40, -99 41, -98 40, -100 40)",
        "MULTILINESTRING ((-100 40, -99 41, -98 40), (0 0, 1 1, 2 0))",
    ],
)
def test_area_lower_dimensional_and_empty_geometries_are_zero(text: str) -> None:
    assert spatial_data.surface_measurements.area(shapely.from_wkt(text)) == (
        0 * units.Unit("meters ** 2")
    )


@pytest.mark.parametrize(
    "text",
    [
        "POLYGON ((-100 40, -99 40, -99 41, -100 41, -100 40))",
        "POLYGON ((-165 70, -164 70, -164 71, -165 71, -165 70))",
        "POLYGON ((-156 19, -155 19, -155 20, -156 20, -156 19))",
        "POLYGON ((-100 -0.5, -99 -0.5, -99 0.5, -100 0.5, -100 -0.5))",
        "POLYGON ((-170 89, -160 89, -160 90, -170 90, -170 89))",
        "POLYGON ((-170 -90, -160 -90, -160 -89, -170 -89, -170 -90))",
        "POLYGON ((-179 50, 179 50, 179 51, -179 51, -179 50))",
        "POLYGON ((-170 -80, 170 60, -160 75, -170 -80))",
        "POLYGON ((-170 40, 170 80, -160 85, -170 40))",
        "POLYGON ((-170 -90, 170 89, -160 50, -170 -90))",
        "POLYGON ((-120.7 44.9, -120.6 45, -120.6000000001 45, -120.7 44.9))",
        "POLYGON Z ((-100 40 1, -99 40 2, -99 41 3, -100 41 4, -100 40 1))",
        (
            "POLYGON ((-100 40, -100 41, -99 41, -99 40, -100 40),"
            "(-99.9 40.1, -99.9 40.2, -99.8 40.2, -99.8 40.1, -99.9 40.1),"
            "(-99.7 40.1, -99.6 40.1, -99.6 40.2, -99.7 40.2, -99.7 40.1))"
        ),
        (
            "MULTIPOLYGON (((179 50, 180 50, 180 51, 179 51, 179 50)),"
            "((-180 50, -179 50, -179 51, -180 51, -180 50)))"
        ),
        (
            "GEOMETRYCOLLECTION (POLYGON EMPTY, POINT (-100 40),"
            "GEOMETRYCOLLECTION (LINESTRING (-100 40, -99 41, -98 40),"
            "POLYGON ((-100 40, -99 40, -99 41, -100 41, -100 40))))"
        ),
    ],
)
def test_area_agrees_with_independent_surface_integral(text: str) -> None:
    geometry = shapely.from_wkt(text)
    expected = tests.helpers.reference.spatial_data.surface_measurements.area(geometry)
    actual = spatial_data.surface_measurements.area(geometry).m_as("meters ** 2")
    assert actual == pytest.approx(expected, rel=8e-15, abs=0.00001)


def test_area_ignores_open_and_closed_line_contributions() -> None:
    polygon = shapely.box(-100, 40, -99, 41)
    path = [(-121, 40), (-120.5, 40), (-120, 40)]
    geometry = shapely.GeometryCollection([
        polygon,
        shapely.LineString(path),
        shapely.LineString([*path, path[0]]),
        shapely.LineString(path[::-1]),
        shapely.GeometryCollection([shapely.Point(-120, 40), shapely.LinearRing(path)]),
    ])
    assert spatial_data.surface_measurements.area(geometry) == (
        spatial_data.surface_measurements.area(polygon)
    )


def test_area_is_invariant_under_collinear_horizontal_edge_vertices() -> None:
    polygon = shapely.box(-100, 40, -99, 41)
    divided = shapely.Polygon([
        (-100, 40),
        (-99.5, 40),
        (-99, 40),
        (-99, 41),
        (-99.5, 41),
        (-100, 41),
    ])
    assert polygon.equals(divided)
    assert spatial_data.surface_measurements.area(divided) == (
        spatial_data.surface_measurements.area(polygon)
    )
    assert abs(
        spatial_data.measurements.area(divided)
        - spatial_data.measurements.area(polygon),
    ) > 47_000 * units.Unit("meters ** 2")


def test_area_subtracts_holes_and_adds_parts_independent_of_winding() -> None:
    shell = shapely.box(-100, 40, -99, 41)
    hole = shapely.box(-99.9, 40.1, -99.8, 40.2)
    polygon = shapely.Polygon(shell.exterior, [hole.exterior])
    second = shapely.reverse(shapely.box(-98, 40, -97, 41))
    geometry = shapely.MultiPolygon([polygon, second])
    expected = (
        spatial_data.surface_measurements.area(shell)
        - spatial_data.surface_measurements.area(hole)
        + spatial_data.surface_measurements.area(second)
    )
    assert spatial_data.surface_measurements.area(geometry).m_as(
        "meters ** 2",
    ) == pytest.approx(expected.m_as("meters ** 2"), rel=8e-15, abs=0.00001)


def test_ring_area_reverses_sign() -> None:
    ring = shapely.box(-100, 40, -99, 41).exterior
    assert spatial_data.surface_measurements.ring_area(shapely.reverse(ring)) == (
        -spatial_data.surface_measurements.ring_area(ring)
    )


def test_latitude_primitive_difference_is_zero_at_reference() -> None:
    actual = spatial_data.surface_measurements.latitude_primitive_difference(
        np.array([0.0]) * units.degrees,
        40 * units.degrees,
    )
    assert actual.m_as("meters ** 2").tolist() == [0.0]


def test_ring_area_empty_boundary_is_zero() -> None:
    assert spatial_data.surface_measurements.ring_area(shapely.LinearRing()) == (
        0 * units.Unit("meters ** 2")
    )


def test_ring_area_vertical_boundary_is_zero() -> None:
    ring = shapely.LinearRing([(-100, 40), (-100, 41), (-100, 42), (-100, 40)])
    assert spatial_data.surface_measurements.ring_area(ring) == (
        0 * units.Unit("meters ** 2")
    )


@pytest.mark.parametrize("batch_size", [1, 3, 7])
def test_area_is_bitwise_invariant_across_integration_batch_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    batch_size: int,
) -> None:
    geometry = shapely.GeometryCollection([
        shapely.Polygon([(-120, 40), (-119, 45), (-121, 44)]),
        shapely.GeometryCollection([
            shapely.box(-100, 40, -99, 41),
            shapely.box(-98, 40, -97, 41),
        ]),
    ])
    expected = float(
        spatial_data.surface_measurements.area(geometry).m_as("meters ** 2"),
    )
    monkeypatch.setattr(
        spatial_data.surface_measurements,
        "MAXIMUM_INTEGRATION_BATCH_PIECES",
        batch_size,
    )
    primitive = unittest.mock.Mock(
        wraps=spatial_data.surface_measurements.primitive_difference_with_reference_values,
    )
    monkeypatch.setattr(
        spatial_data.surface_measurements,
        "primitive_difference_with_reference_values",
        primitive,
    )
    actual = float(spatial_data.surface_measurements.area(geometry).m_as("meters ** 2"))
    assert actual.hex() == expected.hex()
    assert len(primitive.call_args_list) > 1
    assert all(len(call.args[0]) <= batch_size for call in primitive.call_args_list)


def test_ring_areas_match_individual_boundaries_for_many_small_components() -> None:
    polygons = [
        shapely.box(-100 + index / 100, 40, -99.999 + index / 100, 40.001)
        for index in range(257)
    ]
    expected = math.fsum(
        spatial_data.surface_measurements.ring_area(polygon.exterior).m_as(
            "meters ** 2",
        )
        for polygon in polygons
    )
    actual = spatial_data.surface_measurements.area(shapely.MultiPolygon(polygons))
    assert float(actual.m_as("meters ** 2")).hex() == float(expected).hex()


def test_area_from_ring_areas_preserves_nested_collection_sum_boundaries() -> None:
    polygon = shapely.box(-100, 40, -99, 41)
    geometry = shapely.GeometryCollection([
        polygon,
        shapely.GeometryCollection([polygon, polygon]),
    ])
    measurements = iter([
        1.0 * units.Unit("meters ** 2"),
        2.0**53 * units.Unit("meters ** 2"),
        1.0 * units.Unit("meters ** 2"),
    ])
    actual = spatial_data.surface_measurements.area_from_ring_areas(
        geometry,
        measurements,
    )
    assert float(actual.m_as("meters ** 2")).hex() == float(2.0**53).hex()
    assert actual.m_as("meters ** 2") != math.fsum([1.0, 2.0**53, 1.0])
