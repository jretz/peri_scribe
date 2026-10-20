"""Properties of the WGS84 measure beneath straight coordinate-plane edges."""

import hypothesis
import hypothesis.strategies
import pytest
import shapely

import spatial_data.surface_measurements
import tests.helpers.reference.spatial_data.surface_measurements
import tests.helpers.strategies.geometry


@hypothesis.given(geometry=tests.helpers.strategies.geometry.polygons())
def test_area_is_independent_of_ring_orientation(geometry: shapely.Polygon) -> None:
    assert spatial_data.surface_measurements.area(shapely.reverse(geometry)).m_as(
        "meters ** 2",
    ) == pytest.approx(
        spatial_data.surface_measurements.area(geometry).m_as("meters ** 2"),
        rel=2e-14,
        abs=0.0000001,
    )


@hypothesis.settings(max_examples=25)
@hypothesis.given(geometry=tests.helpers.strategies.geometry.polygons())
def test_area_agrees_with_independent_surface_integral(
    geometry: shapely.Polygon,
) -> None:
    expected = tests.helpers.reference.spatial_data.surface_measurements.area(geometry)
    assert spatial_data.surface_measurements.area(geometry).m_as(
        "meters ** 2",
    ) == pytest.approx(expected, rel=2e-14, abs=0.0000001)


@hypothesis.given(
    longitude=hypothesis.strategies.integers(-175, 170),
    latitude=hypothesis.strategies.integers(-85, 80),
    binary_scale=hypothesis.strategies.integers(1, 27),
)
def test_area_is_invariant_under_collinear_vertex_insertion(
    longitude: int,
    latitude: int,
    binary_scale: int,
) -> None:
    increment = 2.0**-binary_scale
    first = (longitude, latitude)
    second = (longitude + 3 * increment, latitude + increment)
    third = (longitude + increment, latitude + 3 * increment)
    midpoint = ((second[0] + third[0]) / 2, (second[1] + third[1]) / 2)
    geometry = shapely.Polygon([first, second, third])
    divided = shapely.Polygon([first, second, midpoint, third])
    assert geometry.equals(divided)
    assert spatial_data.surface_measurements.area(divided).m_as(
        "meters ** 2",
    ) == pytest.approx(
        spatial_data.surface_measurements.area(geometry).m_as("meters ** 2"),
        rel=2e-14,
        abs=0.0000001,
    )


@hypothesis.given(
    longitude=hypothesis.strategies.integers(-175, 170),
    latitude=hypothesis.strategies.integers(-85, 80),
    binary_scale=hypothesis.strategies.integers(1, 27),
)
def test_area_is_additive_across_planar_partitions(
    longitude: int,
    latitude: int,
    binary_scale: int,
) -> None:
    increment = 2.0**-binary_scale
    first = (longitude, latitude)
    second = (longitude + 3 * increment, latitude + increment)
    third = (longitude + increment, latitude + 3 * increment)
    midpoint = ((second[0] + third[0]) / 2, (second[1] + third[1]) / 2)
    polygon = shapely.Polygon([first, second, third])
    partitioned_area = spatial_data.surface_measurements.area(
        shapely.MultiPolygon([
            shapely.Polygon([first, second, midpoint]),
            shapely.Polygon([first, midpoint, third]),
        ]),
    )
    assert partitioned_area.m_as("meters ** 2") == pytest.approx(
        spatial_data.surface_measurements.area(polygon).m_as("meters ** 2"),
        rel=2e-14,
        abs=0.0000001,
    )
