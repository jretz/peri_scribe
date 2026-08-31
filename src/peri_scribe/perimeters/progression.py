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


if typing.TYPE_CHECKING:
    import shapely


# Google Earth shows observation times in the output placemark names, and those
# times are written in California local time.
CALIFORNIA_TIME_ZONE = zoneinfo.ZoneInfo("America/Los_Angeles")

PROGRESSION_MAPS_FOLDER_NAME = "Perimeter Progression Maps"


@dataclasses.dataclass(frozen=True, kw_only=True)
class Ring:
    """One growth ring, the time it was observed, and the area it added.

    ``area`` is the ring geometry's area in square meters, computed once when the ring
    is built. Synthetic rings that only stand in for another geometry (such as a fire's
    latest perimeter) leave it at the default 0.
    """

    geometry: shapely.Geometry
    observation_time: datetime.datetime | None
    area: float = 0.0


@dataclasses.dataclass(frozen=True, kw_only=True)
class ProgressionBand:
    """One KML-template progression band: a name and the day range it covers.

    The template's fictional progression perimeters are named for these bands; the KMZ
    output colors real rings by where their times fall in the fire's active span
    instead, so these bands only name the template's geometry.

    ``minimum_age_in_days`` is the newest age (days before the latest date) in the band
    and ``maximum_age_in_days`` the oldest; a None maximum means the band has no upper
    bound and covers every ring older than the minimum. The band names oldest age ("128+
    Days Before That").
    """

    name: str
    minimum_age_in_days: int
    maximum_age_in_days: int | None


PROGRESSION_BANDS = (
    ProgressionBand(
        name="Latest Day",
        minimum_age_in_days=0,
        maximum_age_in_days=0,
    ),
    ProgressionBand(
        name="2 Days Before That",
        minimum_age_in_days=1,
        maximum_age_in_days=2,
    ),
    ProgressionBand(
        name="4 Days Before That",
        minimum_age_in_days=3,
        maximum_age_in_days=6,
    ),
    ProgressionBand(
        name="8 Days Before That",
        minimum_age_in_days=7,
        maximum_age_in_days=14,
    ),
    ProgressionBand(
        name="16 Days Before That",
        minimum_age_in_days=15,
        maximum_age_in_days=30,
    ),
    ProgressionBand(
        name="32 Days Before That",
        minimum_age_in_days=31,
        maximum_age_in_days=62,
    ),
    ProgressionBand(
        name="64 Days Before That",
        minimum_age_in_days=63,
        maximum_age_in_days=126,
    ),
    ProgressionBand(
        name="128+ Days Before That",
        minimum_age_in_days=127,
        maximum_age_in_days=None,
    ),
)
