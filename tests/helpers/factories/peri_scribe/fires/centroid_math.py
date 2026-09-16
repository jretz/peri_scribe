"""Build inputs for centroid math tests."""

from __future__ import annotations

import numpy as np
import shapely
import shapely.geometry

import peri_scribe.fires.centroid_math
import peri_scribe.fires.centroid_streaming
import tests.helpers.factories.peri_scribe.fires.centroid_streaming


def centroids(
    geometries: list[shapely.Polygon | shapely.MultiPolygon],
    chunk_size: int,
    maximum_vertices: int,
) -> np.ndarray:
    """Keep chunk boundaries independent of the expected geographic result.

    Args:
        geometries: Footprints to pass through the GeoJSON stream.
        chunk_size: The maximum feature count per chunk.
        maximum_vertices: The chunk's vertex budget.

    Returns:
        The centroid coordinate pairs in feature order.
    """
    features = (
        tests.helpers.factories.peri_scribe.fires.centroid_streaming.geometry_features([
            shapely.geometry.mapping(geometry) for geometry in geometries
        ])
    )
    results: list[np.ndarray] = []
    while (
        chunk := peri_scribe.fires.centroid_streaming.collect_geometry_chunk(
            features,
            chunk_size,
            maximum_vertices,
        )
    ) is not None:
        results.append(peri_scribe.fires.centroid_math.polygon_centroids(chunk))
    return np.concatenate(results)
