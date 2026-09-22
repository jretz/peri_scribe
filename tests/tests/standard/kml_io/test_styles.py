"""Style construction preserves caller choices and KML channel encoding."""

from __future__ import annotations

import typing

import pytest

import kml_io.styles
from measurement_units import units


if typing.TYPE_CHECKING:
    import pint


@pytest.mark.parametrize(
    ("opacity", "expected"),
    [
        (0 * units.percent, "008000ff"),
        (50 * units.percent, "7f8000ff"),
        (0.5 * units.dimensionless, "7f8000ff"),
        (100 * units.percent, "ff8000ff"),
    ],
)
def test_kml_color_encodes_opacity_and_reverses_channels(
    opacity: pint.Quantity[float],
    expected: str,
) -> None:
    assert kml_io.styles.kml_color("#FF0080", opacity) == expected


def test_icon_style_preserves_identifier_and_image_reference() -> None:
    style = kml_io.styles.icon_style("city", "images/city.png")
    assert style.id == "city"
    assert style.iconstyle.icon.href == "images/city.png"


def test_filled_polygon_style_uses_supplied_color_and_opacity() -> None:
    style = kml_io.styles.filled_polygon_style("lake", "#123456", 100 * units.percent)
    assert style.id == "lake"
    assert style.polystyle.color == "ff563412"
    assert style.polystyle.fill == 1
    assert style.polystyle.outline == 0


def test_outlined_polygon_style_keeps_transparent_fill_for_list_icon() -> None:
    style = kml_io.styles.outlined_polygon_style(
        "border",
        "#123456",
        50 * units.percent,
        3.0,
    )
    assert style.id == "border"
    assert style.linestyle.color == "7f563412"
    assert style.linestyle.width == pytest.approx(3.0)
    assert style.polystyle.color == "00563412"
    assert style.polystyle.fill == 1
    assert style.polystyle.outline == 1
