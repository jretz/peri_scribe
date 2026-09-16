"""Build inputs for areas tests."""

from __future__ import annotations

import datetime
import json
import math
import typing

import pandas as pd
import shapely

import tests.helpers.factories.geography
import tests.helpers.factories.time
from peri_scribe.units import units


if typing.TYPE_CHECKING:
    import geopandas


def time(days: float) -> datetime.datetime:
    """Give policy tests a shared clock with support for intraday deadlines.

    Args:
        days: Elapsed days from midnight UTC on September 1, 2026.

    Returns:
        The corresponding timezone-aware observation time.
    """
    return tests.helpers.factories.time.utc(2026, 9, 1, 0) + datetime.timedelta(
        days=days,
    )


def mappings(entries: list[tuple[float, float]]) -> geopandas.GeoDataFrame:
    """Isolate area policy with explicit measurements and comparable footprints.

    Args:
        entries: Observation day offsets paired with stored acreage measurements.

    Returns:
        Synthetic perimeter rows whose stored areas support exact threshold checks and
        whose changing square footprints support survey-freshness checks.
    """
    return tests.helpers.factories.geography.geo_frame(
        {
            "observation_time": [time(day) for day, _area in entries],
            "geometry_area_square_meters": [
                (area * units.acres).m_as("meters**2") for _day, area in entries
            ],
        },
        [
            shapely.box(
                -120,
                35,
                -120 + math.sqrt(area) / 1000,
                35 + math.sqrt(area) / 1000,
            )
            for _day, area in entries
        ],
    )


def reports(
    entries: list[tuple[float, float]],
    *,
    confirmed: bool = False,
) -> pd.DataFrame:
    """Make formal-report confirmation explicit in area-selection scenarios.

    Args:
        entries: Observation day offsets paired with reported acreage.
        confirmed: Whether each observation carries a distinct formal report time.

    Returns:
        Incident rows with serialized dispatch or ICS-209 source metadata.
    """
    return pd.DataFrame([
        {
            "observation_time": time(day),
            "incident_size": area,
            "source_attributes": json.dumps({
                "ModifiedBySystem": "ics209" if confirmed else "dispatch",
                "ICS209ReportDateTime": time(day).isoformat() if confirmed else None,
            }),
        }
        for day, area in entries
    ])
