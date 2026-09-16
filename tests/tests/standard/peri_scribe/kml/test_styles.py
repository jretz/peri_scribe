"""Tests for peri_scribe.kml.styles."""

from __future__ import annotations

import peri_scribe.kml.styles
from peri_scribe.units import units


def test_outlined_perimeter_style_fills_with_transparent_outline_color() -> None:
    color = "#FF0000"
    style = peri_scribe.kml.styles.outlined_perimeter_style("outline", color)
    assert style.linestyle.color == peri_scribe.kml.styles.kml_color(
        color,
        peri_scribe.kml.styles.OUTLINE_OPACITY,
    )
    assert style.polystyle.color == peri_scribe.kml.styles.kml_color(
        color,
        0 * units.percent,
    )
