"""Choose a spatial reference that fits the coordinates ArcGIS returned.

A layer can report different wkids in its metadata, extents, and query response.
Collecting all of them lets the returned coordinate bounds help distinguish the
candidates instead of trusting one report unconditionally.

[Algorithm note](../../docs/algorithms/source-validation.md)
"""

from __future__ import annotations

import dataclasses
import math
import typing

import pyproj
import pyproj.exceptions
import shapely
import structlog

import arcgis_access.exceptions
import spatial_data.reference
from measurement_units import units


if typing.TYPE_CHECKING:
    import arcgis.features


logger = structlog.get_logger()


# Smaller coordinates cannot reliably distinguish projected units from degrees.
MINIMUM_PROJECTED_MAGNITUDE = 1.0 * units.km

# A broad fallback is used when projected CRS metadata has no area of use.
PROJECTED_MAXIMUM_MAGNITUDE_FALLBACK = 25_000.0 * units.km


@dataclasses.dataclass(frozen=True, kw_only=True)
class SpatialReferenceDomain:
    """Plausible coordinate magnitude bands for a spatial reference."""

    crs: pyproj.CRS
    bands: tuple[float, float, float, float]  # x and y (minimum, maximum) magnitudes
    description: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class SpatialReferenceSelection:
    """Result of selecting a spatial reference wkid from candidates.

    When a wkid is chosen, ``warning`` holds the text to log about excluded candidates,
    if any. When no wkid can be chosen, ``failure_message`` explains why.
    """

    wkid: int | None
    warning: str | None = None
    failure_message: str = ""


def spatial_reference_wkids(spatial_reference: object) -> set[int]:
    """Collect the integer wkid values an ArcGIS spatial reference reports.

    Args:
        spatial_reference: ArcGIS spatial-reference metadata, expected to be a
            dictionary containing ``wkid`` or ``latestWkid``.

    Returns:
        The set of integer wkid values the spatial reference reports.
    """
    if not isinstance(spatial_reference, dict):
        return set()
    wkids: set[int] = set()
    for key in ("wkid", "latestWkid"):
        value = spatial_reference.get(key)
        if isinstance(value, str) and value.isdigit():
            value = int(value)
        if isinstance(value, int):
            wkids.add(value)
    return wkids


def layer_wkids(layer: arcgis.features.FeatureLayer) -> set[int]:
    """Collect every wkid the layer's metadata reports, including extents.

    Args:
        layer: The ArcGIS feature layer whose spatial-reference metadata is needed.

    Returns:
        The set of wkid values the layer's metadata reports, including extents.
    """
    wkids: set[int] = set()
    properties = layer.properties
    for key in ("extent", "fullExtent", "initialExtent"):
        container = properties.get(key)
        if isinstance(container, dict):
            wkids |= spatial_reference_wkids(container.get("spatialReference"))
    wkids |= spatial_reference_wkids(properties.get("spatialReference"))
    return wkids


def bounds_of(
    geometries: list[shapely.Geometry | None],
) -> tuple[float, float, float, float] | None:
    """Return (x_minimum, x_maximum, y_minimum, y_maximum) of the geometries.

    Args:
        geometries: The feature geometries in their source coordinate units, with None
            for missing geometry.

    Returns:
        The bounds as (x_minimum, x_maximum, y_minimum, y_maximum), or None when no
        geometry has coordinates.
    """
    valid = [
        geometry
        for geometry in geometries
        if geometry is not None and not geometry.is_empty
    ]
    if not valid:
        return None
    x_minimum, y_minimum, x_maximum, y_maximum = shapely.total_bounds(valid)
    return x_minimum, x_maximum, y_minimum, y_maximum


