"""Tests for spatial_data.centroid_math."""

from __future__ import annotations

import hypothesis
import hypothesis.strategies
import numpy as np
import shapely
import shapely.geometry

import tests.helpers.factories.spatial_data.centroid_math
import tests.helpers.reference.spatial_data.centroid_streaming
import tests.helpers.strategies.geometry


# This test is slow, so limit examples to keep routine test runs fast.
@hypothesis.settings(max_examples=25)
@hypothesis.given(
    geometries=hypothesis.strategies.lists(
        tests.helpers.strategies.geometry.footprints(),
        min_size=1,
        max_size=5,
    ),
    chunk_size=hypothesis.strategies.integers(1, 5),
    maximum_vertices=hypothesis.strategies.integers(1, 60),
)
def test_polygon_centroids_match_reference_across_generated_chunks(
    geometries: list[shapely.Polygon | shapely.MultiPolygon],
    chunk_size: int,
    maximum_vertices: int,
) -> None:
    actual = tests.helpers.factories.spatial_data.centroid_math.centroids(
        geometries,
        chunk_size,
        maximum_vertices,
    )
    expected = [
        tests.helpers.reference.spatial_data.centroid_streaming.reference_centroid(
            shapely.geometry.mapping(geometry),
        )
        for geometry in geometries
    ]
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-8)
