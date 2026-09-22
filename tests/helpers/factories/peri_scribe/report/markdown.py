"""Build inputs for markdown tests."""

from __future__ import annotations

import datetime

import peri_scribe.models
import peri_scribe.presentation.descriptions
import peri_scribe.report.gathering
from measurement_units import units


REPORT_SECTION_COUNT = 6


GROWTH_SECTION_COUNT = 2


LOCATION_COLUMN_SECTION_COUNT = 2


def make_entry(
    name: str,
    *,
    identifier: str | None = None,
    description: peri_scribe.presentation.descriptions.FireDescription | None = None,
    area: float | None = None,
    percent_contained: float | None = None,
    discovery_time: datetime.datetime | None = None,
    score: int | None = None,
    growth: float | None = None,
    growth_percent: float | None = None,
    location: str | None = None,
) -> peri_scribe.report.gathering.FireReportEntry:
    """Return a report entry carrying only the requested facts.

    When no *description* is given one is built from the requested facts, mirroring how
    the gathering step pairs an entry with the fire's balloon description, so the
    details rows read from the same source the balloon reads.

    Args:
        name: The fire's name.
        identifier: The fire's identifier, or None.
        description: The fire's balloon description, or None to build one.
        area: The fire's latest area, or None.
        percent_contained: The fire's containment percentage, or None.
        discovery_time: The fire's discovery time, or None.
        score: The fire's score, or None.
        growth: The fire's acreage growth, or None.
        growth_percent: The fire's percent growth, or None.
        location: The fire's nearest-city location phrase, or None.

    Returns:
        An active fire entry carrying the requested facts.
    """
    if description is None:
        description = peri_scribe.presentation.descriptions.FireDescription(
            identifier=identifier,
            area=None if area is None else area * units.acres,
            percent_contained=percent_contained,
            discovery_time=discovery_time,
        )
    return peri_scribe.report.gathering.FireReportEntry(
        name=name,
        identifier=identifier,
        status=peri_scribe.models.FireStatus.ACTIVE,
        description=description,
        growth=None if growth is None else growth * units.acres,
        growth_percent=(
            None if growth_percent is None else growth_percent * units.percent
        ),
        score=score,
        location=location,
    )


LOCATION_COLUMN_SECTION_COUNT = 2
