"""Computing California border geometry and neighbor state borders."""

from __future__ import annotations

import collections
import itertools
import operator
import typing

import geopandas
import pyproj
import shapely
import structlog
import us

import peri_scribe.exceptions
import peri_scribe.geo.data
import peri_scribe.models
import peri_scribe.units


if typing.TYPE_CHECKING:
    import arcgis.features


logger = structlog.get_logger()


CALIFORNIA_WHERE_CLAUSE = "STATE_ABBR='CA'"


NEIGHBOR_WHERE_CLAUSE = "STATE_ABBR IN ('AZ','NV','OR')"


NEIGHBOR_COLUMN_NAME = "NEIGHBOR"


NEIGHBOR_ABBREVIATION_COLUMN_NAME = "NEIGHBOR_ABBR"


LENGTH_COLUMN_NAME = "LENGTH_KM"


INTERSECTION_TOLERANCE_DEGREES = 1e-5


NEIGHBOR_STATES = [us.states.AZ, us.states.NV, us.states.OR]


EXPECTED_FEATURE_COUNT = len(NEIGHBOR_STATES)


CALIFORNIA_BOX_SOUTHERN_LATITUDE = 31.0


CALIFORNIA_BOX_WESTERN_LONGITUDE = -126.0


BORDER_PATH_ENDPOINT_COUNT = 2


EXPECTED_COLUMNS = frozenset(
    {
        NEIGHBOR_COLUMN_NAME,
        NEIGHBOR_ABBREVIATION_COLUMN_NAME,
        LENGTH_COLUMN_NAME,
    },
)


def line_parts(geometry: shapely.Geometry) -> list[shapely.LineString]:
    """Return the LineStrings contained in *geometry*.

    Intersecting a boundary with a polygon can return a LineString, a MultiLineString,
    or a GeometryCollection mixing lines and points, so callers need the lines alone.

    Args:
        geometry: The geometry to decompose.

    Returns:
        The LineStrings contained in *geometry*.
    """
    geometry_type = geometry.geom_type
    if geometry_type == "LineString":
        return [] if geometry.is_empty else [geometry]
    if geometry_type == "MultiLineString":
        multi_line = typing.cast("shapely.MultiLineString", geometry)
        return list(multi_line.geoms)
    if geometry_type == "GeometryCollection":
        collection = typing.cast("shapely.GeometryCollection", geometry)
        return [
            part for contained in collection.geoms for part in line_parts(contained)
        ]
    return []


def total_line_length_in_degrees(geometry: shapely.Geometry) -> float:
    """Return the total planar length of the LineStrings in *geometry*, in degrees.

    Args:
        geometry: The geometry to measure.

    Returns:
        The summed planar length of the contained LineStrings, in degrees.
    """
    return sum(part.length for part in line_parts(geometry))


def shared_border(
    california_geometry: shapely.Geometry,
    neighbor_geometry: shapely.Geometry,
) -> shapely.Geometry:
    """Return the portion of California's boundary shared with *neighbor_geometry*.

    The boundary is intersected with the neighbor polygon, and with the neighbor grown
    by ``INTERSECTION_TOLERANCE_DEGREES``; the more complete result is kept so borders
    that line up only approximately between the two source copies are still captured.

    Args:
        california_geometry: California's polygon.
        neighbor_geometry: The neighboring state's polygon.

    Returns:
        The shared border as a LineString or MultiLineString.

    Raises:
        AdministrativeBoundariesError: If the geometries share no border.
    """
    california_boundary = california_geometry.boundary
    candidates = [
        california_boundary.intersection(neighbor_geometry),
        california_boundary.intersection(
            neighbor_geometry.buffer(INTERSECTION_TOLERANCE_DEGREES),
        ),
    ]
    best = max(candidates, key=total_line_length_in_degrees)
    parts = line_parts(best)
    if not parts:
        message = "California and its neighbor share no border"
        raise peri_scribe.exceptions.AdministrativeBoundariesError(message)
    if len(parts) == 1:
        return parts[0]
    return shapely.MultiLineString(parts)


def border_length_in_kilometers(geometry: shapely.Geometry) -> float:
    """Return the geodesic length of *geometry* in kilometers.

    Args:
        geometry: The border geometry to measure.

    Returns:
        The geodesic length in kilometers.
    """
    geod = pyproj.Geod(ellps="WGS84")
    return (
        sum(geod.geometry_length(part) for part in line_parts(geometry))
        / peri_scribe.units.METERS_PER_KILOMETER
    )