def projected_maximum_magnitude_in_crs_units(crs: pyproj.CRS) -> float:
    """Return the largest coordinate magnitude a projected CRS plausibly produces.

    Transform the four corners of the CRS's area of use and take their largest finite
    coordinate magnitude. This is a plausibility estimate, not a bound on every point a
    nonlinear projection can produce inside that area.

    Args:
        crs: The projected coordinate reference system whose extent is needed.

    Returns:
        The estimated magnitude, or ``PROJECTED_MAXIMUM_MAGNITUDE_FALLBACK`` when the
        CRS has no area of use or its transformed corners supply no usable magnitude.
    """
    area = crs.area_of_use
    if area is None:
        return PROJECTED_MAXIMUM_MAGNITUDE_FALLBACK.m_as("meters")
    transformer = pyproj.Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    maximum_magnitude_in_crs_units = 0.0
    for longitude, latitude in (
        (area.west, area.south),
        (area.east, area.south),
        (area.west, area.north),
        (area.east, area.north),
    ):
        try:
            x_coordinate, y_coordinate = transformer.transform(longitude, latitude)
        except pyproj.exceptions.ProjError, ValueError:
            continue
        if math.isfinite(x_coordinate) and math.isfinite(y_coordinate):
            maximum_magnitude_in_crs_units = max(
                maximum_magnitude_in_crs_units,
                abs(x_coordinate),
                abs(y_coordinate),
            )
    if not maximum_magnitude_in_crs_units:
        return PROJECTED_MAXIMUM_MAGNITUDE_FALLBACK.m_as("meters")
    return maximum_magnitude_in_crs_units


def spatial_reference_domain(
    wkid: int,
) -> SpatialReferenceDomain | None:
    """Describe the plausible coordinate domain of a wkid, or None if unknown.

    Args:
        wkid: The spatial-reference identifier to resolve through the CRS database.

    Returns:
        The domain of the wkid's CRS, or None if the wkid has no known geographic or
        projected CRS.
    """
    try:
        crs = spatial_data.reference.spatial_reference_for_id(wkid)
    except pyproj.exceptions.CRSError:
        return None
    if crs.is_geographic:
        return SpatialReferenceDomain(
            crs=crs,
            bands=(0.0, 180.0, 0.0, 90.0),
            description="geographic (degrees)",
        )
    if not crs.is_projected:
        return None
    unit = crs.axis_info[0].unit_name if crs.axis_info else "unknown"
    maximum_magnitude_in_crs_units = projected_maximum_magnitude_in_crs_units(crs)
    return SpatialReferenceDomain(
        crs=crs,
        bands=(
            MINIMUM_PROJECTED_MAGNITUDE.m_as("meters"),
            maximum_magnitude_in_crs_units,
            MINIMUM_PROJECTED_MAGNITUDE.m_as("meters"),
            maximum_magnitude_in_crs_units,
        ),
        description=f"projected ({unit})",
    )


def axis_fits(
    low: float,
    high: float,
    minimum_magnitude_in_crs_units: float,
    maximum_magnitude_in_crs_units: float,
) -> bool:
    """Return True if every value in [low, high] has magnitude in the band.

    Args:
        low: The lower coordinate bound in the candidate CRS's units.
        high: The upper coordinate bound in the candidate CRS's units.
        minimum_magnitude_in_crs_units: The smallest plausible absolute coordinate value
            in the same units.
        maximum_magnitude_in_crs_units: The largest plausible absolute coordinate value
            in the same units.

    Returns:
        True if every value in [low, high] has magnitude in the band.
    """
    if max(abs(low), abs(high)) > maximum_magnitude_in_crs_units:
        return False
    if minimum_magnitude_in_crs_units > 0 and low <= 0 <= high:
        return False
    return min(abs(low), abs(high)) >= minimum_magnitude_in_crs_units


def coordinates_match_domain(
    domain: tuple[float, float, float, float],
    bounds: tuple[float, float, float, float],
) -> bool:
    """Return True if every coordinate magnitude in bounds fits the bands.

    Args:
        domain: The minimum and maximum absolute coordinate magnitudes for x, then y, in
            the candidate CRS's units.
        bounds: The observed (x_minimum, x_maximum, y_minimum, y_maximum) coordinates in
            the source units.

    Returns:
        True if every coordinate magnitude in bounds fits the bands.
    """
    x_minimum_band, x_maximum_band, y_minimum_band, y_maximum_band = domain
    x_minimum, x_maximum, y_minimum, y_maximum = bounds
    return axis_fits(
        x_minimum,
        x_maximum,
        x_minimum_band,
        x_maximum_band,
    ) and axis_fits(y_minimum, y_maximum, y_minimum_band, y_maximum_band)


