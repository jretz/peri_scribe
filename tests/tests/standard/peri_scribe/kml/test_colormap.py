"""Tests for peri_scribe.kml.colormap."""

from __future__ import annotations

import datetime

import pytest

import peri_scribe.kml.colormap
import tests.helpers.factories.peri_scribe.kml.colormap
import tests.helpers.peri_scribe.kml.colormap
from peri_scribe.units import units


def test_turbo_colormap_keeps_the_full_table() -> None:
    assert len(peri_scribe.kml.colormap.turbo_colormap_256) == (
        peri_scribe.kml.colormap.TURBO_TRIM_FROM_START
        + len(peri_scribe.kml.colormap.TURBO_RAMP)
        + peri_scribe.kml.colormap.TURBO_TRIM_FROM_END
    )
    assert peri_scribe.kml.colormap.turbo_colormap_256[0] == (0.18995, 0.07176, 0.23217)
    assert peri_scribe.kml.colormap.turbo_colormap_256[-1] == (
        0.47960,
        0.01583,
        0.01055,
    )


def test_turbo_colormap_is_the_trimmed_ramp() -> None:
    assert (
        peri_scribe.kml.colormap.TURBO_RAMP[0]
        == (
            peri_scribe.kml.colormap.turbo_colormap_256[
                peri_scribe.kml.colormap.TURBO_TRIM_FROM_START
            ]
        )
    )
    assert (
        peri_scribe.kml.colormap.TURBO_RAMP[-1]
        == (
            peri_scribe.kml.colormap.turbo_colormap_256[
                -(peri_scribe.kml.colormap.TURBO_TRIM_FROM_END + 1)
            ]
        )
    )


def test_turbo_at_interpolates_between_entries() -> None:
    first = peri_scribe.kml.colormap.TURBO_RAMP[0]
    second = peri_scribe.kml.colormap.TURBO_RAMP[1]
    midpoint = tuple(
        (lower + higher) / 2 for lower, higher in zip(first, second, strict=True)
    )
    assert peri_scribe.kml.colormap.turbo_at(0.5) == midpoint


def test_turbo_at_clamps_at_the_ends() -> None:
    assert (
        peri_scribe.kml.colormap.turbo_at(-1)
        == (peri_scribe.kml.colormap.TURBO_RAMP[0])
    )
    assert (
        peri_scribe.kml.colormap.turbo_at(1_000)
        == (peri_scribe.kml.colormap.TURBO_RAMP[-1])
    )


def test_sample_turbo_bounds_the_ramp() -> None:
    assert peri_scribe.kml.colormap.sample_turbo(1) == (
        peri_scribe.kml.colormap.TURBO_RAMP[0],
    )
    assert peri_scribe.kml.colormap.sample_turbo(2) == (
        peri_scribe.kml.colormap.TURBO_RAMP[0],
        peri_scribe.kml.colormap.TURBO_RAMP[-1],
    )
    assert peri_scribe.kml.colormap.sample_turbo(0) == ()


def test_color_hex_converts_to_rrggbb() -> None:
    assert peri_scribe.kml.colormap.color_hex((0.18995, 0.07176, 0.23217)) == "#30123b"
    assert peri_scribe.kml.colormap.color_hex((0.0, 0.5, 1.0)) == "#0080ff"


def test_cool_fraction_is_hottest_for_one_ring() -> None:
    assert peri_scribe.kml.colormap.cool_fraction(1) == pytest.approx(1.0)


def test_cool_fraction_spans_the_ramp_at_full_ring_count() -> None:
    full = peri_scribe.kml.colormap.FULL_RAMP_RING_COUNT
    assert peri_scribe.kml.colormap.cool_fraction(full) == pytest.approx(0.0)
    assert peri_scribe.kml.colormap.cool_fraction(full + 1) == pytest.approx(0.0)


def test_cool_fraction_anchors_short_fires_partway() -> None:
    full = peri_scribe.kml.colormap.FULL_RAMP_RING_COUNT
    assert peri_scribe.kml.colormap.cool_fraction(3) == pytest.approx(
        (full - 3) / (full - 1),
    )


def test_active_ring_window_keeps_the_single_qualifying_ring() -> None:
    assert peri_scribe.kml.colormap.active_ring_window(
        [5.0 * units.Unit("meters ** 2"), 1.0 * units.Unit("meters ** 2")],
        4.0 * units.Unit("meters ** 2"),
    ) == (0, 0)


def test_active_ring_window_drops_trivial_edges() -> None:
    assert peri_scribe.kml.colormap.active_ring_window(
        [
            0.1 * units.Unit("meters ** 2"),
            10.0 * units.Unit("meters ** 2"),
            0.1 * units.Unit("meters ** 2"),
        ],
        9.9 * units.Unit("meters ** 2"),
    ) == (1, 1)


