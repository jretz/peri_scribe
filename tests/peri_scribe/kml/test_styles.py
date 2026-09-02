"""Tests for peri_scribe.kml.styles."""

from __future__ import annotations

import simplekml

import peri_scribe.kml.styles


def test_set_draw_order_sets_the_private_kml_tag() -> None:
    point = simplekml.Point()
    draw_order = 7
    peri_scribe.kml.styles.set_draw_order(point, draw_order)
    assert vars(point)["_kml"]["gx:drawOrder"] == draw_order


def test_band_draw_order_counts_from_newest() -> None:
    band_count = 8
    newest_first_index = 0
    expected_draw_order = 7
    assert (
        peri_scribe.kml.styles.band_draw_order(band_count, newest_first_index)
        == expected_draw_order
    )


def test_outlined_perimeter_style_fills_with_transparent_outline_color() -> None:
    color = "#FF0000"
    style = peri_scribe.kml.styles.outlined_perimeter_style("outline", color)
    assert style.linestyle.color == peri_scribe.kml.styles.kml_color(
        color,
        peri_scribe.kml.styles.OUTLINE_OPACITY_PERCENT,
    )
    assert style.polystyle.color == peri_scribe.kml.styles.kml_color(color, 0)
