"""Describing a fire's location relative to the nearest reference place.

The reports identify each fire's location by the city whose point lies closest to the
fire's mapped area: the nearest city names the location, and the location phrase reads
the distance and direction from that city to the fire, like ``15 mi ESE of Portland,
OR``. A fire with a mapped perimeter is measured to its interior — the area bounded by
its latest perimeter — rather than to its point, so a fire that reaches a city reads as
0 miles from that city. Distances from cities outside the mapped area are measured to
its nearest edge. A fire with only a point location is measured from that point instead.

Each candidate city is measured in an azimuthal equidistant projection centered on that
city. Radial distances use the geodesic metric; projected polygon segments and candidate
pruning retain the numerical assumptions described in the design note. The search uses
a centroid-distance bound based on vertex radius plus a fixed margin, then chooses the
nearest measured candidate with deterministic ties.

Design notes:
[Nearest place descriptions](../../../docs/algorithms/nearest-place.md).
"""

from __future__ import annotations

import dataclasses
import math
import typing

import numpy as np
import pyproj
import shapely
import shapely.ops

import spatial_data.geometry
import spatial_data.reference
from measurement_units import units


if typing.TYPE_CHECKING:
    import geopandas
    import pint


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
COMPASS_POINT_SPAN = 360.0 * units.degrees / len(COMPASS_POINT_NAMES)

# Add this allowance to the greatest boundary-vertex distance from the centroid before
# screening candidate cities. Edges can extend farther than their vertices, and distance
# calculations have numerical error. This fixed margin allows for those effects but is
# not a proven bound for arbitrary geometry; the design note explains that limitation.
CENTROID_DISTANCE_MARGIN = 1_000.0 * units.meters


@dataclasses.dataclass(frozen=True, kw_only=True)
class NearestCity:
    """Keep the nearest city's name, distance, and direction together.

    Distance is measured from the city's point to the fire's mapped interior, or to its
    point when no interior is available. A city on or inside the mapped area has
    distance zero. The bearing points toward the nearest part of the fire, in degrees
    clockwise from north. It's None for a city on or inside the area because there's no
    single direction toward the fire.
    """

    name: str
    state_abbreviation: str
    distance: pint.Quantity[float]
    bearing: pint.Quantity[float] | None = None


def compass_point(bearing: pint.Quantity[float]) -> str:
    """Return the 16-wind compass point nearest to *bearing*.

    A bearing is measured in degrees clockwise from north, so 0 and 360 are north, 90 is
    east, 180 is south, and 270 is west. Each compass point spans the 22.5 degrees
    centered on its named bearing, and the naming wraps around past north.

    Args:
        bearing: The bearing to name.

    Returns:
        The nearest compass point, like ``ESE``.

    Examples:
        >>> compass_point(0 * units.degrees)
        'N'

        >>> compass_point(90 * units.degrees)
        'E'

        >>> compass_point(112.5 * units.degrees)
        'ESE'

        >>> compass_point(359 * units.degrees)
        'N'
    """
    degrees = bearing.m_as("degrees")
    return COMPASS_POINT_NAMES[
        round(degrees / COMPASS_POINT_SPAN.m_as("degrees")) % len(COMPASS_POINT_NAMES)
    ]


def location_text(city: NearestCity) -> str:
    """Return a location phrase such as ``15 mi ESE of Portland, OR``.

    Distance is rounded to the nearest whole mile and paired with a compass direction,
    so readers can place the fire relative to the named city and state. A city on or
    inside the mapped area has no single direction toward the fire, so the phrase shows
    zero miles and the city name without a direction.

    Args:
        city: The nearest city and its distance and direction facts.

    Returns:
        The location phrase.

    Examples:
        >>> location_text(
        ...     NearestCity(
        ...         name="Portland",
        ...         state_abbreviation="OR",
        ...         distance=14.6 * units.miles,
        ...         bearing=112.5 * units.degrees,
        ...     )
        ... )
        '15 mi ESE of Portland, OR'

        >>> location_text(
        ...     NearestCity(
        ...         name="Portland", state_abbreviation="OR", distance=0 * units.miles
        ...     )
        ... )
        '0 mi from Portland, OR'
    """
    place = f"{city.name}, {city.state_abbreviation}"
    if city.bearing is None:
        return f"0 mi from {place}"
    miles = round(city.distance.m_as("miles"))
    return f"{miles} mi {compass_point(city.bearing)} of {place}"