def test_active_ring_window_keeps_the_larger_boundary_ring_on_a_tie() -> None:
    assert peri_scribe.kml.colormap.active_ring_window(
        [
            1.0 * units.Unit("meters ** 2"),
            100.0 * units.Unit("meters ** 2"),
            5.0 * units.Unit("meters ** 2"),
        ],
        101.0 * units.Unit("meters ** 2"),
    ) == (1, 2)


def test_progression_ring_colors_single_ring_is_hottest() -> None:
    only = tests.helpers.factories.peri_scribe.kml.colormap.ring(
        1.0,
        tests.helpers.factories.peri_scribe.kml.colormap.utc(2026, 8, 15),
        area=100.0,
    )
    assert peri_scribe.kml.colormap.progression_ring_colors((only,)) == (
        (only, peri_scribe.kml.colormap.TURBO_RAMP[-1]),
    )


def test_progression_ring_colors_hottest_for_shared_timestamp() -> None:
    rings = (
        tests.helpers.factories.peri_scribe.kml.colormap.ring(
            1.0,
            tests.helpers.factories.peri_scribe.kml.colormap.utc(2026, 8, 15),
            area=100.0,
        ),
        tests.helpers.factories.peri_scribe.kml.colormap.ring(
            1.0,
            tests.helpers.factories.peri_scribe.kml.colormap.utc(2026, 8, 15),
            area=100.0,
        ),
    )
    colored = peri_scribe.kml.colormap.progression_ring_colors(rings)
    assert [rgb for _ring, rgb in colored] == [
        peri_scribe.kml.colormap.TURBO_RAMP[-1],
        peri_scribe.kml.colormap.TURBO_RAMP[-1],
    ]


def test_progression_ring_colors_interpolates_by_timestamp() -> None:
    base = datetime.datetime(2026, 8, 13, 0, 0, tzinfo=datetime.UTC)
    rings = (
        tests.helpers.factories.peri_scribe.kml.colormap.ring(1.0, base, area=100.0),
        tests.helpers.factories.peri_scribe.kml.colormap.ring(
            1.0,
            base + datetime.timedelta(hours=6),
            area=100.0,
        ),
        tests.helpers.factories.peri_scribe.kml.colormap.ring(
            1.0,
            base + datetime.timedelta(hours=24),
            area=100.0,
        ),
    )
    colored = peri_scribe.kml.colormap.progression_ring_colors(rings)
    cool = peri_scribe.kml.colormap.cool_fraction(3)
    assert [rgb for _ring, rgb in colored] == [
        peri_scribe.kml.colormap.turbo_at(
            cool * (len(peri_scribe.kml.colormap.TURBO_RAMP) - 1),
        ),
        peri_scribe.kml.colormap.turbo_at(
            (cool + 0.25 * (1.0 - cool))
            * (len(peri_scribe.kml.colormap.TURBO_RAMP) - 1),
        ),
        peri_scribe.kml.colormap.TURBO_RAMP[-1],
    ]


def test_progression_ring_colors_clamps_smolder_to_the_hottest() -> None:
    rings = (
        tests.helpers.factories.peri_scribe.kml.colormap.ring(
            1.0,
            tests.helpers.factories.peri_scribe.kml.colormap.utc(2026, 8, 13),
            area=100.0,
        ),
        tests.helpers.factories.peri_scribe.kml.colormap.ring(
            1.0,
            tests.helpers.factories.peri_scribe.kml.colormap.utc(2026, 8, 14),
            area=100.0,
        ),
        tests.helpers.factories.peri_scribe.kml.colormap.ring(
            1.0,
            tests.helpers.factories.peri_scribe.kml.colormap.utc(2026, 8, 15),
            area=100.0,
        ),
        tests.helpers.factories.peri_scribe.kml.colormap.ring(
            1.0,
            tests.helpers.factories.peri_scribe.kml.colormap.utc(2026, 8, 23),
            area=0.1,
        ),
    )
    colored = peri_scribe.kml.colormap.progression_ring_colors(rings)
    assert colored[2][1] == peri_scribe.kml.colormap.TURBO_RAMP[-1]
    assert colored[3][1] == peri_scribe.kml.colormap.TURBO_RAMP[-1]


def test_progression_ring_colors_clamps_slow_start_to_the_coolest() -> None:
    rings = (
        tests.helpers.factories.peri_scribe.kml.colormap.ring(
            1.0,
            tests.helpers.factories.peri_scribe.kml.colormap.utc(2026, 8, 1),
            area=0.1,
        ),
        tests.helpers.factories.peri_scribe.kml.colormap.ring(
            1.0,
            tests.helpers.factories.peri_scribe.kml.colormap.utc(2026, 8, 10),
            area=100.0,
        ),
        tests.helpers.factories.peri_scribe.kml.colormap.ring(
            1.0,
            tests.helpers.factories.peri_scribe.kml.colormap.utc(2026, 8, 11),
            area=100.0,
        ),
    )
    colored = peri_scribe.kml.colormap.progression_ring_colors(rings)
    cool = peri_scribe.kml.colormap.cool_fraction(2)
    assert colored[0][1] == peri_scribe.kml.colormap.turbo_at(
        cool * (len(peri_scribe.kml.colormap.TURBO_RAMP) - 1),
    )
    assert colored[-1][1] == peri_scribe.kml.colormap.TURBO_RAMP[-1]


