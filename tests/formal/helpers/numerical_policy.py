"""Exercise real quantity decisions against integer binary64 arithmetic in Lean."""

import dataclasses
import datetime
import itertools
import math

import numpy as np
import shapely.geometry

import peri_scribe.areas
import peri_scribe.fires.scoring
import peri_scribe.incidents
import peri_scribe.publication
import tests.formal.helpers.publication_evidence
from measurement_units import units


SCALE = 1 << 1074
BASE = datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC)
AREA_UNITS = ("meter ** 2", "acre", "hectare", "foot ** 2", "mile ** 2")


def integer(value: float) -> int:
    """Encode every finite bit value without rounding away fractional evidence.

    Args:
        value: A finite binary64 number, with either zero sign permitted.

    Returns:
        Its exact integer multiple of the least positive subnormal.
    """
    numerator, denominator = float(value).as_integer_ratio()
    return numerator * (SCALE // denominator)


def arguments(*values: float) -> str:
    """Keep all numeric operands on one exact scale.

    Args:
        values: Raw finite quantities or policy constants.

    Returns:
        Whitespace-separated exact integers for the compiled oracle.
    """
    return " ".join(str(integer(value)) for value in values)


def neighbors(value: float) -> tuple[float, ...]:
    """Expose both sides of a threshold without inventing a decimal epsilon.

    Args:
        value: The finite boundary of interest.

    Returns:
        The boundary and its immediately adjacent binary64 values.
    """
    return math.nextafter(value, -math.inf), value, math.nextafter(value, math.inf)


def arithmetic_cases() -> list[tuple[float, float]]:
    """Cover binade transitions, cancellation, halfway ties, and subnormal underflow.

    Returns:
        Operand pairs whose modeled arithmetic results remain finite.
    """
    points = (
        0.0,
        -0.0,
        math.ulp(0.0),
        -math.ulp(0.0),
        *neighbors(float.fromhex("0x1p-1022")),
        *neighbors(0.5),
        *neighbors(1.0),
        *neighbors(2.0),
        -1.0,
        1.25,
        1e-12,
        1e12,
    )
    candidates = list(itertools.product(points, repeat=2))
    generator = np.random.default_rng(20261004)
    candidates.extend(
        (
            math.ldexp(generator.uniform(-2, 2), int(generator.integers(-1073, 1023))),
            math.ldexp(generator.uniform(-2, 2), int(generator.integers(-1073, 1023))),
        )
        for _ in range(1600)
    )
    return [
        (left, right)
        for left, right in candidates
        if all(
            math.isfinite(value)
            for value in (left - right, left * right, left / right if right else 0.0)
        )
    ]


@dataclasses.dataclass(frozen=True, kw_only=True)
class Publication:
    """Retain the quantity's original unit through the real publication gate."""

    current: float
    previous: float
    threshold: float
    unit: str

    def command(self) -> str:
        """Pass unit metadata and raw operands without evaluating the decision.

        Returns:
            A request for rounded conversion, subtraction, and tolerance comparison.
        """
        factor = (1.0 * units(self.unit)).m_as("meter ** 2")
        return "publish|" + arguments(
            self.current,
            self.previous,
            self.threshold,
            factor,
            1e-12,
        )

    def result(self) -> tuple[int, int, int]:
        """Read the complete real numerical result, including signed evidence.

        Returns:
            Publication eligibility, exact change, and converted threshold.
        """
        current = (
            tests.formal.helpers.publication_evidence
            .Mapping(
                identity=0,
            )
            .production()
            .model_copy(update={"area_square_meters": self.current})
        )
        previous = current.model_copy(update={"area_square_meters": self.previous})
        threshold = peri_scribe.publication.Threshold(
            area=self.threshold * units(self.unit),
            interval=datetime.timedelta(minutes=5),
        )
        result = peri_scribe.publication.mapping_decision(
            {
                "fire": (
                    current,
                    peri_scribe.publication.PublishedFire(
                        identifiers=("fire",),
                        name="Fire",
                        mapping=previous,
                    ),
                ),
            },
            threshold,
        )
        return (
            int(result.proceed),
            integer(result.change.m_as("meter ** 2")),
            integer(threshold.area.m_as("meter ** 2")),
        )


def publications() -> list[Publication]:
    """Distinguish literal equality from tolerance admission and loss of small changes.

    Returns:
        Both growth and shrinkage around threshold and tolerance edges in five units.
    """
    result = []
    for unit, threshold, previous in itertools.product(
        AREA_UNITS,
        (0.0, 0.1, 1.0, 10.0, 1000.125),
        (0.0, 100.25, 1e12),
    ):
        boundary = (threshold * units(unit)).m_as("meter ** 2")
        for edge in (boundary, boundary * (1 - 1e-12), boundary * (1 - 2e-12)):
            for change in neighbors(edge):
                if change < 0:
                    continue
                for current in neighbors(previous + change):
                    if current >= 0:
                        result.extend((
                            Publication(
                                current=current,
                                previous=previous,
                                threshold=threshold,
                                unit=unit,
                            ),
                            Publication(
                                current=previous,
                                previous=current,
                                threshold=threshold,
                                unit=unit,
                            ),
                        ))
    return result


def report(
    value: float,
    offset: int,
    *,
    confirmed: bool,
) -> peri_scribe.incidents.IncidentUpdate:
    """Make corroborating report times independent of the area arithmetic.

    Args:
        value: Incident acreage in the source's declared unit.
        offset: Seconds after the mapping, or zero for a simultaneous report.
        confirmed: Whether the source supplies formal confirmation.

    Returns:
        A real reconciled update for the production policy entry point.
    """
    time = BASE + datetime.timedelta(seconds=offset)
    return peri_scribe.incidents.IncidentUpdate(
        observation_time=time,
        report_time=time if confirmed else None,
        confirmed=confirmed,
        source="wfigs_location",
        source_file="report.gpkg",
        serial=offset,
        measurements={"incident_size": value},
    )


@dataclasses.dataclass(frozen=True, kw_only=True)
class Takeover:
    """Keep units, temporal eligibility, and confirmation counts separate."""

    mapped: float
    unit: str
    reported: float
    baseline: float | None
    age: int
    confirmations: int
    newer: bool = True

    def command(self) -> str:
        """Preserve multiplication-before-conversion at the ratio boundary.

        Returns:
            Raw quantity magnitudes, conversion facts, and evidence attributes.
        """
        factor = (1.0 * units(self.unit)).m_as("acre")
        report_factor = (
            1.0 if self.unit == "acre" else (1.0 * units.acre).m_as("meter ** 2")
        )
        mapped_factor = (
            1.0 if self.unit == "acre" else (1.0 * units(self.unit)).m_as("meter ** 2")
        )
        return (
            "takeover|"
            + arguments(
                self.mapped,
                factor,
                self.reported,
                report_factor,
                mapped_factor,
                self.baseline or 0.0,
                10.0,
                1.25,
                2.0,
            )
            + f" {int(self.baseline is not None)} {int(self.newer)}"
            f" {self.age} {self.confirmations}"
        )

    def result(self) -> bool:
        """Run the actual report policy with distinct confirmations and mixed units.

        Returns:
            Whether the accepted report can replace the mapped estimate.
        """
        records = tuple(
            report(
                self.reported,
                (index + 1) if self.newer else 0,
                confirmed=self.confirmations > 0,
            )
            for index in range(max(1, self.confirmations))
        )
        mapping = peri_scribe.areas.Mapping(
            time=BASE,
            area=self.mapped * units(self.unit),
            geometry=shapely.geometry.box(0, 0, 1, 1),
            source_file="mapping.gpkg",
            surveyed=True,
        )
        return peri_scribe.areas.report_can_take_over(
            mapping,
            records,
            BASE + datetime.timedelta(seconds=self.age),
            self.baseline,
            peri_scribe.areas.DEFAULT_POLICY,
        )


def takeovers() -> list[Takeover]:
    """Cross fractional growth boundaries with both temporal routes and unit choices.

    Returns:
        Complete takeover cases including blocked baselines and simultaneous reports.
    """
    result = []
    for unit, mapped, age, confirmations in itertools.product(
        AREA_UNITS,
        (0.125, 40.25, 1000.125),
        (86399, 86400, 259199, 259200),
        (0, 1, 2),
    ):
        quantity = mapped * units(unit)
        edges = (
            quantity.m_as("acre") + 10.0,
            (quantity * 1.25).m_as("acre"),
            (quantity * 2.0).m_as("acre"),
        )
        for edge in edges:
            result.extend(
                Takeover(
                    mapped=mapped,
                    unit=unit,
                    reported=value,
                    baseline=None,
                    age=age,
                    confirmations=confirmations,
                )
                for value in neighbors(edge)
            )
    selected = result[::41]
    for case in selected:
        result.extend((
            dataclasses.replace(case, baseline=case.reported),
            dataclasses.replace(
                case,
                baseline=math.nextafter(case.reported, -math.inf),
            ),
            dataclasses.replace(case, newer=False),
        ))
    return result


def corrections() -> list[tuple[float, float, bool]]:
    """Expose the strict ratio and inclusive absolute decrease boundaries together.

    Returns:
        Nonnegative previous/current acreages with optional confirmation.
    """
    return [
        (previous, current, confirmed)
        for previous in (10.125, 40.25, 100.125, 1e12)
        for edge in (previous - 10.0, previous / 1.25)
        for current in neighbors(edge)
        for confirmed in (False, True)
    ]


def corrected(previous: float, current: float, *, confirmed: bool) -> bool:
    """Observe acceptance without reimplementing its numerical decisions.

    Args:
        previous: The first accepted acreage.
        current: The candidate correction.
        confirmed: Whether formal reporting supports the correction.

    Returns:
        Whether both source observations survive the production filter.
    """
    rows = (
        report(previous, 1, confirmed=True),
        report(current, 2, confirmed=confirmed),
    )
    return len(
        peri_scribe.areas.accepted_reports(rows, peri_scribe.areas.DEFAULT_POLICY),
    ) == len(rows)


def tier_cases() -> list[
    tuple[float, tuple[peri_scribe.fires.scoring.SignalTier, ...]]
]:
    """Use exact adjacent floats at every configured scoring boundary.

    Returns:
        Values and their applicable ordered tier tables.
    """
    return [
        (value, tiers)
        for tiers in (
            peri_scribe.fires.scoring.SIZE_TIERS,
            peri_scribe.fires.scoring.GROWTH_TIERS,
            peri_scribe.fires.scoring.FIRST_MAPPING_TIERS,
            peri_scribe.fires.scoring.BUILDING_COUNT_TIERS,
        )
        for tier in tiers
        for value in (*neighbors(tier.threshold), 0.125, 0.0)
    ]
