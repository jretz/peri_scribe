"""Tests for spatial_data.centroid_math."""

from __future__ import annotations

import pytest

import spatial_data.centroid_math
import spatial_data.centroid_streaming
import tests.helpers.factories.spatial_data.centroid_streaming
import tests.helpers.reference.spatial_data.centroid_streaming


def test_polygon_centroids_match_reference() -> None:
    geometries = [
        tests.helpers.factories.spatial_data.centroid_streaming.SQUARE,
        tests.helpers.factories.spatial_data.centroid_streaming.SQUARE_WITH_HOLE,
        tests.helpers.factories.spatial_data.centroid_streaming.MULTIPOLYGON,
        tests.helpers.factories.spatial_data.centroid_streaming.CLOCKWISE_SQUARE,
    ]
    chunk = spatial_data.centroid_streaming.collect_geometry_chunk(
        tests.helpers.factories.spatial_data.centroid_streaming.geometry_features(
            geometries,
        ),
        10,
        100,
    )
    assert chunk is not None
    centroids = spatial_data.centroid_math.polygon_centroids(chunk)
    for centroid, geometry in zip(centroids, geometries, strict=True):
        expected_x, expected_y = (
            tests.helpers.reference.spatial_data.centroid_streaming.reference_centroid(
                geometry,
            )
        )
        assert centroid[0] == pytest.approx(expected_x, abs=1e-9)
        assert centroid[1] == pytest.approx(expected_y, abs=1e-9)


def test_polygon_centroids_fall_back_to_mean_vertex_for_zero_area() -> None:
    degenerate: dict[str, object] = (
        tests.helpers.factories.spatial_data.centroid_streaming.polygon([
            [[30, 30], [31, 30], [32, 30], [30, 30]],
        ])
    )
    chunk = spatial_data.centroid_streaming.collect_geometry_chunk(
        tests.helpers.factories.spatial_data.centroid_streaming.geometry_features([
            degenerate,
        ]),
        10,
        100,
    )
    assert chunk is not None
    centroids = spatial_data.centroid_math.polygon_centroids(chunk)
    # The zero-area ring's shoelace sums are zero, so the fallback mean vertex is used:
    # the mean of the four ring points.
    assert centroids[0] == pytest.approx([30.75, 30.0], abs=1e-6)
