"""Building the perimeter progression bands that show how a fire grew.

A fire's growth is read from the differential perimeter history, whose rings each
show the area the fire added at one growth step. The rings are grouped into the day
ranges the KML template names (the latest day, the two days before that, and so on),
and each range becomes one band whose geometry is the union of its rings. The band
set is defined here so the template generator and the KMZ output both use the same
ranges and names.
"""

from __future__ import annotations

import dataclasses
import datetime
import typing
import zoneinfo

import shapely


# Google Earth shows observation times in the output placemark names, and those
# times are written in California local time.
CALIFORNIA_TIME_ZONE = zoneinfo.ZoneInfo("America/Los_Angeles")

PROGRESSION_MAPS_FOLDER_NAME = "Perimeter Progression Maps"


@dataclasses.dataclass(frozen=True, kw_only=True)
class Ring:
    """One growth ring and the time it was observed."""

    geometry: shapely.Geometry
    observation_time: datetime.datetime | None


@dataclasses.dataclass(frozen=True, kw_only=True)
class ProgressionBand:
    """One progression-map band: a name and the day range it covers.

    `minimum_age_in_days` is the newest age (days before the latest date) in the
    band and `maximum_age_in_days` the oldest; a None maximum means the band has no
    oldest age ("128+ Days Before That").
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


@dataclasses.dataclass(frozen=True, kw_only=True)
class ProgressionBandGeometry:
    """One fire's growth band, ready to symbolize."""

    name: str
    label: str
    geometry: shapely.Geometry
    observation_time: datetime.datetime | None


def ring_date(observation_time: datetime.datetime) -> datetime.date:
    """Return the California-local date of *observation_time*.

    The band ranges count calendar days, so each ring needs a date in the time zone
    the output labels use.

    Args:
        observation_time: The ring's observation time.

    Returns:
        The ring's California date.
    """
    return observation_time.astimezone(CALIFORNIA_TIME_ZONE).date()


def band_for_age(age: int) -> ProgressionBand | None:
    """Return the band that covers a ring *age* days old, or None.

    The bands tile the ages from 0 upward without gaps, so the first band whose
    range contains the age is the one.

    Args:
        age: The ring's age in days before the latest date.

    Returns:
        The covering band, or None when no band covers the age.
    """
    for band in PROGRESSION_BANDS:
        if age < band.minimum_age_in_days:
            continue
        if band.maximum_age_in_days is None or age <= band.maximum_age_in_days:
            return band
    return None


def band_label(
    band: ProgressionBand,
    latest_date: datetime.date,
    ring_dates: typing.Sequence[datetime.date],
) -> str:
    """Return the label naming the dates *band* covers for one fire.

    The label shows the actual span of the fire's rings in the band, so a band the
    fire only partially fills names the dates the fire really covers rather than the
    band's full range. A single date is named alone. The open-ended band is named by
    the boundary it starts at, because its data extends without a lower bound.

    Args:
        band: The band to label.
        latest_date: The fire's latest observation date.
        ring_dates: The dates of the fire's rings in the band.

    Returns:
        The band's label, like ``08/15``, ``08/13 - 08/14``, or ``≤ 04/10``.
    """
    if band.maximum_age_in_days is None:
        boundary = latest_date - datetime.timedelta(days=band.minimum_age_in_days)
        return f"≤ {boundary:%m/%d}"
    dates = sorted(set(ring_dates))
    if len(dates) == 1:
        return f"{dates[0]:%m/%d}"
    return f"{dates[0]:%m/%d} - {dates[-1]:%m/%d}"


def progression_bands(
    rings: typing.Sequence[Ring],
) -> tuple[ProgressionBandGeometry, ...]:
    """Return one growth band per day range *rings* cover, newest first.

    The differential history already reduced the fire to its growth rings, so each
    band is simply the union of the rings whose dates fall in the band's range; a
    range with no rings contributes no band, and a fire with no rings yields none.
    Rings without an observation time cannot be dated and are left out.

    Args:
        rings: The fire's growth rings in chronological order.

    Returns:
        One band geometry per covered range, newest first.
    """
    dated: list[tuple[datetime.date, datetime.datetime, Ring]] = []
    for ring in rings:
        observation_time = ring.observation_time
        if observation_time is None:
            continue
        dated.append((ring_date(observation_time), observation_time, ring))
    if not dated:
        return ()
    latest_date = max(date for date, _time, _ring in dated)
    by_band: dict[
        ProgressionBand,
        list[tuple[datetime.date, datetime.datetime, Ring]],
    ] = {}
    for date, observation_time, ring in dated:
        age = (latest_date - date).days
        band = band_for_age(age)
        if band is not None:
            by_band.setdefault(band, []).append((date, observation_time, ring))
    geometries: list[ProgressionBandGeometry] = []
    for band in PROGRESSION_BANDS:
        bucket = by_band.get(band)
        if bucket is None:
            continue
        geometry = shapely.union_all([ring.geometry for _date, _time, ring in bucket])
        if geometry.is_empty:
            continue
        geometries.append(
            ProgressionBandGeometry(
                name=band.name,
                label=band_label(
                    band,
                    latest_date,
                    [date for date, _time, _ring in bucket],
                ),
                geometry=geometry,
                # The band's timestamp is the moment its last ring was observed,
                # so the time slider shows the band appearing exactly when the
                # band's growth was complete.
                observation_time=max(time for _date, time, _ring in bucket),
            ),
        )
    return tuple(geometries)
