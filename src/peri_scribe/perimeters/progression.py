"""Building the perimeter progression rings that show how a fire grew.

A fire's growth is read from the differential perimeter history, whose rings each show
the area the fire added at one growth step. Each ring carries its own area and
observation time, and the KMZ output colors each ring by where its time falls in the
fire's active growth span.
"""

from __future__ import annotations

import dataclasses
import datetime
import typing
import zoneinfo

from peri_scribe.units import units


if typing.TYPE_CHECKING:
    import pint
    import shapely


# Google Earth shows observation times in the output placemark names, and those
# times are written in California local time.
CALIFORNIA_TIME_ZONE = zoneinfo.ZoneInfo("America/Los_Angeles")


@dataclasses.dataclass(frozen=True, kw_only=True)
class Ring:
    """One growth ring, the time it was observed, and the area it added.

    ``area`` is the ring geometry's area, a quantity in square meters, computed once
    when the ring is built. Synthetic rings that only stand in for another geometry
    (such as a fire's latest perimeter) leave it at the default 0.
    """

    geometry: shapely.Geometry
    observation_time: datetime.datetime | None
    area: pint.Quantity[float] = 0.0 * units.meters**2