def layer_dataframe(
    layer: arcgis.features.FeatureLayer,
    layer_name: str,
    *,
    where: str,
) -> geopandas.GeoDataFrame:
    """Query *layer* and return its features as a GeoDataFrame in WGS84.

    The query requests the features re-projected to WGS 84 so the two sources can be
    intersected in one spatial reference. A layer that returns no features is an
    error, since no border can be computed from it.

    Args:
        layer: The layer to query.
        layer_name: Human-readable layer identifier for log messages.
        where: The SQL where clause selecting the features.

    Returns:
        The features as a GeoDataFrame in WGS84.

    Raises:
        AdministrativeBoundariesError: If the layer returns no features.
    """
    feature_set = peri_scribe.geo.data.query_with_retry(
        layer_name,
        layer,
        parameters={
            "where": where,
            "out_sr": peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID,
        },
    )
    if not feature_set.features:
        message = f"Layer {layer_name} returned no features; no border was computed"
        raise peri_scribe.exceptions.AdministrativeBoundariesError(message)
    dataframe, geometries, geometry_warning = peri_scribe.geo.data.extract_geometries(
        feature_set.sdf,
    )
    if geometry_warning is not None:
        logger.warning(geometry_warning)
    return peri_scribe.geo.data.geo_data_frame_from(
        dataframe,
        geometries,
        peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID,
    )


def california_geometry(layer: arcgis.features.FeatureLayer) -> shapely.Geometry:
    """Return California's boundary polygon from *layer*.

    Args:
        layer: The layer holding the California feature.

    Returns:
        California's polygon.

    Raises:
        AdministrativeBoundariesError: If the layer does not hold exactly one
            California feature with a geometry.
    """
    dataframe = layer_dataframe(
        layer,
        "California",
        where=CALIFORNIA_WHERE_CLAUSE,
    )
    if len(dataframe) != 1:
        message = f"Expected one California feature, got {len(dataframe)}"
        raise peri_scribe.exceptions.AdministrativeBoundariesError(message)
    geometry = dataframe.geometry.iloc[0]
    if geometry is None:
        message = "The California feature has no geometry"
        raise peri_scribe.exceptions.AdministrativeBoundariesError(message)
    return typing.cast("shapely.Geometry", geometry)


def neighbor_geometries(
    layer: arcgis.features.FeatureLayer,
) -> geopandas.GeoDataFrame:
    """Return the neighboring states' polygons from *layer*.

    Args:
        layer: The layer holding the state polygons.

    Returns:
        The Arizona, Nevada, and Oregon polygons as a GeoDataFrame in WGS84.

    Raises:
        AdministrativeBoundariesError: If the layer does not hold every expected
            neighbor, or a neighbor has no geometry.
    """
    dataframe = layer_dataframe(
        layer,
        "Neighboring states",
        where=NEIGHBOR_WHERE_CLAUSE,
    )
    if len(dataframe) != EXPECTED_FEATURE_COUNT:
        message = (
            f"Expected {EXPECTED_FEATURE_COUNT} neighboring states, "
            f"got {len(dataframe)}"
        )
        raise peri_scribe.exceptions.AdministrativeBoundariesError(message)
    if dataframe.geometry.isna().any():
        message = "A neighboring state feature has no geometry"
        raise peri_scribe.exceptions.AdministrativeBoundariesError(message)
    return dataframe


def border_dataframe(
    california_geometry: shapely.Geometry,
    neighbors: geopandas.GeoDataFrame,
) -> geopandas.GeoDataFrame:
    """Return the shared borders with each neighbor as a GeoDataFrame.

    Each row names the neighbor and gives the geodesic length of its shared border with
    California in kilometers. The geometry column is named
    ``peri_scribe.models.GEOMETRY_COLUMN_NAME`` so the layer matches the rest of the
    project's GeoPackage layers.

    Args:
        california_geometry: California's polygon.
        neighbors: The neighboring states' polygons.

    Returns:
        The shared borders as a GeoDataFrame in WGS84.
    """
    names: list[str] = []
    abbreviations: list[str] = []
    lengths_in_kilometers: list[float] = []
    borders: list[shapely.Geometry] = []
    for index in range(len(neighbors)):
        border = shared_border(
            california_geometry,
            neighbors.geometry.iloc[index],
        )
        names.append(str(neighbors["STATE_NAME"].iloc[index]))
        abbreviations.append(str(neighbors["STATE_ABBR"].iloc[index]))
        lengths_in_kilometers.append(
            round(border_length_in_kilometers(border), 2),
        )
        borders.append(border)
    dataframe = geopandas.GeoDataFrame(
        {
            NEIGHBOR_COLUMN_NAME: names,
            NEIGHBOR_ABBREVIATION_COLUMN_NAME: abbreviations,
            LENGTH_COLUMN_NAME: lengths_in_kilometers,
        },
        geometry=borders,
        crs=pyproj.CRS.from_epsg(peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID),
    )
    return typing.cast(
        "geopandas.GeoDataFrame",
        dataframe.rename_geometry(peri_scribe.models.GEOMETRY_COLUMN_NAME),
    )


