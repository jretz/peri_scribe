"""Tests for peri_scribe.kml.colormap."""

from __future__ import annotations

import datetime
import io

import PIL.Image
import pytest
import shapely.geometry

import peri_scribe.kml.colormap
import peri_scribe.perimeters.progression


def ring(
    side: float,
    observation_time: datetime.datetime | None = None,
    *,
    area: float = 0.0,
) -> peri_scribe.perimeters.progression.Ring:
    """Build a square growth ring of the given side at *observation_time*.

    Args:
        side: The ring's side length.
        observation_time: The ring's observation time, or None.
        area: The ring's area in square meters.

    Returns:
        The ring.
    """
    half = side / 2
    return peri_scribe.perimeters.progression.Ring(
        geometry=shapely.geometry.box(-half, -half, half, half),
        observation_time=observation_time,
        area=area,
    )


def utc(year: int, month: int, day: int) -> datetime.datetime:
    """Return an aware UTC datetime for the given calendar date.

    Args:
        year: The year.
        month: The month.
        day: The day.

    Returns:
        The datetime at 20:00 UTC.
    """
    return datetime.datetime(year, month, day, 20, 0, tzinfo=datetime.UTC)


def test_turbo_colormap_keeps_the_full_table() -> None:
    assert len(peri_scribe.kml.colormap.turbo_colormap_256) == (
        peri_scribe.kml.colormap.TURBO_TRIM_FROM_START
        + len(peri_scribe.kml.colormap.TURBO_RAMP)
        + peri_scribe.kml.colormap.TURBO_TRIM_FROM_END
    )
    assert peri_scribe.kml.colormap.turbo_colormap_256[0] == (
        0.18995,
        0.07176,
        0.23217,
    )
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
        peri_scribe.kml.colormap.turbo_at(1000)
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
    assert peri_scribe.kml.colormap.color_hex((0.18995, 0.07176, 0.23217)) == (
        "#30123b"
    )
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
    assert peri_scribe.kml.colormap.active_ring_window([5.0, 1.0], 4.0) == (0, 0)


def test_active_ring_window_drops_trivial_edges() -> None:
    assert peri_scribe.kml.colormap.active_ring_window([0.1, 10.0, 0.1], 9.9) == (
        1,
        1,
    )


def test_active_ring_window_keeps_the_larger_boundary_ring_on_a_tie() -> None:
    assert peri_scribe.kml.colormap.active_ring_window([1.0, 100.0, 5.0], 101.0) == (
        1,
        2,
    )


def test_progression_ring_colors_single_ring_is_hottest() -> None:
    only = ring(1.0, utc(2026, 8, 15), area=100.0)
    assert peri_scribe.kml.colormap.progression_ring_colors((only,)) == (
        (only, peri_scribe.kml.colormap.TURBO_RAMP[-1]),
    )


def test_progression_ring_colors_hottest_for_shared_timestamp() -> None:
    rings = (
        ring(1.0, utc(2026, 8, 15), area=100.0),
        ring(1.0, utc(2026, 8, 15), area=100.0),
    )
    colored = peri_scribe.kml.colormap.progression_ring_colors(rings)
    assert [rgb for _ring, rgb in colored] == [
        peri_scribe.kml.colormap.TURBO_RAMP[-1],
        peri_scribe.kml.colormap.TURBO_RAMP[-1],
    ]


def test_progression_ring_colors_interpolates_by_timestamp() -> None:
    base = datetime.datetime(2026, 8, 13, 0, 0, tzinfo=datetime.UTC)
    rings = (
        ring(1.0, base, area=100.0),
        ring(1.0, base + datetime.timedelta(hours=6), area=100.0),
        ring(1.0, base + datetime.timedelta(hours=24), area=100.0),
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
        ring(1.0, utc(2026, 8, 13), area=100.0),
        ring(1.0, utc(2026, 8, 14), area=100.0),
        ring(1.0, utc(2026, 8, 15), area=100.0),
        ring(1.0, utc(2026, 8, 23), area=0.1),
    )
    colored = peri_scribe.kml.colormap.progression_ring_colors(rings)
    assert colored[2][1] == peri_scribe.kml.colormap.TURBO_RAMP[-1]
    assert colored[3][1] == peri_scribe.kml.colormap.TURBO_RAMP[-1]