def longitudes_in_area(
    west: float,
    east: float,
    x_minimum: float,
    x_maximum: float,
) -> bool:
    """Return True if the longitude extent lies within the area's bounds.

    The area may wrap across the antimeridian, in which case west > east.

    Args:
        west: The area's western longitude boundary in degrees.
        east: The area's eastern longitude boundary in degrees.
        x_minimum: The minimum observed longitude in degrees.
        x_maximum: The maximum observed longitude in degrees.

    Returns:
        True if the longitude extent lies within the area's bounds.
    """
    if west <= east:
        return west <= x_minimum and x_maximum <= east
    return x_maximum <= east or x_minimum >= west


def coordinates_in_area(
    crs: pyproj.CRS,
    bounds: tuple[float, float, float, float],
) -> bool:
    """Return True if the bounds fall inside the CRS's area of use.

    An unknown area of use is treated as matching.

    Args:
        crs: The coordinate reference system whose geographic area of use is checked.
        bounds: The observed (x_minimum, x_maximum, y_minimum, y_maximum) longitude and
            latitude bounds in degrees.

    Returns:
        True if the bounds fall inside the CRS's area of use.
    """
    area = crs.area_of_use
    if area is None:
        return True
    x_minimum, x_maximum, y_minimum, y_maximum = bounds
    return (
        longitudes_in_area(area.west, area.east, x_minimum, x_maximum)
        and area.south <= y_minimum
        and y_maximum <= area.north
    )


def area_of_use_text(crs: pyproj.CRS) -> str:
    """Describe a CRS's area of use for warnings.

    Args:
        crs: The coordinate reference system whose area of use should be described.

    Returns:
        A human-readable description of the CRS's area of use.
    """
    area = crs.area_of_use
    if area is None:
        return "unknown"
    return f"longitude {area.west}..{area.east}, latitude {area.south}..{area.north}"


def classify_candidates_for_bounds(
    candidates: set[int],
    bounds: tuple[float, float, float, float],
) -> tuple[list[int], dict[int, str], list[str]]:
    """Group candidates by whether their expected coordinate ranges fit the bounds.

    An unknown or incompatible coordinate range excludes a candidate, with a reason. A
    geographic candidate whose range fits but whose area of use does not contain the
    coordinates is kept separately. That distinction lets selection consider it as a
    fallback when no better candidate fits.

    Args:
        candidates: The spatial-reference identifiers reported by the source.
        bounds: The observed (x_minimum, x_maximum, y_minimum, y_maximum) coordinates in
            the source units.

    Returns:
        Three groups: matching wkids, geographic wkids whose coordinate ranges fit but
        whose areas of use exclude the coordinates (mapped to area descriptions), and
        reasons for excluding the remaining candidates. Projected candidates do not
        need to pass the geographic area-of-use check.
    """
    matches: list[int] = []
    outside_area: dict[int, str] = {}
    excluded: list[str] = []
    for wkid in sorted(candidates):
        domain = spatial_reference_domain(wkid)
        if domain is None:
            excluded.append(f"{wkid} (no expected coordinate range known)")
        elif not coordinates_match_domain(domain.bands, bounds):
            (x_minimum_band, x_maximum_band, y_minimum_band, y_maximum_band) = (
                domain.bands
            )
            x_minimum, x_maximum, y_minimum, y_maximum = bounds
            excluded.append(
                f"{wkid} ({domain.description}, expected coordinate "
                f"magnitudes x {x_minimum_band}..{x_maximum_band}, "
                f"y {y_minimum_band}..{y_maximum_band}, "
                f"got x {x_minimum}..{x_maximum}, "
                f"y {y_minimum}..{y_maximum})",
            )
        elif domain.crs.is_geographic and not coordinates_in_area(domain.crs, bounds):
            outside_area[wkid] = area_of_use_text(domain.crs)
        else:
            matches.append(wkid)
    return matches, outside_area, excluded


