"""Tests for peri_scribe.fires.centroid_math."""

from __future__ import annotations

import hypothesis
import hypothesis.strategies
import numpy as np
import pytest
import shapely
import shapely.geometry

import peri_scribe.fires.centroid_math
import peri_scribe.fires.centroid_streaming
import tests.geometry_strategies
import tests.peri_scribe.fires.centroid_math_helpers
import tests.peri_scribe.fires.centroid_streaming_helpers


# This test is slow, so limit examples to keep routine test runs fast.
@hypothesis.settings(max_examples=25)
@hypothesis.given(
    geometries=hypothesis.strategies.lists(
        tests.geometry_strategies.footprints(),
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
    actual = tests.peri_scribe.fires.centroid_math_helpers.centroids(
        geometries,
        chunk_size,
        maximum_vertices,
    )
    expected = [
        tests.peri_scribe.fires.centroid_streaming_helpers.reference_centroid(
            shapely.geometry.mapping(geometry),
        )
        for geometry in geometries
    ]
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-8)


def test_polygon_centroids_match_reference() -> None:
    geometries = [
        tests.peri_scribe.fires.centroid_streaming_helpers.SQUARE,
        tests.peri_scribe.fires.centroid_streaming_helpers.SQUARE_WITH_HOLE,
        tests.peri_scribe.fires.centroid_streaming_helpers.MULTIPOLYGON,
        tests.peri_scribe.fires.centroid_streaming_helpers.CLOCKWISE_SQUARE,
    ]
    chunk = peri_scribe.fires.centroid_streaming.collect_geometry_chunk(
        tests.peri_scribe.fires.centroid_streaming_helpers.geometry_features(
            geometries,
        ),
        10,
        100,
    )
    assert chunk is not None
    centroids = peri_scribe.fires.centroid_math.polygon_centroids(chunk)
    for centroid, geometry in zip(centroids, geometries, strict=True):
        expected_x, expected_y = (
            tests.peri_scribe.fires.centroid_streaming_helpers.reference_centroid(
                geometry,
            )
        )
        assert centroid[0] == pytest.approx(expected_x, abs=1e-9)
        assert centroid[1] == pytest.approx(expected_y, abs=1e-9)


def test_polygon_centroids_fall_back_to_mean_vertex_for_zero_area() -> None:
    degenerate: dict[str, object] = (
        tests.peri_scribe.fires.centroid_streaming_helpers.polygon([
            [[30, 30], [31, 30], [32, 30], [30, 30]],
        ])
    )
    chunk = peri_scribe.fires.centroid_streaming.collect_geometry_chunk(
        tests.peri_scribe.fires.centroid_streaming_helpers.geometry_features([
            degenerate,
        ]),
        10,
        100,
    )
    assert chunk is not None
    centroids = peri_scribe.fires.centroid_math.polygon_centroids(chunk)
    # The zero-area ring's shoelace sums are zero, so the fallback mean vertex is used:
    # the mean of the four ring points.
    assert centroids[0] == pytest.approx([30.75, 30.0], abs=1e-6)