def ordered_border_coordinates(
    parts: list[shapely.LineString],
) -> list[tuple[float, float]]:
    """Return the border coordinates ordered from the Pacific end to the Mexico end.

    The shared borders are stored as one line per neighbor and may not meet exactly at
    the state corners, so the parts are chained by endpoint proximity into one path
    rather than merged with ``shapely.line_merge`` (which only joins segments that
    actually touch). The path begins at the westernmost endpoint, which is the corner
    California shares with Oregon and the Pacific Ocean.

    Args:
        parts: The border LineStrings to chain.

    Returns:
        The border coordinates in path order.

    Raises:
        AdministrativeBoundariesError: If the parts do not form a single path.
    """
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for part in parts:
        segments.extend(itertools.pairwise(part.coords))
    if not segments:
        message = "California border has no line segments"
        raise peri_scribe.exceptions.AdministrativeBoundariesError(message)

    # Endpoints that round to the same four-decimal coordinate are the same corner.
    # The stored borders are offset by roughly a meter at the corners, so this snaps
    # them together without merging the far-apart vertices that trace the border.
    def snapped(point: tuple[float, float]) -> tuple[float, float]:
        return (round(point[0], 4), round(point[1], 4))

    adjacency: dict[
        tuple[float, float],
        list[tuple[tuple[float, float], tuple[float, float]]],
    ] = collections.defaultdict(list)
    representatives: dict[tuple[float, float], tuple[float, float]] = {}
    for segment in segments:
        for endpoint in segment:
            key = snapped(endpoint)
            adjacency[key].append(segment)
            representatives.setdefault(key, endpoint)

    odd_endpoints = [
        key for key, incident in adjacency.items() if len(incident) % 2 == 1
    ]
    if len(odd_endpoints) != BORDER_PATH_ENDPOINT_COUNT:
        message = "California border is not a single continuous path"
        raise peri_scribe.exceptions.AdministrativeBoundariesError(message)
    start_key = min(odd_endpoints, key=operator.itemgetter(0))
    ordered = [representatives[start_key]]
    current_key = start_key
    previous_segment: (
        tuple[
            tuple[float, float],
            tuple[float, float],
        ]
        | None
    ) = None
    while True:
        incident = [
            segment
            for segment in adjacency[current_key]
            if segment is not previous_segment
        ]
        if not incident:
            break
        segment = incident[0]
        start_endpoint, end_endpoint = segment
        next_endpoint = (
            end_endpoint if snapped(start_endpoint) == current_key else start_endpoint
        )
        ordered.append(next_endpoint)
        previous_segment = segment
        current_key = snapped(next_endpoint)
    return ordered


def california_box_polygon(border: shapely.Geometry) -> shapely.Polygon:
    """Return the "California box" polygon built from *border*.

    The box traces the interstate border from its Pacific/Oregon end to its
    Mexico/Arizona end and closes with straight lines that run due south into Mexico,
    due west into the Pacific Ocean, straight north, and straight east back to the
    Pacific/Oregon end. The landward edges of the box follow the interstate border
    exactly, while the southern and western edges sit beyond every point of California,
    so the box contains all of California and nothing on the far side of the border.

    Args:
        border: The California border lines in WGS84.

    Returns:
        The California box polygon in WGS84.
    """
    ordered = ordered_border_coordinates(line_parts(border))
    northwest_corner = ordered[0]
    southeast_corner = ordered[-1]
    ring = [
        *ordered,
        (southeast_corner[0], CALIFORNIA_BOX_SOUTHERN_LATITUDE),
        (CALIFORNIA_BOX_WESTERN_LONGITUDE, CALIFORNIA_BOX_SOUTHERN_LATITUDE),
        (CALIFORNIA_BOX_WESTERN_LONGITUDE, northwest_corner[1]),
        northwest_corner,
    ]
    return shapely.Polygon(ring)
