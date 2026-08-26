"""Spatial reference resolution for peri_scribe.

Collects every wkid reported by a layer's metadata, extents, and query response, then
chooses the candidate whose plausible coordinate domain fits the returned features'
coordinate bounds.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pyproj
import pyproj.exceptions
import shapely
import structlog

import peri_scribe.exceptions
import peri_scribe.models


if TYPE_CHECKING:
    import arcgis.features


logger = structlog.get_logger()


def spatial_reference_wkids(spatial_reference: object) -> set[int]:
    """Collect the integer wkid values an ArcGIS spatial reference reports.

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

    Returns:
        The bounds as (x_minimum, x_maximum, y_minimum, y_maximum), or None if every
        geometry is null.
    """
    valid = [geometry for geometry in geometries if geometry is not None]
    if not valid:
        return None
    x_minimum, y_minimum, x_maximum, y_maximum = shapely.total_bounds(valid)
    return x_minimum, x_maximum, y_minimum, y_maximum


def projected_maximum_magnitude_in_crs_units(crs: pyproj.CRS) -> float:
    """Return the largest coordinate magnitude a projected CRS plausibly produces.

    Derived from the CRS's area of use: its corners are transformed into the CRS, giving
    the coordinate extent in the CRS's own units.

    Returns:
        The largest coordinate magnitude the CRS plausibly produces, or the
        ``PROJECTED_MAXIMUM_MAGNITUDE_FALLBACK_IN_METERS`` constant when the CRS has no
        area of use.
    """
    area = crs.area_of_use
    if area is None:
        return peri_scribe.models.PROJECTED_MAXIMUM_MAGNITUDE_FALLBACK_IN_METERS
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
        return peri_scribe.models.PROJECTED_MAXIMUM_MAGNITUDE_FALLBACK_IN_METERS
    return maximum_magnitude_in_crs_units


def spatial_reference_domain(
    wkid: int,
) -> peri_scribe.models.SpatialReferenceDomain | None:
    """Describe the plausible coordinate domain of a wkid, or None if unknown.

    Returns:
        The domain of the wkid's CRS, or None if the wkid has no known geographic or
        projected CRS.
    """
    try:
        crs = pyproj.CRS.from_epsg(wkid)
    except pyproj.exceptions.CRSError:
        return None
    if crs.is_geographic:
        return peri_scribe.models.SpatialReferenceDomain(
            crs,
            (0.0, 180.0, 0.0, 90.0),
            "geographic (degrees)",
        )
    if not crs.is_projected:
        return None
    unit = crs.axis_info[0].unit_name if crs.axis_info else "unknown"
    maximum_magnitude_in_crs_units = projected_maximum_magnitude_in_crs_units(crs)
    return peri_scribe.models.SpatialReferenceDomain(
        crs,
        (
            peri_scribe.models.MINIMUM_PROJECTED_MAGNITUDE_IN_METERS,
            maximum_magnitude_in_crs_units,
            peri_scribe.models.MINIMUM_PROJECTED_MAGNITUDE_IN_METERS,
            maximum_magnitude_in_crs_units,
        ),
        f"projected ({unit})",
    )


def axis_fits(
    low: float,
    high: float,
    minimum_magnitude_in_crs_units: float,
    maximum_magnitude_in_crs_units: float,
) -> bool:
    """Return True if every value in [low, high] has magnitude in the band.

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
    """Classify candidates by how their coordinate range fits the bounds.

    A candidate whose expected coordinate range does not fit the bounds is excluded,
    with a description of why. A geographic candidate whose expected range fits but
    whose area of use does not contain the coordinates is kept, but reported as
    outside its area of use.

    Returns:
        A tuple of the wkids that fit the bounds and contain the coordinates in their
        area of use, the wkids that fit the bounds but not the coordinates in their
        area of use (mapped to their area of use text), and the descriptions of the
        excluded candidates.
    """
    matches: list[int] = []
    outside_area: dict[int, str] = {}
    excluded: list[str] = []
    for wkid in sorted(candidates):
        domain = spatial_reference_domain(wkid)
        if domain is None:
            excluded.append(f"{wkid} (no expected coordinate range known)")
        elif not coordinates_match_domain(domain.bands, bounds):
            (
                x_minimum_band,
                x_maximum_band,
                y_minimum_band,
                y_maximum_band,
            ) = domain.bands
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
) -> peri_scribe.models.SpatialReferenceSelection:
    """Choose a wkid from the candidates for coordinates with these bounds.

    Candidates whose plausible coordinate domain — derived from pyproj's CRS database —
    does not fit the returned features' coordinate bounds are excluded, as are
    geographic candidates whose area of use does not contain the coordinates. When
    exactly one candidate remains, it wins and the selection carries a warning listing
    the excluded candidates and the reason. When no candidate remains but exactly one
    was excluded only by the area-of-use check, that candidate is chosen with a
    warning, because its coordinate range is plausible and no better candidate is
    reported. When no wkid can be chosen, the selection carries a failure message that
    explains why.

    Returns:
        The selection describing the chosen wkid, or explaining why none could be
        chosen.
    """
    if not candidates:
        return peri_scribe.models.SpatialReferenceSelection(
            wkid=None,
            failure_message=(
                "no spatial reference wkid reported by the layer or its query"
            ),
        )
    if bounds is None:
        if len(candidates) == 1:
            return peri_scribe.models.SpatialReferenceSelection(
                wkid=next(iter(candidates)),
            )
        return peri_scribe.models.SpatialReferenceSelection(
            wkid=None,
            failure_message=(
                "cannot determine spatial reference: wkids "
                f"{sorted(candidates)} are reported, but no feature geometry "
                "is available to check them"
            ),
        )
    x_minimum, x_maximum, y_minimum, y_maximum = bounds
    matches, outside_area, excluded = classify_candidates_for_bounds(
        candidates,
        bounds,
    )
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
        return peri_scribe.models.SpatialReferenceSelection(
            wkid=matches[0],
            warning=warning,
        )
    if not matches:
        if len(outside_area) == 1:
            wkid = next(iter(outside_area))
            return peri_scribe.models.SpatialReferenceSelection(
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
    return peri_scribe.models.SpatialReferenceSelection(
        wkid=None,
        failure_message=failure_message,
    )


def choose_spatial_reference_id(
    layer: arcgis.features.FeatureLayer,
    feature_set: arcgis.features.FeatureSet,
    bounds: tuple[float, float, float, float] | None,
) -> int:
    """Pick the spatial reference id for the coordinates a query returned.

    Collects every wkid the layer reports (layer metadata, layer extents, and the query
    response) and selects the candidate whose plausible coordinate domain fits the
    returned features' coordinate bounds. If the selection carries a warning, it is
    logged; if no wkid can be chosen, NoSpatialReferenceError is raised so no output is
    written.

    Returns:
        The chosen spatial reference wkid.

    Raises:
        NoSpatialReferenceError: If no candidate wkid matches the returned coordinates.
    """
    candidates = layer_wkids(layer) | spatial_reference_wkids(
        feature_set.spatial_reference,
    )
    selection = select_spatial_reference_wkid(candidates, bounds)
    if selection.wkid is not None:
        if selection.warning is not None:
            logger.info(selection.warning)
        return selection.wkid
    raise peri_scribe.exceptions.NoSpatialReferenceError(selection.failure_message)
