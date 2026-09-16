"""Tests for peri_scribe.kml.tour."""

from __future__ import annotations

import datetime

import hypothesis
import pytest

import peri_scribe.kml.tour
import tests.helpers.peri_scribe.kml.parsing
import tests.helpers.peri_scribe.kml.tour
import tests.helpers.strategies.peri_scribe.kml.tour


@hypothesis.given(times=tests.helpers.strategies.peri_scribe.kml.tour.ring_times())
def test_progression_tour_preserves_elapsed_time_within_playback_budget(
    times: list[datetime.datetime | None],
) -> None:
    tour = tests.helpers.peri_scribe.kml.tour.rendered_tour(times)
    waits = tests.helpers.peri_scribe.kml.parsing.tour_primitives(
        tour,
        tests.helpers.peri_scribe.kml.parsing.gx_tag("Wait"),
    )
    durations = [
        tests.helpers.peri_scribe.kml.parsing.wait_duration(wait) for wait in waits
    ]
    assert len(durations) == len(times)
    assert all(duration >= 0 for duration in durations)
    if not times:
        return
    assert durations[-1] == peri_scribe.kml.tour.FINAL_TOUR_WAIT.m_as("seconds")
    observed = [time for time in times if time is not None]
    days = (observed[-1] - observed[0]) / datetime.timedelta(days=1) if observed else 0
    expected = min(
        days * peri_scribe.kml.tour.TOUR_PLAYBACK_RATE,
        peri_scribe.kml.tour.MAXIMUM_TOUR_PLAYBACK.m_as("seconds"),
    )
    assert sum(durations[:-1]) == pytest.approx(expected, rel=1e-12, abs=1e-12)


@hypothesis.given(times=tests.helpers.strategies.peri_scribe.kml.tour.ring_times())
def test_progression_tour_reveals_exactly_one_more_ring_per_step(
    times: list[datetime.datetime | None],
) -> None:
    tour = tests.helpers.peri_scribe.kml.tour.rendered_tour(times)
    updates = tests.helpers.peri_scribe.kml.parsing.tour_primitives(
        tour,
        tests.helpers.peri_scribe.kml.parsing.gx_tag("AnimatedUpdate"),
    )
    states = [
        tests.helpers.peri_scribe.kml.parsing.update_visibility_by_target(update)
        for update in updates
    ]
    assert len(states) == len(times)
    targets = list(states[0]) if states else []
    assert len(targets) == len(times)
    for revealed, state in enumerate(states, start=1):
        assert set(state) == set(targets)
        assert set(state.values()) <= {0, 1}
        assert {target for target, visible in state.items() if visible} == set(
            targets[:revealed],
        )