def test_progression_ring_colors_clamps_slow_start_to_the_coolest() -> None:
    rings = (
        ring(1.0, utc(2026, 8, 1), area=0.1),
        ring(1.0, utc(2026, 8, 10), area=100.0),
        ring(1.0, utc(2026, 8, 11), area=100.0),
    )
    colored = peri_scribe.kml.colormap.progression_ring_colors(rings)
    cool = peri_scribe.kml.colormap.cool_fraction(2)
    assert colored[0][1] == peri_scribe.kml.colormap.turbo_at(
        cool * (len(peri_scribe.kml.colormap.TURBO_RAMP) - 1),
    )
    assert colored[-1][1] == peri_scribe.kml.colormap.TURBO_RAMP[-1]


def test_progression_ring_colors_skips_undated_rings() -> None:
    colored = peri_scribe.kml.colormap.progression_ring_colors(
        (ring(1.0), ring(2.0, utc(2026, 8, 15), area=100.0)),
    )
    assert len(colored) == 1
    assert colored[0][0].observation_time is not None


def test_progression_ring_colors_returns_nothing_without_rings() -> None:
    assert peri_scribe.kml.colormap.progression_ring_colors(()) == ()


# A pixel is treated as the strip's white background when its channels span at most
# this much, and a strip-end pixel may differ from its color by at most this much
# per channel (the cell at each end renders a fraction of a pixel narrower than the
# rest).
MAX_NEUTRAL_CHANNEL_SPREAD = 8
MAX_COLOR_CHANNEL_ERROR = 6


def expected_rgb(rgb: tuple[float, float, float]) -> tuple[int, int, int]:
    """Return *rgb* on a 0 to 1 scale rounded to 8-bit components.

    Args:
        rgb: The color as (red, green, blue) components from 0 to 1.

    Returns:
        The color as (red, green, blue) components from 0 to 255.
    """
    return (
        round(rgb[0] * 255),
        round(rgb[1] * 255),
        round(rgb[2] * 255),
    )


def strip_end_colors(
    content: bytes,
) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Return the colors at the ends of the colormap strip in *content*.

    Args:
        content: The strip PNG bytes.

    Returns:
        The (first, last) pixel colors from the strip's middle row.
    """
    with PIL.Image.open(io.BytesIO(content)) as image:
        width, height = image.size
        pixels = image.convert("RGB").tobytes()
    middle_row = pixels[height // 2 * width * 3 : (height // 2 + 1) * width * 3]

    def neutral(pixel_index: int) -> bool:
        pixel = middle_row[pixel_index * 3 : pixel_index * 3 + 3]
        return max(pixel) - min(pixel) < MAX_NEUTRAL_CHANNEL_SPREAD

    colored = [index for index in range(width) if not neutral(index)]
    first = middle_row[(colored[0] + 2) * 3 : (colored[0] + 2) * 3 + 3]
    last = middle_row[(colored[-1] - 2) * 3 : (colored[-1] - 2) * 3 + 3]
    return (first[0], first[1], first[2]), (last[0], last[1], last[2])


def assert_ends_match(
    ends: tuple[tuple[int, int, int], tuple[int, int, int]],
    first: tuple[float, float, float],
    last: tuple[float, float, float],
) -> None:
    """Assert *ends* match the 8-bit forms of *first* and *last* closely.

    Args:
        ends: The (first, last) pixel colors from the strip.
        first: The expected first color on a 0 to 1 scale.
        last: The expected last color on a 0 to 1 scale.
    """
    for actual, expected in zip(
        ends,
        (expected_rgb(first), expected_rgb(last)),
        strict=True,
    ):
        assert all(
            abs(actual_channel - expected_channel) <= MAX_COLOR_CHANNEL_ERROR
            for actual_channel, expected_channel in zip(
                actual,
                expected,
                strict=True,
            )
        )


def test_turbo_colormap_png_draws_the_full_table_by_default() -> None:
    content = peri_scribe.kml.colormap.turbo_colormap_png()
    assert content[:8] == b"\x89PNG\r\n\x1a\n"
    with PIL.Image.open(io.BytesIO(content)) as image:
        width, height = image.size
    assert width > height
    assert_ends_match(
        strip_end_colors(content),
        peri_scribe.kml.colormap.turbo_colormap_256[0],
        peri_scribe.kml.colormap.turbo_colormap_256[-1],
    )


def test_turbo_colormap_png_previews_a_trim() -> None:
    content = peri_scribe.kml.colormap.turbo_colormap_png(
        trim_start=16,
        trim_end=16,
    )
    assert content[:8] == b"\x89PNG\r\n\x1a\n"
    assert_ends_match(
        strip_end_colors(content),
        peri_scribe.kml.colormap.TURBO_RAMP[0],
        peri_scribe.kml.colormap.TURBO_RAMP[-1],
    )