def azimuthal_equidistant_projection(
    centered_longitude: float,
    centered_latitude: float,
) -> pyproj.CRS:
    """Return the azimuthal equidistant projection centered on the given point.

    The projection preserves geodesic distances and directions from its center: every
    transformed point's radial distance and direction use the geodesic metric.
    Polygon edges between transformed vertices remain straight projected segments;
    their approximation limits are described in the module's design note.

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
) -> tuple[pint.Quantity[float], pint.Quantity[float] | None]:
    """Estimate distance and bearing from one point to the geometry.

    The distance is measured to the geometry itself — a fire's interior or its point
    location — so a point inside or on the geometry is at distance zero and has no one
    nearest part to bear toward. The measurement is made in the azimuthal equidistant
    projection centered on the point. Its radial metric is geodesic, while the geometry
    uses straight segments between transformed vertices and floating-point operations.

    Args:
        geometry: The fire's interior or point geometry, in WGS 84 degrees.
        longitude: The point's longitude, in degrees.
        latitude: The point's latitude, in degrees.

    Returns:
        The projected estimate of geodesic distance, zero when the point lies
        inside or on it, and the bearing clockwise from north toward the nearest part of
        the geometry, or None when the point lies inside.
    """
    projection = azimuthal_equidistant_projection(longitude, latitude)
    transformer = pyproj.Transformer.from_crs(
        spatial_data.reference.WGS84_SPATIAL_REFERENCE,
        projection,
        always_xy=True,
    )
    projected_interior = spatial_data.geometry.transform_coordinates(
        geometry,
        transformer,
    )
    projected_longitude, projected_latitude = transformer.transform(longitude, latitude)
    projected_point = shapely.Point(projected_longitude, projected_latitude)
    if shapely.intersects(projected_point, projected_interior):
        return 0 * units.meters, None
    distance = shapely.distance(projected_point, projected_interior) * units.meters
    nearest = shapely.ops.nearest_points(projected_point, projected_interior)[1]
    bearing = (
        math.degrees(
            math.atan2(nearest.x - projected_longitude, nearest.y - projected_latitude),
        )
        * units.degrees
    )
    return distance, bearing % (360 * units.degrees)


def plausible_city_indices(
    geometry: shapely.Geometry,
    city_longitudes: np.ndarray,
    city_latitudes: np.ndarray,
    city_names: list[str],
    state_abbreviations: list[str],
) -> list[int]:
    """Return the indices of the cities that could be nearest to *geometry*.

    Cities are screened by geodesic distance from the geometry's centroid before the
    more expensive projected comparison. The triangle-inequality argument requires a
    radius enclosing every point of the geometry. This implementation uses maximum
    boundary-vertex distance plus a fixed margin; its sufficiency for arbitrary curved
    or extreme geometries is not established. See the design note for the conditional
    bound and numerical assumptions. Point geometry has zero vertex radius.

    Args:
        geometry: The fire's interior or point geometry, in WGS 84 degrees.
        city_longitudes: Each city's longitude, in degrees.
        city_latitudes: Each city's latitude, in degrees.
        city_names: Each city's name, aligned with the coordinate arrays.
        state_abbreviations: Each city's state abbreviation, aligned with the coordinate
            arrays.

    Returns:
        The index of each plausible city, ordered by name and state so equal distances
        resolve deterministically.
    """
    geodesic = pyproj.Geod(ellps="WGS84")
    centroid = geometry.centroid
    vertex_coordinates = shapely.get_coordinates(geometry.boundary)
    if len(vertex_coordinates) == 0:
        interior_radius = 0 * units.meters
    else:
        _, _, vertex_distances = geodesic.inv(
            np.full(len(vertex_coordinates), centroid.x),
            np.full(len(vertex_coordinates), centroid.y),
            vertex_coordinates[:, 0],
            vertex_coordinates[:, 1],
        )
        interior_radius = float(vertex_distances.max()) * units.meters
    _, _, centroid_distances = geodesic.inv(
        np.full(len(city_longitudes), centroid.x),
        np.full(len(city_latitudes), centroid.y),
        city_longitudes,
        city_latitudes,
    )
    plausible_radius = interior_radius + CENTROID_DISTANCE_MARGIN
    candidate_mask = centroid_distances <= (
        centroid_distances.min() + 2.0 * plausible_radius.m_as("meters")
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
    point geometry in WGS 84 degrees. Rows missing any of those or carrying empty
    geometries are ignored. Distances are measured only for plausible candidates
    (see :func:`plausible_city_indices`). When several cities tie for nearest, the first
    alphabetically by name and state wins, so the choice is stable.

    Args:
        geometry: The fire's interior or point geometry, in WGS 84 degrees.
        cities: The populated places to choose among.

    Returns:
        The nearest city and its distance and direction facts, or None when *cities*
        holds no usable city.
    """
    if cities.empty:
        return None
    valid = cities[
        cities["NAME"].notna()
        & cities["STATE_ABBR"].notna()
        & (cities.geometry.geom_type == "Point")
        & ~cities.geometry.is_empty
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
    nearest_distance = math.inf * units.meters
    for index in candidate_indices:
        distance, bearing = distance_and_bearing_from_point(
            geometry,
            city_longitudes[index],
            city_latitudes[index],
        )
        if distance < nearest_distance:
            nearest_distance = distance
            nearest = NearestCity(
                name=city_names[index],
                state_abbreviation=state_abbreviations[index],
                distance=distance,
                bearing=bearing,
            )
    return nearest
