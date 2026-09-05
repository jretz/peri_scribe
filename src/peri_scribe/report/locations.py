"""Describing a fire's location relative to the nearest major city.

The reports identify each fire's location by the city whose point lies closest to the
fire's mapped area: the nearest city names the location, and the location phrase reads
the distance and direction from that city to the fire, like ``15 mi ESE of Portland,
OR``. A fire with a mapped perimeter is measured to its interior — the area bounded by
its latest perimeter — rather than to its point, so a fire that reaches a city reads as
0 miles from that city, and a large fire reads from where it actually starts rather than
from its mapped center. A fire with only a point location is measured from that point
instead.

The distance is geodesic so it is accurate anywhere on Earth. Each candidate city is
measured in an azimuthal equidistant projection centered on that city, whose distances
from its center equal the true geodesic distances, so the projected distance and
direction equal the geodesic ones. The nearest city is chosen exactly among the cities
that could plausibly be nearest, found by bounding how far the nearest city can lie from
the interior's centroid.
"""

from __future__ import annotations

import dataclasses
import math
import typing

import numpy as np
import pyproj
import shapely
import shapely.ops

import peri_scribe.units


if typing.TYPE_CHECKING:
    import geopandas


# The 16 points of the compass in clockwise order from north, each spanning the 22.5
# degrees centered on its own bearing: N at 0 degrees, E at 90, S at 180, W at 270, with
# the intercardinal points and the half-winds between them.
COMPASS_POINT_NAMES: tuple[str, ...] = (
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSW",
    "SW",
    "WSW",
    "W",
    "WNW",
    "NW",
    "NNW",
)

# The width of one 16-wind compass point in degrees.
DEGREES_PER_COMPASS_POINT = 360.0 / len(COMPASS_POINT_NAMES)

# How far past the mapped area's measured extent a nearest city may lie. The candidate
# search keeps every city whose distance from the area's centroid is within twice this
# radius of the closest city's, and the radius is measured to the area's boundary
# vertices plus this margin, so the margin absorbs the small distance by which an edge's
# midpoint can reach beyond its vertices and the numerical noise of the measurements.
# The margin is far smaller than the spacing between cities, so it adds only cities that
# were plausible candidates anyway.
CENTROID_DISTANCE_MARGIN_IN_METERS = 1000.0


@dataclasses.dataclass(frozen=True, kw_only=True)
class NearestCity:
    """The city nearest to a fire's mapped area and the facts the location phrase needs.

    The mapped area is the fire's interior, or its point location when the fire has no
    interior. The distance is from the city's point to that area: zero when the city
    lies on or inside it. The bearing points from the city toward the nearest part of
    the area, measured in degrees clockwise from north; a city on or inside the area has
    no one nearest part, so its bearing is None.
    """

    name: str
    state_abbreviation: str
    distance_in_miles: float
    bearing_in_degrees: float | None = None


def compass_point(bearing_in_degrees: float) -> str:
    """Return the 16-wind compass point nearest to *bearing_in_degrees*.

    A bearing is measured in degrees clockwise from north, so 0 and 360 are north, 90
    is east, 180 is south, and 270 is west. Each compass point spans the 22.5 degrees
    centered on its named bearing, and the naming wraps around past north.

    Args:
        bearing_in_degrees: The bearing to name.

    Returns:
        The nearest compass point, like ``ESE``.

    Examples:
        >>> compass_point(0.0)
        'N'

        >>> compass_point(90.0)
        'E'

        >>> compass_point(112.5)
        'ESE'

        >>> compass_point(359.0)
        'N'
    """
    return COMPASS_POINT_NAMES[
        round(bearing_in_degrees / DEGREES_PER_COMPASS_POINT) % len(COMPASS_POINT_NAMES)
    ]


