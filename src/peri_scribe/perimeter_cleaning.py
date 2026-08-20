"""Cleaning fire perimeter polygons for Google Earth rendering.

WFIGS/IRWIN perimeters are produced by rapid mapping at scale and carry
below-resolution artifacts — zero-area parts and holes, and doubled-back
"hairline" slits — that Google Earth's tessellator cannot render. These
functions remove those artifacts from perimeters read from the sources
directory before they are written to the derived directory, without changing
the source files.
"""

from __future__ import annotations

import dataclasses
import typing

import pyproj
import shapely


@dataclasses.dataclass(frozen=True, kw_only=True)
class PerimeterCleaningConfig:
    """Thresholds for cleaning a fire perimeter polygon.

    The thresholds are measured from the source data's artifact population, so they are
    the smallest settings that remove the artifacts rather than aesthetic choices.
    """

    minimum_part_area_in_square_degrees: float = 1e-6
    collinear_epsilon_in_degrees: float = 1e-7
    maximum_deviation_in_meters: float = 22.0


DEFAULT_CONFIG = PerimeterCleaningConfig()


def polygonal_parts(geometry: shapely.Geometry) -> list[shapely.Polygon]:
    """Return *geometry*'s polygon parts, ignoring non-polygonal members.

    Args:
        geometry: The geometry to flatten.

    Returns:
        Every non-empty polygon part, in order, or an empty list when the geometry has
        none.
    """
    parts: list[shapely.Polygon] = []
    for part in shapely.get_parts(geometry):
        if part.is_empty:
            continue
        if part.geom_type == "Polygon":
            parts.append(typing.cast("shapely.Polygon", part))
        elif part.geom_type == "MultiPolygon":
            parts.extend(
                typing.cast("shapely.Polygon", member)
                for member in part.geoms
                if not member.is_empty
            )
    return parts


def meters_per_degree_latitude(latitude: float) -> float:
    """Return the north-south distance of one degree, in meters, at *latitude*.

    Args:
        latitude: The latitude to measure at, in degrees.

    Returns:
        The meridional length of one degree, in meters.
    """
    _forward_azimuth, _backward_azimuth, distance = pyproj.Geod(
        ellps="WGS84",
    ).inv(0.0, latitude, 0.0, latitude + 1.0)
    return distance


def simplify_tolerance_in_degrees(
    geometry: shapely.Geometry,
    config: PerimeterCleaningConfig,
) -> float:
    """Return the ring simplification tolerance, in degrees, for *geometry*.

    The maximum deviation is converted to degrees at the geometry's latitude, then
    floored at the collinear epsilon so redundant collinear points are always removed.

    Args:
        geometry: The geometry being cleaned, in degree coordinates.
        config: The cleaning thresholds.

    Returns:
        The simplification tolerance in degrees.
    """
    maximum_deviation_in_degrees = (
        config.maximum_deviation_in_meters
        / meters_per_degree_latitude(geometry.representative_point().y)
    )
    return max(
        config.collinear_epsilon_in_degrees,
        maximum_deviation_in_degrees,
    )


def without_degenerate_holes(
    part: shapely.Polygon,
    config: PerimeterCleaningConfig,
) -> shapely.Polygon:
    """Return *part* without its degenerate holes.

    A zero-area hole is not a real unburned island, so it is dropped.

    Args:
        part: The polygon part to filter.
        config: The cleaning thresholds.

    Returns:
        The part with only its real holes.
    """
    return shapely.Polygon(
        part.exterior,
        [
            ring
            for ring in part.interiors
            if shapely.Polygon(ring).area > config.minimum_part_area_in_square_degrees
        ],
    )


def clean_perimeter(
    geometry: shapely.Geometry | None,
    config: PerimeterCleaningConfig = DEFAULT_CONFIG,
) -> shapely.Geometry | None:
    """Return *geometry* cleaned for rendering, or None when nothing remains.

    Parts smaller than the area floor are rejected, degenerate holes are dropped,
    and the surviving geometry is simplified as a whole within the configured
    maximum deviation (which also removes collinear points) and repaired if the
    result is invalid. When every part is below the floor, the original geometry is
    kept, since a whole fire is not below-resolution noise. Simplifying the assembled
    geometry rather than each part keeps the parts from drifting into each other, so
    the result is valid. The geometry is only changed in memory; the source is never
    modified.

    Args:
        geometry: The perimeter geometry, in degree coordinates.
        config: The cleaning thresholds.

    Returns:
        The cleaned polygon or multi-polygon, or the original geometry unchanged when it
        is empty, non-polygonal, or every part is below the area floor.
    """
    if geometry is None or geometry.is_empty:
        return geometry
    parts = polygonal_parts(geometry)
    if not parts:
        return geometry
    kept = [
        without_degenerate_holes(part, config)
        for part in parts
        if part.area > config.minimum_part_area_in_square_degrees
    ]
    if not kept:
        return geometry
    assembled = kept[0] if len(kept) == 1 else shapely.MultiPolygon(kept)
    simplified = shapely.simplify(
        assembled,
        simplify_tolerance_in_degrees(geometry, config),
    )
    if simplified.is_valid:
        return simplified
    return shapely.make_valid(simplified)
