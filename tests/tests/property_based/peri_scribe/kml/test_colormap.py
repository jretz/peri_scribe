"""Tests for peri_scribe.kml.colormap."""

from __future__ import annotations

import dataclasses
import datetime

import hypothesis
import hypothesis.strategies

import peri_scribe.kml.colormap
import peri_scribe.perimeters.progression
import tests.helpers.strategies.peri_scribe.kml.colormap
from peri_scribe.units import units


@hypothesis.given(
    areas=hypothesis.strategies.lists(
        hypothesis.strategies.integers(1, 1000),
        min_size=1,
        max_size=20,
    ),
    data=hypothesis.strategies.data(),
)
def test_active_ring_window_finds_a_shortest_qualifying_run(
    areas: list[int],
    data: hypothesis.strategies.DataObject,
) -> None:
    threshold = data.draw(hypothesis.strategies.integers(1, sum(areas)))
    qualifying = [
        (start, end)
        for start in range(len(areas))
        for end in range(start, len(areas))
        if sum(areas[start : end + 1]) >= threshold
    ]
    shortest = min(end - start for start, end in qualifying)
    expected = {(start, end) for start, end in qualifying if end - start == shortest}
    assert (
        peri_scribe.kml.colormap.active_ring_window(
            [area * units.meters**2 for area in areas],
            threshold * units.meters**2,
        )
        in expected
    )


@hypothesis.given(
    rings=tests.helpers.strategies.peri_scribe.kml.colormap.ring_histories(),
    shift=hypothesis.strategies.integers(-365, 365),
    stretch=hypothesis.strategies.integers(1, 10),
)
def test_progression_ring_colors_preserves_colors_under_affine_time_changes(
    rings: list[peri_scribe.perimeters.progression.Ring],
    shift: int,
    stretch: int,
) -> None:
    base = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
    transformed = [
        dataclasses.replace(
            ring,
            observation_time=None
            if ring.observation_time is None
            else base
            + datetime.timedelta(days=shift)
            + (ring.observation_time - base) * stretch,
        )
        for ring in rings
    ]
    assert [
        color
        for _ring, color in peri_scribe.kml.colormap.progression_ring_colors(
            transformed,
        )
    ] == [
        color
        for _ring, color in peri_scribe.kml.colormap.progression_ring_colors(rings)
    ]


@hypothesis.given(
    rings=tests.helpers.strategies.peri_scribe.kml.colormap.ring_histories(),
    exponent=hypothesis.strategies.integers(-10, 10),
)
def test_progression_ring_colors_is_independent_of_absolute_area_scale(
    rings: list[peri_scribe.perimeters.progression.Ring],
    exponent: int,
) -> None:
    scaled = [
        dataclasses.replace(ring, area=ring.area * 2.0**exponent) for ring in rings
    ]
    assert [
        color
        for _ring, color in peri_scribe.kml.colormap.progression_ring_colors(scaled)
    ] == [
        color
        for _ring, color in peri_scribe.kml.colormap.progression_ring_colors(rings)
    ]
