"""Dated evidence exercises the complete area selector against its proved fold."""

import dataclasses
import datetime
import itertools

import numpy as np
import pandas as pd
import shapely

import peri_scribe.areas
import peri_scribe.geo.measurements
import peri_scribe.incidents
import tests.formal.helpers.areas
import tests.formal.helpers.generation
from measurement_units import units


@dataclasses.dataclass(frozen=True, kw_only=True)
class Mapping:
    """Integral evidence separates freshness policy from geodesic measurement."""

    time: int
    area: int
    provenance: int
    surveyed: bool


@dataclasses.dataclass(frozen=True, kw_only=True)
class Report:
    """Distinct observation and confirmation clocks expose duplicate confirmations."""

    time: int
    area: int
    provenance: int
    confirmation: int = -1


@dataclasses.dataclass(frozen=True, kw_only=True)
class History:
    """One complete history preserves event ordering and source-file identity."""

    mappings: tuple[Mapping, ...]
    reports: tuple[Report, ...]

    def command(self) -> str:
        """Encode observations without performing any area-policy calculation.

        Returns:
            An oracle command preserving every supplied field.
        """
        mappings = " ".join(
            f"{item.time},{item.area},{item.provenance},{int(item.surveyed)}"
            for item in self.mappings
        )
        reports = " ".join(
            f"{item.time},{item.area},{item.provenance},{item.confirmation}"
            for item in self.reports
        )
        return f"area {mappings} | {reports}"


def cases() -> list[History]:
    """Cover takeover, renewal, correction, timestamp ties, and deadline-only events.

    Returns:
        Explicit policy boundaries plus reproducible varied complete histories.
    """
    result = [History(mappings=(), reports=())]
    for value, final_time, renew, confirmation in itertools.product(
        (40, 109, 110, 124, 125, 126, 199, 200, 201),
        (86_399, 86_400, 86_401, 259_199, 259_200, 259_201, 345_600),
        (False, True),
        (-1, 1),
    ):
        result.append(
            History(
                mappings=(
                    Mapping(time=0, area=100, provenance=0, surveyed=True),
                    Mapping(
                        time=final_time,
                        area=80,
                        provenance=1,
                        surveyed=renew,
                    ),
                ),
                reports=(
                    Report(time=1, area=value, provenance=2, confirmation=confirmation),
                    Report(time=2, area=value, provenance=3, confirmation=confirmation),
                ),
            ),
        )
    generator = np.random.default_rng(20260926)
    times = (0, 1, 86_399, 86_400, 86_401, 172_800, 259_200, 345_600, 432_000)
    for _ in range(300):
        mappings = tuple(
            Mapping(
                time=time,
                area=tests.formal.helpers.generation.choose(
                    generator,
                    (40, 100, 120, 160, 240),
                ),
                provenance=index,
                surveyed=index == 0
                or tests.formal.helpers.generation.choose(generator, (True, False)),
            )
            for index, time in enumerate(
                sorted(
                    tests.formal.helpers.generation.choose(generator, times)
                    for _ in range(int(generator.integers(5)))
                ),
            )
        )
        reports = tuple(
            Report(
                time=time,
                area=tests.formal.helpers.generation.choose(
                    generator,
                    (0, 39, 40, 99, 100, 125, 200, 201, 400),
                ),
                provenance=10 + index,
                confirmation=tests.formal.helpers.generation.choose(
                    generator,
                    (-2, -1, 0, 1, 2, 3),
                ),
            )
            for index, time in enumerate(
                sorted(
                    tests.formal.helpers.generation.choose(generator, times)
                    for _ in range(int(generator.integers(6)))
                ),
            )
        )
        result.append(History(mappings=mappings, reports=reports))
    return result


def implementation(history: History) -> tuple[peri_scribe.areas.AreaEstimate, ...]:
    """Exercise mapping preparation and report acceptance in the production selector.

    Args:
        history: Exact chronological observations with integral acreage.

    Returns:
        The production selector's complete source-attributed history.
    """
    origin = tests.formal.helpers.areas.TIME
    geometry = shapely.box(-120.01, 40, -120, 40.01)
    perimeters = pd.DataFrame([
        {
            "observation_time": origin + datetime.timedelta(seconds=item.time),
            "source_file": str(item.provenance),
            "source_subsource": "FIRIS" if item.surveyed else "WFIGS",
            "geometry": geometry,
            peri_scribe.geo.measurements.AREA_COLUMN: (item.area * units.acres).m_as(
                "meters ** 2",
            ),
        }
        for item in history.mappings
    ])
    updates = tuple(
        peri_scribe.incidents.IncidentUpdate(
            observation_time=origin + datetime.timedelta(seconds=item.time),
            report_time=(
                origin + datetime.timedelta(seconds=item.confirmation)
                if item.confirmation >= 0
                else None
            ),
            confirmed=item.confirmation != -1,
            source="formal",
            source_file=str(item.provenance),
            serial=index,
            measurements={"incident_size": float(item.area)},
        )
        for index, item in enumerate(history.reports)
    )
    return peri_scribe.areas.area_history(perimeters, pd.DataFrame(), updates=updates)
