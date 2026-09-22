"""Shared coordinate systems keep geometry and storage operations consistent."""

import functools

import pyproj


WGS84_SPATIAL_REFERENCE_ID = 4326
NAD83_SPATIAL_REFERENCE_ID = 4269
CALIFORNIA_ALBERS_SPATIAL_REFERENCE_ID = 3310
WEB_MERCATOR_SPATIAL_REFERENCE_ID = 3857


@functools.cache
def spatial_reference_for_id(spatial_reference_id: int) -> pyproj.CRS:
    """Reuse parsed coordinate systems across repeated transformations.

    Args:
        spatial_reference_id: The EPSG identifier of the coordinate system.

    Returns:
        The coordinate reference system.
    """
    return pyproj.CRS.from_epsg(spatial_reference_id)


WGS84_SPATIAL_REFERENCE = spatial_reference_for_id(WGS84_SPATIAL_REFERENCE_ID)
WEB_MERCATOR_SPATIAL_REFERENCE = spatial_reference_for_id(
    WEB_MERCATOR_SPATIAL_REFERENCE_ID,
)
