"""Building the perimeter progression rings that show how a fire grew.

A fire's growth is read from the differential perimeter history, whose rings each show
the area the fire added at one growth step. Each ring carries its own area and
observation time, and the KMZ output colors each ring by where its time falls in the
fire's active growth span.
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import typing
import zoneinfo

import shapely

import peri_scribe.units
from peri_scribe.units import units


if typing.TYPE_CHECKING:
    import pint


# Google Earth shows observation times in the output placemark names, and those times
# are written in California local time.
CALIFORNIA_TIME_ZONE = zoneinfo.ZoneInfo("America/Los_Angeles")

MINIMUM_RING_AREA = 1.0 * units.Unit("meters ** 2")
ADDED_AREA_COLUMN = "added_area_square_meters"
SEQUENCE_COLUMN = "ring_sequence_digest"


@dataclasses.dataclass(frozen=True, kw_only=True)
class Ring:
    """One growth ring, the time it was observed, and the area it added.

    ``area`` is the ring geometry's area, a quantity in square meters, computed once
    when the ring is built. Synthetic rings that only stand in for another geometry
    (such as a fire's latest perimeter) leave it at the default 0.
    """

    geometry: shapely.Geometry
    observation_time: datetime.datetime | None
    area: pint.Quantity[float] = 0.0 * units.Unit("meters ** 2")
    added_area: pint.Quantity[float] | None = None
    sequence_digest: str | None = None


def sequence_digest(geometries: typing.Iterable[shapely.Geometry]) -> str:
    """Identify the exact ordered shapes whose cumulative areas were measured.

    Args:
        geometries: The ring geometries in their displayed progression order.

    Returns:
        The ordered sequence's SHA-256 digest.
    """
    digest = hashlib.sha256()
    for geometry in geometries:
        content = shapely.to_wkb(geometry, include_srid=True)
        digest.update(len(content).to_bytes(8))
        digest.update(content)
    return digest.hexdigest()


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
        combined = geometry if combined is None else shapely.union(combined, geometry)
        cumulative = peri_scribe.units.area(combined)
        added.append(max(0 * units.Unit("meters ** 2"), cumulative - previous))
        previous = cumulative
    return tuple(added)
