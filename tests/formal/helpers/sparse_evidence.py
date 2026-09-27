"""Sparse and dated DataFrames exercise the proved fallback and visibility contract."""

import dataclasses
import datetime
import itertools
import math

import geopandas
import pandas as pd
import shapely

import peri_scribe.areas
import peri_scribe.geo.measurements
import peri_scribe.models
import peri_scribe.presentation.index
import tests.helpers.factories.geography
from measurement_units import units


MISSING = -99999999
ORIGIN = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Perimeter:
    """Usable geometry is independent from a row's supplied acreage."""

    measured: int | None
    supplied: int | None
    usable: bool = True


@dataclasses.dataclass(frozen=True, kw_only=True)
class Report:
    """Undated reported sizes retain zero and historical discovery/final evidence."""

    size: int | None = None
    discovery: int | None = None
    final: int | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class Case:
    """Selected dated mapping estimates can supersede every sparse fallback."""

    dated: tuple[int, ...] = ()
    perimeters: tuple[Perimeter, ...] = ()
    points: tuple[Report, ...] = ()
    incidents: tuple[Report, ...] = ()

    def command(self) -> str:
        """Encode evidence directly without reproducing the selection policy.

        Returns:
            A command evaluated by the proved Lean definitions.
        """
        perimeters = " ".join(
            f"{optional(row.measured if row.usable else None)},{optional(row.supplied)}"
            for row in self.perimeters
        )
        reports = [
            " ".join(
                f"{optional(row.size)},{optional(row.discovery)},{optional(row.final)}"
                for row in rows
            )
            for rows in (self.points, self.incidents)
        ]
        return (
            f"sparse {' '.join(map(str, self.dated))} | {perimeters} | "
            + " | ".join(reports)
        )


def optional(value: int | None) -> str:
    """Keep a missing value distinct from every signed integer.

    Args:
        value: An integral source measurement, or absent evidence.

    Returns:
        Its unambiguous oracle encoding.
    """
    return "n" if value is None else str(value)


def cases() -> tuple[Case, ...]:
    """Cross threshold boundaries with absence, zero, signs, shape loss, and dates.

    Returns:
        Sparse matrices and focused multi-observation chronological transitions.
    """
    values = (None, -1, 0, 1, 24, 25, 26, 100)
    result = [Case()]
    for measured, supplied, usable in itertools.product(values, values, (False, True)):
        result.append(
            Case(
                perimeters=(
                    Perimeter(measured=measured, supplied=supplied, usable=usable),
                ),
            ),
        )
    for current, historical in itertools.product(values, values):
        result.extend((
            Case(points=(Report(size=current, final=historical),)),
            Case(incidents=(Report(size=current, discovery=historical),)),
            Case(
                perimeters=(Perimeter(measured=None, supplied=current),),
                points=(Report(size=historical), Report()),
            ),
            Case(
                perimeters=(Perimeter(measured=historical, supplied=100),),
                points=(Report(size=current),),
            ),
        ))
    result.extend(
        Case(
            dated=dated,
            perimeters=(Perimeter(measured=100, supplied=1000),),
            points=(Report(size=200, discovery=500),),
            incidents=(Report(final=1000),),
        )
        for dated in ((1,), (24,), (25,), (100, 1), (1, 100), (25, 1))
    )
    result.extend((
        Case(
            perimeters=(
                Perimeter(measured=100, supplied=None),
                Perimeter(measured=1, supplied=None),
            ),
        ),
        Case(
            perimeters=(
                Perimeter(measured=1, supplied=None),
                Perimeter(measured=100, supplied=None),
            ),
        ),
        Case(points=(Report(size=100), Report(size=0))),
        Case(points=(Report(size=100), Report())),
    ))
    return tuple(result)


def report_frame(rows: tuple[Report, ...]) -> geopandas.GeoDataFrame:
    """Exercise real incident parsing without inventing dates for sparse evidence.

    Args:
        rows: Undated report records for one identified fire.

    Returns:
        The source frame with every optional area column represented.
    """
    return tests.helpers.factories.geography.geo_frame(
        {
            "fire_identifier": ["fire"] * len(rows),
            "fire_name": ["Fire"] * len(rows),
            "observation_time": [None] * len(rows),
            "incident_size": [row.size for row in rows],
            "discovery_acres": [row.discovery for row in rows],
            "final_acres": [row.final for row in rows],
        },
        [shapely.Point(-120, 40)] * len(rows),
    )


def frames(case: Case) -> tuple[geopandas.GeoDataFrame, ...]:
    """Dated fresh mappings exercise the complete selector before sparse fallback.

    Args:
        case: Raw source evidence and optional dated positive mappings.

    Returns:
        Perimeter, point, and independent incident frames for presentation.
    """
    rows = [
        {
            "fire_identifier": "fire",
            "fire_name": "Fire",
            "observation_time": None,
            "geometry": (
                shapely.box(-120.01, 40, -120, 40.01)
                if row.usable and row.measured is not None
                else shapely.Polygon()
            ),
            peri_scribe.geo.measurements.AREA_COLUMN: (
                None
                if row.measured is None
                else (row.measured * units.acres).m_as("meters ** 2")
            ),
            "area_acres": row.supplied,
        }
        for row in case.perimeters
    ]
    rows.extend(
        {
            "fire_identifier": "fire",
            "fire_name": "Fire",
            "observation_time": ORIGIN + datetime.timedelta(seconds=index + 1),
            "geometry": shapely.box(-120.01, 40, -120, 40.01),
            peri_scribe.geo.measurements.AREA_COLUMN: (value * units.acres).m_as(
                "meters ** 2",
            ),
            "area_acres": None,
            "source_subsource": "FIRIS",
        }
        for index, value in enumerate(case.dated)
    )
    perimeters = geopandas.GeoDataFrame(
        pd.DataFrame(
            rows,
            columns=[
                "fire_identifier",
                "fire_name",
                "observation_time",
                "geometry",
                peri_scribe.geo.measurements.AREA_COLUMN,
                "area_acres",
                "source_subsource",
            ],
        ),
        geometry="geometry",
        crs="EPSG:4326",
    )
    return perimeters, report_frame(case.points), report_frame(case.incidents)


def check(case: Case, expected: tuple[int, ...]) -> None:
    """Compare both area consumers and the real shared KMZ/report eligibility filter.

    Args:
        case: Source evidence supplied independently to Lean and Python.
        expected: Current area, historical area, and visibility computed by Lean.
    """
    perimeters, points, incidents = frames(case)
    history = peri_scribe.areas.prepare_history(perimeters, points, incidents)
    for actual, value in zip(
        (history.latest_area, history.historical_area),
        expected[:2],
        strict=True,
    ):
        if value == MISSING:
            assert actual is None, case
        else:
            assert actual is not None, case
            assert math.isclose(actual.m_as("acres"), value, abs_tol=1e-9), case
    index = peri_scribe.models.FireIndex(
        version="formal",
        fires=[
            peri_scribe.models.FireIndexEntry(
                name="Fire",
                identifier="fire",
                status="active",
                paths=[],
            ),
        ],
    )
    qualified = peri_scribe.presentation.index.area_qualified_index(
        index,
        perimeters,
        points,
        incidents,
    )
    assert bool(qualified.fires) == bool(expected[2]), case
