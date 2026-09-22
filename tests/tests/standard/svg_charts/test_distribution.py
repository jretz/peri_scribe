"""Verify numerical distribution curves and bend detection."""

from __future__ import annotations

import pytest

import svg_charts.distribution


def test_curve_knees_finds_two_breakpoints() -> None:
    assert svg_charts.distribution.curve_knees(
        [10] * 4 + [50] * 2 + [100, 200, 300, 500],
    ) == [(100, pytest.approx(0.3)), (300, pytest.approx(0.1))]


def test_curve_knees_returns_empty_without_a_bend() -> None:
    assert svg_charts.distribution.curve_knees([]) == []
    assert svg_charts.distribution.curve_knees([5, 5, 5]) == []
    assert svg_charts.distribution.curve_knees([10, 20]) == []
    assert (
        svg_charts.distribution.curve_knees(
            [10] * 20 + [50] * 5 + [100] * 3 + [200] * 2 + [500],
        )
        == []
    )


def test_curve_knees_selects_the_best_fit_among_multiple_candidates() -> None:
    assert svg_charts.distribution.curve_knees(list(range(1, 11))) == [
        (6, pytest.approx(0.4)),
        (8, pytest.approx(0.2)),
    ]


def test_curve_knees_preserves_fractional_values() -> None:
    assert svg_charts.distribution.curve_knees(
        [0.125] * 4 + [0.625] * 2 + [1.25, 2.5, 3.75, 6.25],
    ) == [(1.25, pytest.approx(0.3)), (3.75, pytest.approx(0.1))]


def test_draw_ccdf_escapes_caller_supplied_labels() -> None:
    drawing = svg_charts.distribution.draw_ccdf(
        [1.25, 2.5, 3.75],
        title='Duration < 5 & "sample"',
        x_axis_label="Seconds < limit",
        y_axis_label="Share & count",
        annotations=(
            svg_charts.distribution.CurveAnnotation(
                value=1.25,
                share=2 / 3,
                lines=("Label < threshold", "More & less"),
            ),
        ),
    )
    assert 'aria-label="Duration &lt; 5 &amp; &quot;sample&quot;"' in drawing
    assert ">Seconds &lt; limit</text>" in drawing
    assert ">Share &amp; count</text>" in drawing
    assert ">Label &lt; threshold</text>" in drawing
    assert ">More &amp; less</text>" in drawing
