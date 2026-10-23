"""Compare raw acreage timelines with the proved cumulative activity policy."""

import datetime
import itertools
import math

import peri_scribe.fires.activity
import peri_scribe.models
import tests.formal.helpers.oracle
from measurement_units import units


ORIGIN = datetime.datetime(2026, 10, 22, tzinfo=datetime.UTC)
DAY = 86400
SHORT_WINDOW = 3 * DAY
LONG_WINDOW = 7 * DAY
HISTORY_COUNT = 1219


def histories() -> tuple[tuple[tuple[int, int], ...], ...]:
    """Vary ordering, corrected peaks, strict thresholds, and both window cutoffs.

    Returns:
        Raw elapsed-second and exact-acre tuples, before timeline selection.
    """
    result: list[tuple[tuple[int, int], ...]] = [()]
    for times, areas in itertools.product(
        (
            (-LONG_WINDOW - 1, -SHORT_WINDOW - 1, 0),
            (-LONG_WINDOW, -SHORT_WINDOW, 0),
            (-LONG_WINDOW + 1, -SHORT_WINDOW + 1, 1),
            (0, -SHORT_WINDOW, -LONG_WINDOW),
            (-SHORT_WINDOW, 0, 0),
            (-SHORT_WINDOW - 1, -1, -1),
            (1, 2, 3),
            (-LONG_WINDOW, -LONG_WINDOW, -SHORT_WINDOW),
        ),
        itertools.product((0, 1000, 1010, 1011, 1026), repeat=3),
    ):
        result.append(tuple(zip(times, areas, strict=True)))
    for baseline, growth in itertools.product(
        (0, 100, 1000, 2000, 2200, 2500, 2600, 4000, 10000),
        (0, 1, 10, 11, 19, 20, 21, 25, 26, 27, 50, 100),
    ):
        result.extend(
            (
                ((-LONG_WINDOW, baseline), (0, baseline + growth)),
                (
                    (-LONG_WINDOW, baseline),
                    (-SHORT_WINDOW, baseline + growth),
                    (0, baseline + growth),
                ),
            ),
        )
    result.extend(
        (
            ((-LONG_WINDOW, 4000), (-2 * DAY, 3900), (-DAY, 4000), (0, 4004)),
            ((-LONG_WINDOW, 1000), (-DAY, 1100), (-DAY, 1000), (0, 1000)),
        ),
    )
    return tuple(result)


def observations(
    rows: tuple[tuple[int, int], ...],
    *,
    metric: bool = False,
) -> tuple[peri_scribe.fires.activity.AreaObservation, ...]:
    """Preserve raw occurrence order and supply real timestamps and unit quantities.

    Args:
        rows: Independent exact source fixtures.
        metric: Whether to pass equivalent square-meter quantities.

    Returns:
        Production observation values before normalization and selection.
    """
    return tuple(
        peri_scribe.fires.activity.AreaObservation(
            time=ORIGIN + datetime.timedelta(seconds=time),
            area=(area * units.acres).to("meter ** 2")
            if metric
            else area * units.acres,
        )
        for time, area in rows
    )


def encoded(rows: tuple[tuple[int, int], ...]) -> str:
    """Transport raw samples without making any timeline decisions in Python.

    Args:
        rows: Independent exact source fixtures.

    Returns:
        The Lean request's source occurrence section.
    """
    return " ".join(f"{time},{area}" for time, area in rows)


def check_windows() -> None:
    """Check both real window selections against complete executable Lean timelines."""
    cases = tuple(itertools.product(histories(), (SHORT_WINDOW, LONG_WINDOW)))
    expected = tests.formal.helpers.oracle.evaluate(
        [f"window 0 {width} | {encoded(rows)}" for rows, width in cases],
        executable="oracleActivity",
    )
    for (rows, width), (baseline, growth) in zip(cases, expected, strict=True):
        actual = peri_scribe.fires.activity.growth_window(
            observations(rows),
            ORIGIN,
            datetime.timedelta(seconds=width),
        )
        if baseline == -1:
            assert actual.baseline_area is None
            assert actual.growth.m_as("acres") == 0
        else:
            assert actual.baseline_area is not None
            assert actual.baseline_area.m_as("acres") == baseline
            assert actual.growth.m_as("acres") == growth


def check_statuses() -> None:
    """Check source priority, independent streams, grace, and cumulative routes."""
    cases = tuple(itertools.product(histories(), (False, True), (False, True)))
    expected = tests.formal.helpers.oracle.evaluate(
        [
            f"status {int(source_active)} 0 | "
            + (f"{encoded(rows)} | " if reported else f" | {encoded(rows)}")
            for rows, source_active, reported in cases
        ],
        executable="oracleActivity",
    )
    statuses = (
        peri_scribe.models.FireStatus.INACTIVE,
        peri_scribe.models.FireStatus.ACTIVE,
        peri_scribe.models.FireStatus.HOLDING,
    )
    for (rows, source_active, reported), (status,) in zip(cases, expected, strict=True):
        measured = observations(rows)
        actual = peri_scribe.fires.activity.active_status(
            peri_scribe.models.FireStatus.ACTIVE
            if source_active
            else peri_scribe.models.FireStatus.INACTIVE,
            measured if reported else (),
            () if reported else measured,
            ORIGIN,
        )
        assert actual is statuses[status], (rows, source_active, reported)


def check_independent_streams() -> None:
    """Keep acreage bases separate while either source establishes growth."""
    cases = (
        (
            ((-LONG_WINDOW, 4000), (0, 4000)),
            ((-LONG_WINDOW, 100), (0, 100)),
        ),
        (
            ((-LONG_WINDOW, 4000), (0, 4000)),
            ((-LONG_WINDOW, 100), (0, 111)),
        ),
        (
            ((-LONG_WINDOW, 100), (0, 111)),
            ((-LONG_WINDOW, 4000), (0, 4000)),
        ),
        (
            ((-LONG_WINDOW, 4000), (-SHORT_WINDOW, 4026), (0, 4026)),
            ((-LONG_WINDOW, 2000), (0, 2000)),
        ),
    )
    expected = tests.formal.helpers.oracle.evaluate(
        [
            f"status 1 0 | {encoded(reported)} | {encoded(mapped)}"
            for reported, mapped in cases
        ],
        executable="oracleActivity",
    )
    for (reported, mapped), (status,) in zip(cases, expected, strict=True):
        actual = peri_scribe.fires.activity.active_status(
            peri_scribe.models.FireStatus.ACTIVE,
            observations(reported),
            observations(mapped),
            ORIGIN,
        )
        assert (actual is peri_scribe.models.FireStatus.ACTIVE) == (status == 1)


def check_unit_adapter() -> None:
    """Exercise equivalent metric input away from strict threshold boundaries."""
    rows = ((-LONG_WINDOW, 4000), (-SHORT_WINDOW, 4100), (0, 4117))
    for width in (SHORT_WINDOW, LONG_WINDOW):
        acres = peri_scribe.fires.activity.growth_window(
            observations(rows),
            ORIGIN,
            datetime.timedelta(seconds=width),
        )
        metric = peri_scribe.fires.activity.growth_window(
            observations(rows, metric=True),
            ORIGIN,
            datetime.timedelta(seconds=width),
        )
        assert acres.baseline_area is not None
        assert metric.baseline_area is not None
        assert math.isclose(
            acres.baseline_area.m_as("acres"),
            metric.baseline_area.m_as("acres"),
        )
        assert math.isclose(acres.growth.m_as("acres"), metric.growth.m_as("acres"))