def location_text(city: NearestCity) -> str:
    """Return the location phrase naming *city*, like ``15 mi ESE of Portland, OR``.

    The distance is rounded to the nearest whole mile and leads the phrase, followed by
    the compass direction from the city to the fire and the city's name and state. A
    city on or inside the fire's mapped area is at zero distance and has no one
    direction, so its phrase names the city alone at zero miles.

    Args:
        city: The nearest city and its distance and direction facts.

    Returns:
        The location phrase.

    Examples:
        >>> location_text(
        ...     NearestCity(
        ...         name="Portland",
        ...         state_abbreviation="OR",
        ...         distance_in_miles=14.6,
        ...         bearing_in_degrees=112.5,
        ...     ),
        ... )
        '15 mi ESE of Portland, OR'

        >>> location_text(
        ...     NearestCity(
        ...         name="Portland",
        ...         state_abbreviation="OR",
        ...         distance_in_miles=0.0,
        ...     ),
        ... )
        '0 mi of Portland, OR'
    """
    place = f"{city.name}, {city.state_abbreviation}"
    if city.bearing_in_degrees is None:
        return f"0 mi of {place}"
    distance_in_miles = round(city.distance_in_miles)
    return f"{distance_in_miles} mi {compass_point(city.bearing_in_degrees)} of {place}"


def azimuthal_equidistant_projection(
    centered_longitude: float,
    centered_latitude: float,
) -> pyproj.CRS:
    """Return the azimuthal equidistant projection centered on the given point.

    The projection preserves geodesic distances and directions from its center: every
    point's distance from the center and the direction toward it in the projection equal
    the true geodesic distance and bearing. Measuring in this projection is therefore
    the exact way to measure one city's distance and direction to a fire's interior or
    point location.

    Args:
        centered_longitude: The projection center's longitude, in degrees.
        centered_latitude: The projection center's latitude, in degrees.

    Returns:
        The azimuthal equidistant CRS in meters, centered on the point.
    """
    return pyproj.CRS.from_proj4(
        f"+proj=aeqd +lat_0={centered_latitude} +lon_0={centered_longitude} "
        "+datum=WGS84 +units=m +no_defs",
    )


def distance_and_bearing_from_point(
    geometry: shapely.Geometry,
    longitude: float,
    latitude: float,
) -> tuple[float, float | None]:
    """Return the geometry's geodesic distance and bearing from one point.

    The distance is measured to the geometry itself — a fire's interior or its point
    location — so a point inside or on the geometry is at distance zero and has no one
    nearest part to bear toward. The measurement is made in the azimuthal equidistant
    projection centered on the point, whose distances and directions from its center are
    geodesically exact.

    Args:
        geometry: The fire's interior or point geometry, in WGS 84 degrees.
        longitude: The point's longitude, in degrees.
        latitude: The point's latitude, in degrees.

    Returns:
        The geodesic distance in miles from the point to the geometry, zero when the
        point lies inside or on it, and the bearing in degrees clockwise from north
        toward the nearest part of the geometry, or None when the point lies inside.
    """
    projection = azimuthal_equidistant_projection(longitude, latitude)
    transformer = pyproj.Transformer.from_crs(
        "EPSG:4326",
        projection,
        always_xy=True,
    )
    projected_interior = shapely.transform(
        geometry,
        lambda coordinates: np.column_stack(
            transformer.transform(
                coordinates[:, 0],
                coordinates[:, 1],
            ),
        ),
    )
    projected_longitude, projected_latitude = transformer.transform(
        longitude,
        latitude,
    )
    projected_point = shapely.Point(projected_longitude, projected_latitude)
    if shapely.intersects(projected_point, projected_interior):
        return 0.0, None
    distance_in_miles = (
        shapely.distance(projected_point, projected_interior)
        / peri_scribe.units.METERS_PER_MILE
    )
    nearest = shapely.ops.nearest_points(projected_point, projected_interior)[1]
    bearing_in_degrees = math.degrees(
        math.atan2(
            nearest.x - projected_longitude,
            nearest.y - projected_latitude,
        ),
    )
    return distance_in_miles, bearing_in_degrees % 360.0


