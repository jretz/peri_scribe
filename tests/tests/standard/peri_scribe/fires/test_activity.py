"""Boundary and evidence regressions for cumulative fire activity."""

import dataclasses
import datetime
import math

import pytest

import peri_scribe.fires.activity
import peri_scribe.models
import tests.helpers.factories.peri_scribe.fires.activity
from measurement_units import units


@pytest.mark.parametrize(
    ("baseline", "growth", "active"),
    [
        (1_000.0, 10.0, False),
        (1_000.0, 10.01, True),
        (10_000.0, 50.0, False),
        (10_000.0, 50.01, True),
        (10_000.0, 49.99, False),
        (0.0, 11.0, True),
    ],
)
def test_active_status_short_thresholds_are_strict(
    baseline: float,
    growth: float,
    *,
    active: bool,
) -> None:
    reported = tests.helpers.factories.peri_scribe.fires.activity.observations([
        (-4, baseline),
        (-2, baseline + growth),
    ])
    result = peri_scribe.fires.activity.active_status(
        peri_scribe.models.FireStatus.ACTIVE,
        reported,
        (),
        tests.helpers.factories.peri_scribe.fires.activity.REFERENCE_TIME,
    )
    assert (result is peri_scribe.models.FireStatus.ACTIVE) is active


@pytest.mark.parametrize(
    ("baseline", "growth", "active"),
    [
        (4_000.0, 25.0, False),
        (4_000.0, 26.0, True),
        (1_000.0, 10.0, False),
        (1_000.0, 11.0, True),
        (2_000.0, 20.0, False),
        (2_000.0, 21.0, True),
        (2_500.0, 25.0, False),
        (0.0, 11.0, True),
    ],
)
def test_active_status_long_area_or_percentage_with_noise_floor(
    baseline: float,
    growth: float,
    *,
    active: bool,
) -> None:
    reported = tests.helpers.factories.peri_scribe.fires.activity.observations([
        (-8, baseline),
        (-4, baseline + growth),
    ])
    result = peri_scribe.fires.activity.active_status(
        peri_scribe.models.FireStatus.ACTIVE,
        reported,
        (),
        tests.helpers.factories.peri_scribe.fires.activity.REFERENCE_TIME,
    )
    assert (result is peri_scribe.models.FireStatus.ACTIVE) is active


@pytest.mark.parametrize("mapped", [False, True])
def test_active_status_either_stream_can_keep_active(*, mapped: bool) -> None:
    growing = tests.helpers.factories.peri_scribe.fires.activity.observations([
        (-8, 4_000),
        (-4, 4_028),
    ])
    quiet = tests.helpers.factories.peri_scribe.fires.activity.observations([
        (-20, 400_000),
    ])
    result = peri_scribe.fires.activity.active_status(
        peri_scribe.models.FireStatus.ACTIVE,
        quiet if mapped else growing,
        growing if mapped else quiet,
        tests.helpers.factories.peri_scribe.fires.activity.REFERENCE_TIME,
    )
    assert result is peri_scribe.models.FireStatus.ACTIVE


@pytest.mark.parametrize("samples", [[], [(1, 100)], [(-1, math.nan)]])
def test_active_status_unknown_dated_acreage_retains_active(
    samples: list[tuple[float, float]],
) -> None:
    result = peri_scribe.fires.activity.active_status(
        peri_scribe.models.FireStatus.ACTIVE,
        tests.helpers.factories.peri_scribe.fires.activity.observations(samples),
        (),
        tests.helpers.factories.peri_scribe.fires.activity.REFERENCE_TIME,
    )
    assert result is peri_scribe.models.FireStatus.ACTIVE


@pytest.mark.parametrize("age", [3, 4, 7, 30])
def test_active_status_old_unchanged_history_is_holding_without_fresh_update(
    age: int,
) -> None:
    result = peri_scribe.fires.activity.active_status(
        peri_scribe.models.FireStatus.ACTIVE,
        tests.helpers.factories.peri_scribe.fires.activity.observations([(-age, 100)]),
        (),
        tests.helpers.factories.peri_scribe.fires.activity.REFERENCE_TIME,
    )
    assert result is peri_scribe.models.FireStatus.HOLDING


