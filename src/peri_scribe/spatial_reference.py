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
    """Collect the integer wkid values an ArcGIS spatial reference reports."""
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
    """Collect every wkid the layer's metadata reports, including extents."""
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

    Returns None if every geometry is null.
    """
    valid = [geometry for geometry in geometries if geometry is not None]
    if not valid:
        return None
    x_minimum, y_minimum, x_maximum, y_maximum = shapely.total_bounds(valid)
    return x_minimum, x_maximum, y_minimum, y_maximum


def projected_maximum_magnitude(crs: pyproj.CRS) -> float:
    """Return the largest coordinate magnitude a projected CRS plausibly produces.

    Derived from the CRS's area of use: its corners are transformed into the CRS, giving
    the coordinate extent in the CRS's own units.
    """
    area = crs.area_of_use
    if area is None:
        return peri_scribe.models.PROJECTED_MAXIMUM_MAGNITUDE_FALLBACK
    transformer = pyproj.Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    maximum_magnitude = 0.0
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
            maximum_magnitude = max(
                maximum_magnitude,
                abs(x_coordinate),
                abs(y_coordinate),
            )
    if not maximum_magnitude:
        return peri_scribe.models.PROJECTED_MAXIMUM_MAGNITUDE_FALLBACK
    return maximum_magnitude


def spatial_reference_domain(
    wkid: int,
) -> peri_scribe.models.SpatialReferenceDomain | None:
    """Describe the plausible coordinate domain of a wkid, or None if unknown."""
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
    maximum_magnitude = projected_maximum_magnitude(crs)
    return peri_scribe.models.SpatialReferenceDomain(
        crs,
        (
            peri_scribe.models.MINIMUM_PROJECTED_MAGNITUDE,
            maximum_magnitude,
            peri_scribe.models.MINIMUM_PROJECTED_MAGNITUDE,
            maximum_magnitude,
        ),
        f"projected ({unit})",
    )


def axis_fits(
    low: float,
    high: float,
    minimum_magnitude: float,
    maximum_magnitude: float,
) -> bool:
    """Return True if every value in [low, high] has magnitude in the band."""
    if max(abs(low), abs(high)) > maximum_magnitude:
        return False
    if minimum_magnitude > 0 and low <= 0 <= high:
        return False
    return min(abs(low), abs(high)) >= minimum_magnitude


def coordinates_match_domain(
    domain: tuple[float, float, float, float],
    bounds: tuple[float, float, float, float],
) -> bool:
    """Return True if every coordinate magnitude in bounds fits the bands."""
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
    """Describe a CRS's area of use for warnings."""
    area = crs.area_of_use
    if area is None:
        return "unknown"
    return f"longitude {area.west}..{area.east}, latitude {area.south}..{area.north}"


def select_spatial_reference_wkid(
    candidates: set[int],
    bounds: tuple[float, float, float, float] | None,
) -> peri_scribe.models.SpatialReferenceSelection:
    """Choose a wkid from the candidates for coordinates with these bounds.

    Keeps only the candidates whose plausible coordinate domain — derived from pyproj's
    CRS database — fits the returned features' coordinate bounds. The single surviving
    candidate wins; when others were excluded the selection carries a warning that lists
    them and the reason. When no wkid can be chosen, the selection carries a failure
    message that explains why.
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
    matches: list[int] = []
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
            excluded.append(
                f"{wkid} ({domain.description}, expected coordinate "
                f"magnitudes x {x_minimum_band}..{x_maximum_band}, "
                f"y {y_minimum_band}..{y_maximum_band}, "
                f"got x {x_minimum}..{x_maximum}, "
                f"y {y_minimum}..{y_maximum})",
            )
        elif domain.crs.is_geographic and not coordinates_in_area(domain.crs, bounds):
            excluded.append(
                f"{wkid} (coordinates outside its area of use "
                f"{area_of_use_text(domain.crs)})",
            )
        else:
            matches.append(wkid)
    if len(matches) == 1:
        warning = None
        if excluded:
            warning = (
                f"  warning: picked spatial reference EPSG:{matches[0]}; "
                f"excluded {', '.join(excluded)}"
            )
        return peri_scribe.models.SpatialReferenceSelection(
            wkid=matches[0],
            warning=warning,
        )
    if not matches:
        return peri_scribe.models.SpatialReferenceSelection(
            wkid=None,
            failure_message=(
                "no reported spatial reference wkid matches the returned "
                f"coordinates (x {x_minimum}..{x_maximum}, "
                f"y {y_minimum}..{y_maximum}); "
                f"excluded {', '.join(excluded)}"
            ),
        )
    return peri_scribe.models.SpatialReferenceSelection(
        wkid=None,
        failure_message=(
            f"ambiguous spatial reference: wkids {sorted(matches)} all match "
            f"the returned coordinates (x {x_minimum}..{x_maximum}, "
            f"y {y_minimum}..{y_maximum})"
        ),
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
    """
    candidates = layer_wkids(layer) | spatial_reference_wkids(
        feature_set.spatial_reference,
    )
    selection = select_spatial_reference_wkid(candidates, bounds)
    if selection.wkid is not None:
        if selection.warning is not None:
            logger.warning(selection.warning)
        return selection.wkid
    raise peri_scribe.exceptions.NoSpatialReferenceError(selection.failure_message)
