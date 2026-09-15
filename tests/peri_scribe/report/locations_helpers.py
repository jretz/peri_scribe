"""Provide data builders and stand-ins for locations tests."""

from __future__ import annotations

import geopandas
import pyproj
import shapely

from peri_scribe.units import units


GEODESIC = pyproj.Geod(ellps="WGS84")


PORTLAND_LONGITUDE = -122.6750


PORTLAND_LATITUDE = 45.5051


def city_frame(
    rows: list[tuple[str | None, str | None, tuple[float, float] | None]],
) -> geopandas.GeoDataFrame:
    """Build a major-cities frame from (name, state, coordinates) rows.

    A row whose name, state, or coordinates are None holds that missing value, so tests
    can exercise the filtering of unusable rows.

    Args:
        rows: The city name, state abbreviation, and point coordinates of each row.

    Returns:
        The rows as a GeoDataFrame in WGS 84.
    """
    return geopandas.GeoDataFrame(
        {
            "NAME": [name for name, _state, _coordinates in rows],
            "STATE_ABBR": [state for _name, state, _coordinates in rows],
            "geometry": [
                None if coordinates is None else shapely.Point(coordinates)
                for _name, _state, coordinates in rows
            ],
        },
        crs="EPSG:4326",
    )


def geodesic_quad(
    longitude: float,
    latitude: float,
    bearing: float,
    distance: float,
    *,
    length: float,
    width_in_miles: float,
) -> shapely.Geometry:
    """Return a quad whose nearest corner sits at a known geodesic distance and bearing.

    The quad's first corner lies exactly *distance* miles from the point at *bearing*,
    and the quad extends away along that bearing and perpendicular to it, so the corner
    is the point of the quad nearest to the given point.

    Args:
        longitude: The point's longitude, in degrees.
        latitude: The point's latitude, in degrees.
        bearing: The bearing toward the quad's nearest corner.
        distance: The distance to the quad's nearest corner.
        length: How far the quad extends along the bearing.
        width_in_miles: How far the quad extends to the right of the bearing.

    Returns:
        The quad polygon, in WGS 84 degrees.
    """
    corner_longitude, corner_latitude, _ = GEODESIC.fwd(
        longitude,
        latitude,
        bearing,
        (distance * units.miles).m_as("meters"),
    )
    first = (corner_longitude, corner_latitude)
    second = GEODESIC.fwd(
        first[0],
        first[1],
        bearing,
        (length * units.miles).m_as("meters"),
    )[:2]
    third = GEODESIC.fwd(
        second[0],
        second[1],
        bearing + 90.0,
        (width_in_miles * units.miles).m_as("meters"),
    )[:2]
    fourth = GEODESIC.fwd(
        first[0],
        first[1],
        bearing + 90.0,
        (width_in_miles * units.miles).m_as("meters"),
    )[:2]
    return shapely.Polygon([first, second, third, fourth])
