"""Build perimeter rings that show how a fire grew.

Each ring in the differential history represents the ground added at one growth step. It
carries its own area and observation time. KMZ output places that time within the fire's
active growth span to choose the ring's color, so the map shows the sequence of growth.

[Growth rings](../../../docs/algorithms/corrected-growth-rings.md)
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import typing
import zoneinfo

import shapely

import peri_scribe.geo.growth_geometry
import spatial_data.surface_measurements
from measurement_units import units


if typing.TYPE_CHECKING:
    import pint


# Google Earth shows observation times in the output placemark names, and those times
# are written in California local time.
CALIFORNIA_TIME_ZONE = zoneinfo.ZoneInfo("America/Los_Angeles")

MINIMUM_RING_AREA = 1.0 * units.Unit("meters ** 2")
ADDED_AREA_COLUMN = "added_area_square_meters"
SEQUENCE_COLUMN = "ring_sequence_digest"
MEASUREMENT_POLICY = "wgs84-straight-polygon-surface-grid-2^-30-v1"


@dataclasses.dataclass(frozen=True, kw_only=True)
class Ring:
    """One growth ring with its observation time and area measurements.

    ``area`` measures the ring's polygon surface; ``added_area``, when supplied,
    measures the increase in cumulative covered surface. Both use square meters in
    prepared histories and the growth geometry's straight coordinate-plane edges.
    """

    geometry: shapely.Geometry
    observation_time: datetime.datetime | None
    area: pint.Quantity[float] = 0.0 * units.Unit("meters ** 2")
    added_area: pint.Quantity[float] | None = None
    sequence_digest: str | None = None


def sequence_digest(geometries: typing.Iterable[shapely.Geometry]) -> str:
    """Bind the growth measurement policy to the exact ordered displayed shapes.

    Args:
        geometries: The ring geometries in their displayed progression order.

    Returns:
        The explicit policy identity followed by the ordered sequence's SHA-256 digest.
    """
    digest = hashlib.sha256(MEASUREMENT_POLICY.encode() + b"\0")
    for geometry in geometries:
        content = shapely.to_wkb(geometry, include_srid=True)
        digest.update(len(content).to_bytes(8))
        digest.update(content)
    return f"{MEASUREMENT_POLICY}:{digest.hexdigest()}"


def added_areas(
    geometries: typing.Iterable[shapely.Geometry],
) -> tuple[pint.Quantity[float], ...]:
    """Measure newly covered ground without counting overlapping rings twice.

    Args:
        geometries: The ring geometries in their displayed progression order.

    Returns:
        The additional area at each step, in input order.
    """
    combined: shapely.Geometry | None = None
    previous = 0 * units.Unit("meters ** 2")
    added: list[pint.Quantity[float]] = []
    for geometry in geometries:
        combined = peri_scribe.geo.growth_geometry.union(combined, geometry)
        cumulative = covered_area(combined)
        added.append(max(0 * units.Unit("meters ** 2"), cumulative - previous))
        previous = cumulative
    return tuple(added)


def covered_area(geometry: shapely.Geometry | None) -> pint.Quantity[float]:
    """Measure polygonal ground using the common growth precision and edge policy.

    Args:
        geometry: A displayed ring or cumulative geometry in WGS84 coordinates.

    Returns:
        Its normalized polygon surface area in square meters, or zero without area.
    """
    polygonal = peri_scribe.geo.growth_geometry.normalize(geometry)
    return (
        0.0 * units.Unit("meters ** 2")
        if polygonal is None
        else spatial_data.surface_measurements.area(polygonal)
    )
