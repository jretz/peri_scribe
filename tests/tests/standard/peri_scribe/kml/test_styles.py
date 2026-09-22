"""Tests for peri_scribe.kml.styles."""

from __future__ import annotations

import kml_io.styles
import peri_scribe.kml.styles
from measurement_units import units


def test_outlined_perimeter_style_fills_with_transparent_outline_color() -> None:
    color = "#FF0000"
    style = peri_scribe.kml.styles.outlined_perimeter_style("outline", color)
    assert style.linestyle.color == kml_io.styles.kml_color(
        color,
        peri_scribe.kml.styles.OUTLINE_OPACITY,
    )
    assert style.polystyle.color == kml_io.styles.kml_color(
        color,
        0 * units.percent,
    )
