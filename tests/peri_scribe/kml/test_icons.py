"""Tests for peri_scribe.kml.icons."""

from __future__ import annotations

import peri_scribe.kml.colormap
import peri_scribe.kml.icons
import tests.peri_scribe.kml.kml_helpers


def test_interior_progression_icon_filename_names_the_folder() -> None:
    assert (
        peri_scribe.kml.icons.interior_progression_icon_filename()
        == "interior-progression.png"
    )


def test_perimeters_icon_filename_names_the_folder() -> None:
    assert peri_scribe.kml.icons.perimeters_icon_filename() == "perimeters.png"


def test_perimeters_icon_draws_two_full_width_lines() -> None:
    rows = tests.peri_scribe.kml.kml_helpers.png_pixel_rows(
        peri_scribe.kml.icons.perimeters_icon(),
    )
    side = peri_scribe.kml.icons.PROGRESSION_ICON_SIDE_LENGTH_IN_PIXELS
    assert len(rows) == side
    top_line_row = side // 3
    bottom_line_row = side - 1 - side // 3
    background = (0x32, 0x4B, 0x32, 255)
    for row_index, row in enumerate(rows):
        if row_index == top_line_row:
            assert (
                row
                == [
                    (*peri_scribe.kml.icons.LATEST_PERIMETER_COLOR, 255),
                ]
                * side
            )
        elif row_index == bottom_line_row:
            assert (
                row
                == [
                    (*peri_scribe.kml.icons.PENULTIMATE_PERIMETER_COLOR, 255),
                ]
                * side
            )
        else:
            assert row == [background] * side


def test_perimeter_color_constants_match_the_template_colors() -> None:
    assert peri_scribe.kml.icons.LATEST_PERIMETER_COLOR == (0xFF, 0x00, 0x00)
    assert peri_scribe.kml.icons.PENULTIMATE_PERIMETER_COLOR == (0xFF, 0xFF, 0x00)


def test_interior_progression_icon_draws_the_turbo_gradient() -> None:
    rows = tests.peri_scribe.kml.kml_helpers.png_pixel_rows(
        peri_scribe.kml.icons.interior_progression_icon(),
    )
    side = peri_scribe.kml.icons.PROGRESSION_ICON_SIDE_LENGTH_IN_PIXELS
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
