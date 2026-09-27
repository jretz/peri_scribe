"""Translate exact policy inputs into source-attributed application reports."""

import dataclasses
import datetime
import itertools

import shapely

import peri_scribe.areas
import peri_scribe.incidents
from measurement_units import units


TIME = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Takeover:
    """Boundary inputs shared by the Lean definition and Python implementation."""

    mapped: int
    reported: int
    newer: bool
    baseline: int
    age: int
    confirmations: int

    def command(self) -> str:
        """Retain the exact integer inputs used in the proof's policy definition.

        Returns:
            An oracle request for this case.
        """
        return (
            f"takeover {self.mapped} {self.reported} {int(self.newer)} "
            f"{self.baseline} {self.age} {self.confirmations}"
        )


def takeover_cases() -> list[Takeover]:
    """Exercise each side of every policy boundary and report evidence requirement.

    Returns:
        Integral acreages and ages around the default policy's decision boundaries.
    """
    cases = []
    for mapped in (4, 100, 1_000):
        reported = {
            mapped,
            mapped + 9,
            mapped + 10,
            mapped * 5 // 4 - 1,
            mapped * 5 // 4,
            mapped * 2 - 1,
            mapped * 2,
            mapped * 2 + 1,
        }
        for value, age, confirmations in itertools.product(
            sorted(reported),
            (1, 86_399, 86_400, 259_199, 259_200, 259_201),
            range(4),
        ):
            cases.extend(
                Takeover(
                    mapped=mapped,
                    reported=value,
                    newer=True,
                    baseline=baseline,
                    age=age,
                    confirmations=confirmations,
                )
                for baseline in (-1, value - 1, value, value + 1)
            )
        cases.append(
            Takeover(
                mapped=mapped,
                reported=mapped * 3,
                newer=False,
                baseline=-1,
                age=259_200,
                confirmations=0,
            ),
        )
    return cases


def report(
    value: int,
    observed: datetime.datetime,
    *,
    confirmed: bool = False,
) -> peri_scribe.incidents.IncidentUpdate:
    """Preserve evidence timestamps independently of policy evaluation time.

    Args:
        value: Reported acreage.
        observed: The report's observation and, if confirmed, formal-report time.
        confirmed: Whether a formal report supports this measurement.

    Returns:
        An incident update with explicit measurement provenance.
    """
    return peri_scribe.incidents.IncidentUpdate(
        observation_time=observed,
        report_time=observed if confirmed else None,
        confirmed=confirmed,
        source="formal-conformance",
        source_file="reports.gpkg",
        serial=1,
        measurements={"incident_size": float(value)},
    )


def implementation_takeover(case: Takeover) -> bool:
    """Translate the model's confirmation count into distinct formal report times.

    Repeated copies of each report ensure duplicate publication cannot supply extra
    confirmation evidence.

    Args:
        case: Exact policy inputs to translate into implementation objects.

    Returns:
        The implementation's report takeover decision.
    """
    confirmations = tuple(
        report(
            case.mapped * 2,
            TIME + datetime.timedelta(microseconds=index + 1),
            confirmed=True,
        )
        for index in range(case.confirmations)
    )
    reports = (
        *(
            item
            for confirmation in confirmations
            for item in (confirmation, confirmation)
        ),
        report(
            case.reported,
            TIME + datetime.timedelta(seconds=int(case.newer)),
        ),
    )
    return peri_scribe.areas.report_can_take_over(
        peri_scribe.areas.Mapping(
            time=TIME,
            area=float(case.mapped) * units.acres,
            geometry=shapely.Polygon(),
            source_file="mapping.gpkg",
            surveyed=True,
        ),
        reports,
        TIME + datetime.timedelta(seconds=case.age),
        None if case.baseline < 0 else float(case.baseline),
        peri_scribe.areas.DEFAULT_POLICY,
    )