def test_progression_ring_colors_skips_undated_rings() -> None:
    colored = peri_scribe.kml.colormap.progression_ring_colors((
        tests.helpers.factories.peri_scribe.kml.colormap.ring(1.0),
        tests.helpers.factories.peri_scribe.kml.colormap.ring(
            2.0,
            tests.helpers.factories.peri_scribe.kml.colormap.utc(2026, 8, 15),
            area=100.0,
        ),
    ))
    assert len(colored) == 1
    assert colored[0][0].observation_time is not None


def test_progression_ring_colors_returns_nothing_without_rings() -> None:
    assert peri_scribe.kml.colormap.progression_ring_colors(()) == ()


def test_turbo_colormap_ansi_marks_the_used_ramp_by_default() -> None:
    start = peri_scribe.kml.colormap.TURBO_TRIM_FROM_START
    end = start + len(peri_scribe.kml.colormap.TURBO_RAMP) - 1
    lines = peri_scribe.kml.colormap.turbo_colormap_ansi().splitlines()
    assert len(lines) == len(peri_scribe.kml.colormap.turbo_colormap_256)
    marker = peri_scribe.kml.colormap.USED_RANGE_MARKER
    for index, line in enumerate(lines):
        assert (marker in line) == (start <= index <= end)


def test_turbo_colormap_ansi_draws_the_full_table() -> None:
    lines = peri_scribe.kml.colormap.turbo_colormap_ansi(
        trim_start=0,
        trim_end=0,
    ).splitlines()
    assert len(lines) == len(peri_scribe.kml.colormap.turbo_colormap_256)
    for line, color in zip(
        lines,
        peri_scribe.kml.colormap.turbo_colormap_256,
        strict=True,
    ):
        assert peri_scribe.kml.colormap.ansi_background(color) in line
    assert all(peri_scribe.kml.colormap.USED_RANGE_MARKER in line for line in lines)


def test_turbo_colormap_ansi_previews_a_trim() -> None:
    lines = peri_scribe.kml.colormap.turbo_colormap_ansi(
        trim_start=32,
        trim_end=8,
    ).splitlines()
    assert len(lines) == len(peri_scribe.kml.colormap.turbo_colormap_256)
    marked = [
        index
        for index, line in enumerate(lines)
        if peri_scribe.kml.colormap.USED_RANGE_MARKER in line
    ]
    assert marked == list(range(32, 248))


def test_turbo_colormap_ansi_labels_the_tick_indices() -> None:
    assert tests.helpers.peri_scribe.kml.colormap.tick_labels(
        peri_scribe.kml.colormap.turbo_colormap_ansi(),
    ) == {index: index for index in peri_scribe.kml.colormap.COLORMAP_TICK_INDICES}


def test_turbo_colormap_ansi_labels_the_ends_of_the_used_range() -> None:
    first_used = 20
    last_used = 242
    strip = peri_scribe.kml.colormap.turbo_colormap_ansi(
        trim_start=first_used,
        trim_end=len(peri_scribe.kml.colormap.turbo_colormap_256) - 1 - last_used,
    )
    assert tests.helpers.peri_scribe.kml.colormap.range_labels(strip) == {
        first_used: first_used,
        last_used: last_used,
    }


def test_turbo_colormap_ansi_clamps_the_used_range_to_the_table() -> None:
    trim_start = -1
    last_used = (
        len(peri_scribe.kml.colormap.turbo_colormap_256)
        - 1
        - peri_scribe.kml.colormap.TURBO_TRIM_FROM_END
    )
    strip = peri_scribe.kml.colormap.turbo_colormap_ansi(trim_start=trim_start)
    assert tests.helpers.peri_scribe.kml.colormap.range_labels(strip) == {
        0: 0,
        last_used: last_used,
    }


def test_turbo_colormap_ansi_labels_no_used_range_when_the_trims_overlap() -> None:
    first_used = 245
    last_used = 239
    strip = peri_scribe.kml.colormap.turbo_colormap_ansi(
        trim_start=first_used,
        trim_end=len(peri_scribe.kml.colormap.turbo_colormap_256) - 1 - last_used,
    )
    assert tests.helpers.peri_scribe.kml.colormap.range_labels(strip) == {}
    assert peri_scribe.kml.colormap.USED_RANGE_MARKER not in strip


def test_colormap_tick_indices_are_the_tick_intervals() -> None:
    assert peri_scribe.kml.colormap.COLORMAP_TICK_INDICES[:-1] == tuple(
        range(0, 255, peri_scribe.kml.colormap.COLORMAP_TICK_INTERVAL),
    )


def test_colormap_tick_indices_end_with_the_last_color() -> None:
    assert peri_scribe.kml.colormap.COLORMAP_TICK_INDICES[-1] == (
        len(peri_scribe.kml.colormap.turbo_colormap_256) - 1
    )
