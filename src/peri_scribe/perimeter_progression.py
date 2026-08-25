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


@dataclasses.dataclass(frozen=True, kw_only=True)
class ProgressionBandRings:
    """One fire's growth rings grouped into one day range, ready to symbolize."""

    name: str
    label: str
    rings: tuple[Ring, ...]
    band_index: int


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


@dataclasses.dataclass(frozen=True, kw_only=True)
class _BandedRings:
    """One band's rings, its label, and the area they cover."""

    name: str
    label: str
    rings: tuple[Ring, ...]
    band_index: int
    geometry: shapely.Geometry


def _banded_rings(
    rings: typing.Sequence[Ring],
) -> tuple[_BandedRings, ...]:
    """Return each band *rings* cover with its dated rings, newest first.

    The differential history already reduced the fire to its growth rings, so a
    band simply holds the rings whose dates fall in its range; a range with no
    rings contributes nothing, and a fire with no rings yields none. Rings without
    an observation time cannot be dated and are left out.

    Args:
        rings: The fire's growth rings in chronological order.

    Returns:
        One banded-rings entry per covered range, newest first.
    """
    dated: list[tuple[datetime.date, Ring]] = []
    for ring in rings:
        observation_time = ring.observation_time
        if observation_time is None:
            continue
        dated.append((ring_date(observation_time), ring))
    if not dated:
        return ()
    latest_date = max(date for date, _ring in dated)
    by_band: dict[ProgressionBand, list[tuple[datetime.date, Ring]]] = {}
    for date, ring in dated:
        age = (latest_date - date).days
        band = band_for_age(age)
        if band is not None:
            by_band.setdefault(band, []).append((date, ring))
    banded: list[_BandedRings] = []
    for band_index, band in enumerate(PROGRESSION_BANDS):
        bucket = by_band.get(band)
        if bucket is None:
            continue
        band_rings = tuple(ring for _date, ring in bucket)
        geometry = shapely.union_all([ring.geometry for ring in band_rings])
        if geometry.is_empty:
            continue
        banded.append(
            _BandedRings(
                name=band.name,
                label=band_label(
                    band,
                    latest_date,
                    [date for date, _ring in bucket],
                ),
                rings=band_rings,
                band_index=band_index,
                geometry=geometry,
            ),
        )
    return tuple(banded)


def progression_bands(
    rings: typing.Sequence[Ring],
) -> tuple[ProgressionBandGeometry, ...]:
    """Return one growth band per day range *rings* cover, newest first.

    Each band is the union of the rings whose dates fall in the band's range, so a
    range with no rings contributes no band, and a fire with no rings yields none.
    Rings without an observation time cannot be dated and are left out.

    Args:
        rings: The fire's growth rings in chronological order.

    Returns:
        One band geometry per covered range, newest first.
    """
    return tuple(
        ProgressionBandGeometry(
            name=banded.name,
            label=banded.label,
            geometry=banded.geometry,
        )
        for banded in _banded_rings(rings)
    )


def progression_band_rings(
    rings: typing.Sequence[Ring],
) -> tuple[ProgressionBandRings, ...]:
    """Return one day range's rings per band *rings* cover, newest first.

    Each entry holds the individual rings whose dates fall in the band's range,
    so the output can group them into folders by day range while styling each ring
    by the band's color.

    Args:
        rings: The fire's growth rings in chronological order.

    Returns:
        One banded-rings entry per covered range, newest first.
    """
    return tuple(
        ProgressionBandRings(
            name=banded.name,
            label=banded.label,
            rings=banded.rings,
            band_index=banded.band_index,
        )
        for banded in _banded_rings(rings)
    )
