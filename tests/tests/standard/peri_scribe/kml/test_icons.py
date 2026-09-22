"""Tests for peri_scribe.kml.icons."""

from __future__ import annotations

import pytest

import peri_scribe.kml.colormap
import peri_scribe.kml.icons
import tests.helpers.peri_scribe.kml.parsing


def test_interior_progression_icon_filename_names_the_folder() -> None:
    assert (
        peri_scribe.kml.icons.interior_progression_icon_filename()
        == "interior-progression.png"
    )


def test_perimeters_icon_filename_names_the_folder() -> None:
    assert peri_scribe.kml.icons.perimeters_icon_filename() == "perimeters.png"


@pytest.mark.parametrize(
    ("color", "expected"),
    [
        ("#FF0000", (255, 0, 0)),
        ("#FFFF00", (255, 255, 0)),
        ("#FFFFFF", (255, 255, 255)),
        ("#123456", (18, 52, 86)),
    ],
)
def test_outlined_perimeter_icon_draws_requested_color(
    color: str,
    expected: tuple[int, int, int],
) -> None:
    rows = tests.helpers.peri_scribe.kml.parsing.png_pixel_rows(
        peri_scribe.kml.icons.outlined_perimeter_icon(color),
    )
    assert rows[7][8] == rows[8][7] == (*expected, 255)


def test_perimeters_icon_has_transparent_background_and_outlined_diagonals() -> None:
    rows = tests.helpers.peri_scribe.kml.parsing.png_pixel_rows(
        peri_scribe.kml.icons.perimeters_icon(),
    )
    side = 16
    assert len(rows) == side
    assert all(len(row) == side for row in rows)
    assert rows[4][7] == rows[7][4] == (255, 0, 0, 255)
    assert rows[8][11] == rows[11][8] == (255, 255, 0, 255)
    assert rows[0][0] == rows[0][-1] == rows[-1][0] == rows[-1][-1] == (0, 0, 0, 0)
    assert all(rows[index][side - 1 - index][3] == 0 for index in range(side))
    assert any(pixel[:3] == (0, 0, 0) and pixel[3] > 0 for row in rows for pixel in row)


def test_interior_progression_icon_draws_the_turbo_gradient() -> None:
    rows = tests.helpers.peri_scribe.kml.parsing.png_pixel_rows(
        peri_scribe.kml.icons.interior_progression_icon(),
    )
    side = int(peri_scribe.kml.icons.PROGRESSION_ICON_SIDE_LENGTH.magnitude)
    colors = peri_scribe.kml.colormap.sample_turbo(side)[::-1]
    assert len(rows) == side
    for row, rgb in zip(rows, colors, strict=True):
        expected = (*[round(component * 255) for component in rgb], 255)
        assert row == [expected] * side
    assert (
        rows[0]
        == [
            (
                *[
                    round(component * 255)
                    for component in peri_scribe.kml.colormap.TURBO_RAMP[-1]
                ],
                255,
            ),
        ]
        * side
    )
    assert (
        rows[-1]
        == [
            (
                *[
                    round(component * 255)
                    for component in peri_scribe.kml.colormap.TURBO_RAMP[0]
                ],
                255,
            ),
        ]
        * side
    )
