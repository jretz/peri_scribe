"""Calculate independent expected results for centroid streaming tests."""

from __future__ import annotations

import geopandas
import shapely.geometry


def reference_centroid(geometry: dict[str, object]) -> tuple[float, float]:
    """Return the reference (GEOS, projected) centroid of *geometry*.

    The geometry is projected to EPSG:3857, its centroid is computed, and the centroid
    is projected back to WGS84, mirroring the conversion's algorithm.

    Args:
        geometry: The GeoJSON geometry dict.

    Returns:
        The centroid's longitude and latitude.
    """
    projected = geopandas.GeoDataFrame(
        geometry=[shapely.geometry.shape(geometry)],
        crs="EPSG:4326",
    ).to_crs(3857)
    centroid = (
        geopandas
        .GeoDataFrame(geometry=projected.geometry.centroid, crs=3857)
        .to_crs(4326)
        .geometry.iloc[0]
    )
    return centroid.x, centroid.y