def select_spatial_reference_wkid(
    candidates: set[int],
    bounds: tuple[float, float, float, float] | None,
) -> SpatialReferenceSelection:
    """Choose a wkid that fits the coordinates, or explain why none can be chosen.

    Coordinate-range heuristics combine fixed limits with pyproj's CRS metadata. A
    candidate must fit those ranges and, for a geographic reference, its area of use.
    One matching candidate wins; several matches are ambiguous. If none matches but
    exactly one failed only the area-of-use check, use it with a warning: its coordinate
    range is plausible and the source reports no better candidate.

    Warnings explain which alternatives were excluded. With no geometry to check, accept
    a single reported candidate; multiple candidates remain ambiguous.

    Args:
        candidates: The spatial-reference identifiers reported by the source.
        bounds: The observed (x_minimum, x_maximum, y_minimum, y_maximum) coordinates in
            the source units, or None when no geometry is available.

    Returns:
        The selection describing the chosen wkid, or explaining why none could be
        chosen.
    """
    if not candidates:
        return SpatialReferenceSelection(
            wkid=None,
            failure_message=(
                "no spatial reference wkid reported by the layer or its query"
            ),
        )
    if bounds is None:
        if len(candidates) == 1:
            return SpatialReferenceSelection(
                wkid=next(iter(candidates)),
            )
        return SpatialReferenceSelection(
            wkid=None,
            failure_message=(
                "cannot determine spatial reference: wkids "
                f"{sorted(candidates)} are reported, but no feature geometry "
                "is available to check them"
            ),
        )
    x_minimum, x_maximum, y_minimum, y_maximum = bounds
    matches, outside_area, excluded = classify_candidates_for_bounds(candidates, bounds)
    outside_area_descriptions = [
        f"{wkid} (coordinates outside its area of use {area_text})"
        for wkid, area_text in outside_area.items()
    ]
    if len(matches) == 1:
        warning = None
        if excluded or outside_area:
            warning = (
                f"  warning: picked spatial reference EPSG:{matches[0]}; "
                f"excluded {', '.join([*excluded, *outside_area_descriptions])}"
            )
        return SpatialReferenceSelection(
            wkid=matches[0],
            warning=warning,
        )
    if not matches:
        if len(outside_area) == 1:
            wkid = next(iter(outside_area))
            return SpatialReferenceSelection(
                wkid=wkid,
                warning=(
                    "  warning: picked spatial reference "
                    f"EPSG:{wkid}; the returned coordinates fall outside its "
                    f"area of use ({outside_area[wkid]})"
                ),
            )
        failure_message = (
            "no reported spatial reference wkid matches the returned "
            f"coordinates (x {x_minimum}..{x_maximum}, "
            f"y {y_minimum}..{y_maximum}); "
            f"excluded {', '.join([*excluded, *outside_area_descriptions])}"
        )
    else:
        failure_message = (
            f"ambiguous spatial reference: wkids {sorted(matches)} all match "
            f"the returned coordinates (x {x_minimum}..{x_maximum}, "
            f"y {y_minimum}..{y_maximum})"
        )
    return SpatialReferenceSelection(
        wkid=None,
        failure_message=failure_message,
    )


def choose_spatial_reference_id(
    layer: arcgis.features.FeatureLayer,
    feature_set: arcgis.features.FeatureSet,
    bounds: tuple[float, float, float, float] | None,
) -> int:
    """Pick the spatial reference id for the coordinates a query returned.

    The layer metadata, layer extents, and query response can each supply candidates.
    Selection checks them together against the coordinate bounds and logs any warning.
    If it cannot choose one, NoSpatialReferenceError stops the caller from writing
    coordinates with an unsupported spatial reference.

    Args:
        layer: The ArcGIS feature layer supplying metadata and extents.
        feature_set: The query response supplying additional spatial-reference data.
        bounds: The returned features' (x_minimum, x_maximum, y_minimum, y_maximum)
            coordinates in the source units, or None when no geometry is available.

    Returns:
        The chosen spatial reference wkid.

    Raises:
        NoSpatialReferenceError: If no candidate can be selected, including when several
            candidates match and the choice is ambiguous.
    """
    candidates = layer_wkids(layer) | spatial_reference_wkids(
        feature_set.spatial_reference,
    )
    selection = select_spatial_reference_wkid(candidates, bounds)
    if selection.wkid is not None:
        if selection.warning is not None:
            logger.info(selection.warning)
        return selection.wkid
    raise arcgis_access.exceptions.NoSpatialReferenceError(selection.failure_message)