def test_active_status_new_stream_has_only_three_days_of_grace() -> None:
    reference = tests.helpers.factories.peri_scribe.fires.activity.REFERENCE_TIME
    reported = tests.helpers.factories.peri_scribe.fires.activity.observations([
        (-3, 100),
    ])
    assert (
        peri_scribe.fires.activity.active_status(
            peri_scribe.models.FireStatus.ACTIVE,
            reported,
            (),
            reference - datetime.timedelta(microseconds=1),
        )
        is peri_scribe.models.FireStatus.ACTIVE
    )
    assert (
        peri_scribe.fires.activity.active_status(
            peri_scribe.models.FireStatus.ACTIVE,
            reported,
            (),
            reference,
        )
        is peri_scribe.models.FireStatus.HOLDING
    )


def test_active_status_inactive_agency_takes_precedence_over_growth() -> None:
    growing = tests.helpers.factories.peri_scribe.fires.activity.observations([
        (-8, 100),
        (-1, 1_000),
    ])
    assert (
        peri_scribe.fires.activity.active_status(
            peri_scribe.models.FireStatus.INACTIVE,
            growing,
            growing,
            tests.helpers.factories.peri_scribe.fires.activity.REFERENCE_TIME,
        )
        is peri_scribe.models.FireStatus.INACTIVE
    )


def test_growth_window_counts_rebounds_once_and_ignores_future() -> None:
    observations = tests.helpers.factories.peri_scribe.fires.activity.observations([
        (-8, 4_000),
        (-6, 3_900),
        (-4, 4_000),
        (-1, 4_004),
        (1, 20_000),
    ])
    result = peri_scribe.fires.activity.growth_window(
        observations,
        tests.helpers.factories.peri_scribe.fires.activity.REFERENCE_TIME,
        datetime.timedelta(days=7),
    )
    assert result.baseline_area == 4_000 * units.acres
    assert result.growth == 4 * units.acres


def test_growth_window_retains_peak_before_downward_correction() -> None:
    observations = tests.helpers.factories.peri_scribe.fires.activity.observations([
        (-8, 4_000),
        (-6, 4_100),
        (-1, 3_900),
    ])
    result = peri_scribe.fires.activity.growth_window(
        observations,
        tests.helpers.factories.peri_scribe.fires.activity.REFERENCE_TIME,
        datetime.timedelta(days=7),
    )
    assert result.growth == 100 * units.acres


def test_growth_window_sorts_and_uses_last_same_time_correction() -> None:
    observations = tests.helpers.factories.peri_scribe.fires.activity.observations([
        (-1, 110),
        (-7, 90),
        (-7, 100),
        (-2, 105),
    ])
    result = peri_scribe.fires.activity.growth_window(
        observations,
        tests.helpers.factories.peri_scribe.fires.activity.REFERENCE_TIME,
        datetime.timedelta(days=7),
    )
    assert result.baseline_area == 100 * units.acres
    assert result.growth == 10 * units.acres


def test_visible_observations_filters_invalid_and_normalizes_units_and_time() -> None:
    observations = tests.helpers.factories.peri_scribe.fires.activity.observations([
        (-8, -1),
        (-7, math.inf),
        (-6, math.nan),
        (-4, 100),
    ])
    last = dataclasses.replace(
        observations[-1],
        time=observations[-1].time.replace(tzinfo=None),
        area=observations[-1].area.to("meters**2"),
    )
    assert peri_scribe.fires.activity.visible_observations(
        (*observations[:-1], last),
        tests.helpers.factories.peri_scribe.fires.activity.REFERENCE_TIME,
    ) == (observations[-1],)


def test_active_status_sisi_october_12_retains_cumulative_growth() -> None:
    reported = tests.helpers.factories.peri_scribe.fires.activity.observations([
        (-7, 4_343),
        (-3, 4_411),
        (-1, 4_430),
    ])
    assert (
        peri_scribe.fires.activity.active_status(
            peri_scribe.models.FireStatus.ACTIVE,
            reported,
            (),
            tests.helpers.factories.peri_scribe.fires.activity.REFERENCE_TIME,
        )
        is peri_scribe.models.FireStatus.ACTIVE
    )
