"""Tests for peri_scribe.presentation.folders."""

from __future__ import annotations

import hypothesis
import pytest

import peri_scribe.presentation.perimeters
import peri_scribe.presentation.views
import tests.helpers.factories.peri_scribe.presentation.views
import tests.helpers.strategies.peri_scribe.presentation.views


@hypothesis.given(
    perimeters=tests.helpers.strategies.peri_scribe.presentation.views.growth_histories(),
)
def test_fire_growth_matches_the_measurements_available_at_the_reference_time(
    perimeters: tuple[peri_scribe.presentation.perimeters.Perimeter, ...],
) -> None:
    now = tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME
    available = {
        item.observation_time: item.measured_area.m_as("acres")
        for item in perimeters
        if item.observation_time is not None and item.observation_time <= now
    }
    growth, percent = peri_scribe.presentation.views.fire_growth(
        tests.helpers.factories.peri_scribe.presentation.views.active_fire(
            "Generated",
            perimeters=perimeters,
        ),
        now,
    )
    if not available:
        assert (growth, percent) == (None, None)
        return
    cutoff = now - peri_scribe.presentation.views.FAST_GROWTH_LOOKBACK
    baseline_times = [time for time in available if time <= cutoff]
    baseline = available[max(baseline_times)] if baseline_times else 0
    expected = available[max(available)] - baseline
    assert growth is not None
    assert growth.m_as("acres") == pytest.approx(expected)
    if baseline > 0:
        assert percent is not None
        assert percent.m_as("percent") == pytest.approx(expected / baseline * 100)
    else:
        assert percent is None
