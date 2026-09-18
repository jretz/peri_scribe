"""Build inputs for colormap tests."""

from __future__ import annotations

import datetime

import shapely.geometry

import peri_scribe.perimeters.progression
from peri_scribe.units import units


def ring(
    side: float,
    observation_time: datetime.datetime | None = None,
    *,
    area: float = 0.0,
) -> peri_scribe.perimeters.progression.Ring:
    """Build a square growth ring of the given side at *observation_time*.

    Args:
        side: The ring's side length.
        observation_time: The ring's observation time, or None.
        area: The ring's area in square meters.

    Returns:
        The ring.
    """
    half = side / 2
    return peri_scribe.perimeters.progression.Ring(
        geometry=shapely.geometry.box(-half, -half, half, half),
        observation_time=observation_time,
        area=area * units.Unit("meters ** 2"),
    )


def utc(year: int, month: int, day: int) -> datetime.datetime:
    """Return an aware UTC datetime for the given calendar date.

    Args:
        year: The year.
        month: The month.
        day: The day.

    Returns:
        The datetime at 20:00 UTC.
    """
    return datetime.datetime(year, month, day, 20, 0, tzinfo=datetime.UTC)
