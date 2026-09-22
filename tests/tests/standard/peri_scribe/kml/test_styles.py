"""Tests for peri_scribe.kml.styles."""

from __future__ import annotations

import pytest

import kml_io.styles
import peri_scribe.kml.icons
import peri_scribe.kml.styles


@pytest.mark.parametrize("color", peri_scribe.kml.styles.OUTLINED_PERIMETER_COLORS)
def test_outlined_perimeter_style_uses_outline_and_matching_list_icon(
    color: str,
) -> None:
    style = peri_scribe.kml.styles.outlined_perimeter_style("outline", color)
    assert style.linestyle.color == kml_io.styles.kml_color(
        color,
        peri_scribe.kml.styles.OUTLINE_OPACITY,
    )
    assert style.polystyle.fill == 0
    assert style.polystyle.outline == 1
    assert style.linestyle.width == pytest.approx(peri_scribe.kml.styles.OUTLINE_WIDTH)
    assert (
        style.liststyle.itemicon.href
        == peri_scribe.kml.icons.outlined_perimeter_icon_filename(color)
    )
