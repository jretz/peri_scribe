"""Verify coordinate-reference selection against metadata and geometry."""

import operator

import hypothesis
import hypothesis.strategies
import shapely

import peri_scribe.geo.spatial_reference
import tests.helpers.strategies.geometry


@hypothesis.given(
    geometries=hypothesis.strategies.lists(
        hypothesis.strategies.one_of(
            hypothesis.strategies.none(),
            hypothesis.strategies.sampled_from([
                shapely.Point(),
                shapely.Polygon(),
                shapely.GeometryCollection(),
            ]),
            tests.helpers.strategies.geometry.footprints(),
            tests.helpers.strategies.geometry.nested_collections().map(
                operator.itemgetter(0),
            ),
        ),
        max_size=8,
    ),
)
def test_bounds_of_matches_extrema_of_all_present_coordinates(
    geometries: list[shapely.Geometry | None],
) -> None:
    coordinates = shapely.get_coordinates(geometries)
    if not len(coordinates):
        assert peri_scribe.geo.spatial_reference.bounds_of(geometries) is None
    else:
        longitudes = [point[0] for point in coordinates]
        latitudes = [point[1] for point in coordinates]
        assert peri_scribe.geo.spatial_reference.bounds_of(geometries) == (
            min(longitudes),
            max(longitudes),
            min(latitudes),
            max(latitudes),
        )
