"""Provide data builders and stand-ins for colormap tests."""

from __future__ import annotations

import datetime

import shapely.geometry

import peri_scribe.kml.colormap
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
        area=area * units.meters**2,
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


MAX_COLOR_CHANNEL_ERROR = 6


def expected_rgb(rgb: tuple[float, float, float]) -> tuple[int, int, int]:
    """Return *rgb* on a 0 to 1 scale rounded to 8-bit components.

    Args:
        rgb: The color as (red, green, blue) components from 0 to 1.

    Returns:
        The color as (red, green, blue) components from 0 to 255.
    """
    return (round(rgb[0] * 255), round(rgb[1] * 255), round(rgb[2] * 255))


def tick_labels(strip: str) -> dict[int, int]:
    """Return each row's index and the tick label printed to its left.

    Args:
        strip: The colormap strip.

    Returns:
        The labelled rows' indices mapped to the values printed on them.
    """
    labels = {}
    for index, line in enumerate(strip.splitlines()):
        text = line.split("\x1b", 1)[0].strip()
        if text:
            labels[index] = int(text)
    return labels


def range_labels(strip: str) -> dict[int, int]:
    """Return each row's index and the used-range label printed to its right.

    Args:
        strip: The colormap strip.

    Returns:
        The labelled rows' indices mapped to the values printed on them.
    """
    labels = {}
    for index, line in enumerate(strip.splitlines()):
        suffix = line.rsplit(peri_scribe.kml.colormap.ANSI_RESET, 1)[-1]
        text = suffix.replace(peri_scribe.kml.colormap.USED_RANGE_MARKER, "").strip()
        if text:
            labels[index] = int(text)
    return labels