def plausible_city_indices(
    geometry: shapely.Geometry,
    city_longitudes: np.ndarray,
    city_latitudes: np.ndarray,
    city_names: list[str],
    state_abbreviations: list[str],
) -> list[int]:
    """Return the indices of the cities that could be nearest to *geometry*.

    The exact distance to a city is measured in a projection centered on that city, so
    only the cities that could plausibly be nearest are measured. A city at the true
    minimum distance lies within twice the geometry's radius of the city closest to the
    geometry's centroid, because that radius bounds how far the nearest part of the
    geometry can be from the centroid; the radius is measured to the geometry's boundary
    vertices — zero for a point geometry — so cities are compared by geodesic distance
    from the centroid.

    Args:
        geometry: The fire's interior or point geometry, in WGS 84 degrees.
        city_longitudes: Each city's longitude, in degrees.
        city_latitudes: Each city's latitude, in degrees.
        city_names: Each city's name, aligned with the coordinate arrays.
        state_abbreviations: Each city's state abbreviation, aligned with the
            coordinate arrays.

    Returns:
        The index of each plausible city, ordered by name and state so equal distances
        resolve deterministically.
    """
    geod = pyproj.Geod(ellps="WGS84")
    centroid = geometry.centroid
    vertex_coordinates = shapely.get_coordinates(geometry.boundary)
    if len(vertex_coordinates) == 0:
        interior_radius_in_meters = 0.0
    else:
        _, _, vertex_distances_in_meters = geod.inv(
            np.full(len(vertex_coordinates), centroid.x),
            np.full(len(vertex_coordinates), centroid.y),
            vertex_coordinates[:, 0],
            vertex_coordinates[:, 1],
        )
        interior_radius_in_meters = float(vertex_distances_in_meters.max())
    _, _, centroid_distances_in_meters = geod.inv(
        np.full(len(city_longitudes), centroid.x),
        np.full(len(city_latitudes), centroid.y),
        city_longitudes,
        city_latitudes,
    )
    plausible_radius_in_meters = (
        interior_radius_in_meters + CENTROID_DISTANCE_MARGIN_IN_METERS
    )
    candidate_mask = centroid_distances_in_meters <= (
        centroid_distances_in_meters.min() + 2.0 * plausible_radius_in_meters
    )
    return sorted(
        np.nonzero(candidate_mask)[0],
        key=lambda index: (
            city_names[int(index)].casefold(),
            state_abbreviations[int(index)].casefold(),
            int(index),
        ),
    )


def nearest_city(
    geometry: shapely.Geometry,
    cities: geopandas.GeoDataFrame,
) -> NearestCity | None:
    """Return the city nearest to *geometry*, or None when no city can be named.

    Each row of *cities* names one city with ``NAME`` and ``STATE_ABBR`` columns and a
    point geometry in WGS 84 degrees. Rows missing any of those are ignored. The exact
    distances are measured only for the cities that could plausibly be nearest (see
    :func:`plausible_city_indices`), and when several cities tie for nearest, the first
    alphabetically by name and state wins, so the choice is stable.

    Args:
        geometry: The fire's interior or point geometry, in WGS 84 degrees.
        cities: The major cities to choose among.

    Returns:
        The nearest city and its distance and direction facts, or None when *cities*
        holds no usable city.
    """
    if cities.empty:
        return None
    valid = cities[
        cities["NAME"].notna()
        & cities["STATE_ABBR"].notna()
        & cities.geometry.notna()
        & (cities.geometry.geom_type == "Point")
    ]
    if valid.empty:
        return None
    city_names = [str(name) for name in valid["NAME"]]
    state_abbreviations = [str(state) for state in valid["STATE_ABBR"]]
    city_longitudes = valid.geometry.x.to_numpy(dtype=float)
    city_latitudes = valid.geometry.y.to_numpy(dtype=float)
    candidate_indices = plausible_city_indices(
        geometry,
        city_longitudes,
        city_latitudes,
        city_names,
        state_abbreviations,
    )

    nearest: NearestCity | None = None
    nearest_distance_in_miles = math.inf
    for index in candidate_indices:
        distance_in_miles, bearing_in_degrees = distance_and_bearing_from_point(
            geometry,
            city_longitudes[index],
            city_latitudes[index],
        )
        if distance_in_miles < nearest_distance_in_miles:
            nearest_distance_in_miles = distance_in_miles
            nearest = NearestCity(
                name=city_names[index],
                state_abbreviation=state_abbreviations[index],
                distance_in_miles=distance_in_miles,
                bearing_in_degrees=bearing_in_degrees,
            )
    return nearest
