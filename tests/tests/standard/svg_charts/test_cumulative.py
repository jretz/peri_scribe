"""Empirical elapsed-time curves retain observations and readable statistics."""

import io

import PIL.Image
import pytest

import svg_charts.cumulative
from measurement_units import units


@pytest.mark.parametrize(
    ("seconds", "label"),
    [
        (0.025, "25 ms"),
        (5.86, "5.86 s"),
        (60, "1m"),
        (259.45, "4m 19s"),
        (3600, "1h"),
        (3660, "1h 01m"),
        (172800, "2 d"),
    ],
)
def test_duration_label_uses_compact_units(seconds: float, label: str) -> None:
    assert svg_charts.cumulative.duration_label(seconds) == label


def test_legend_label_uses_inverse_empirical_percentiles() -> None:
    series = svg_charts.cumulative.Series(label="Runs", durations=(), color="blue")
    assert svg_charts.cumulative.legend_label(series, [10, 20, 90]) == (
        "Runs (n = 3)\nP50 20 s   ·   P90 1m 30s   ·   Max 1m 30s"
    )


def test_legend_label_distinguishes_missing_samples_from_zero() -> None:
    series = svg_charts.cumulative.Series(label="Runs", durations=(), color="blue")
    assert svg_charts.cumulative.legend_label(series, []) == (
        "Runs (n = 0)\nP50 —   ·   P90 —   ·   Max —"
    )
    assert "P50 0 ms" in svg_charts.cumulative.legend_label(series, [0])


def test_layout_x_of_uses_equal_spacing_for_equal_time_ratios() -> None:
    chart = svg_charts.cumulative.Layout(lower=1, upper=100, top=50)
    assert chart.x_of(10) == pytest.approx((chart.left + chart.right) / 2)
    assert chart.x_of(0) == chart.left


def test_layout_y_of_keeps_cumulative_shares_linear() -> None:
    chart = svg_charts.cumulative.Layout(lower=1, upper=100, top=50)
    assert chart.y_of(0.5) == pytest.approx((chart.y_of(0) + chart.y_of(1)) / 2)
    assert chart.y_of(1) > chart.top


def test_curve_points_preserves_repeated_samples_and_horizontal_steps() -> None:
    chart = svg_charts.cumulative.Layout(
        lower=1,
        upper=100,
        top=0,
        left=0,
        right=2,
        bottom=1.04,
    )
    expected = [
        (0, 1.04),
        (0, 1.04),
        (0, 1.04 - 1 / 3),
        (0, 1.04 - 1 / 3),
        (0, 1.04 - 2 / 3),
        (2, 1.04 - 2 / 3),
        (2, 0.04),
        (2, 0.04),
    ]
    actual = svg_charts.cumulative.curve_points([1, 1, 100], chart)
    for observed, wanted in zip(actual, expected, strict=True):
        assert observed == pytest.approx(wanted)


@pytest.mark.parametrize("values", [[[]], [[0]], [[120, 5], [20]]])
def test_layout_keeps_positive_bounds_and_room_for_legends(
    values: list[list[float]],
) -> None:
    chart = svg_charts.cumulative.layout(values)
    assert 0 < chart.lower < chart.upper
    assert chart.top > len(values) * 40
    assert chart.time_ticks()


def test_layout_time_ticks_preserves_labels_beyond_named_time_ladder() -> None:
    chart = svg_charts.cumulative.Layout(lower=0.000001, upper=0.00001, top=50)
    assert chart.time_ticks() == (chart.lower, chart.upper)


def test_layout_time_ticks_avoids_overlapping_labels() -> None:
    chart = svg_charts.cumulative.Layout(lower=1, upper=1000, top=50, right=300)
    ticks = chart.time_ticks()
    assert len(ticks) < len(
        svg_charts.cumulative.Layout(lower=1, upper=1000, top=50).time_ticks(),
    )


def test_png_preserves_dimensions_background_and_curve_colors() -> None:
    series = (
        svg_charts.cumulative.Series(
            label="All runs",
            durations=(2 * units.minutes, 5 * units.seconds),
            color="#60a5fa",
        ),
        svg_charts.cumulative.Series(
            label="Source → KMZ",
            durations=(4 * units.minutes,),
            color="#2dd4bf",
        ),
    )
    with PIL.Image.open(
        io.BytesIO(svg_charts.cumulative.png(series, "Start — end")),
    ) as image:
        assert image.size == (1000, 768)
        assert image.getpixel((0, 0)) == (17, 24, 39)
        assert image.getpixel((0, image.height - 1)) == (17, 24, 39)
        assert image.getpixel((170, 40)) == pytest.approx((96, 165, 250), abs=10)
        assert image.getpixel((170, 104)) == pytest.approx((45, 212, 191), abs=10)


def test_png_normalizes_elapsed_time_units() -> None:
    seconds = svg_charts.cumulative.Series(
        label="Runs",
        durations=(120 * units.seconds, 5 * units.seconds),
        color="blue",
    )
    minutes = svg_charts.cumulative.Series(
        label="Runs",
        durations=(2 * units.minutes, 5000 * units.milliseconds),
        color="blue",
    )
    assert svg_charts.cumulative.png((seconds,), "Window") == (
        svg_charts.cumulative.png((minutes,), "Window")
    )


@pytest.mark.parametrize("seconds", [(), (0,)])
def test_image_handles_empty_and_zero_only_series(seconds: tuple[float, ...]) -> None:
    series = svg_charts.cumulative.Series(
        label="Runs",
        durations=tuple(value * units.seconds for value in seconds),
        color="blue",
    )
    assert svg_charts.cumulative.image((series,), "Window").size == (1000, 768)
