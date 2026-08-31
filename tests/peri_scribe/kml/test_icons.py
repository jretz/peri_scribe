"""Tests for peri_scribe.kml.icons."""

from __future__ import annotations

import peri_scribe.kml.colormap
import peri_scribe.kml.icons
import peri_scribe.kml.template
import peri_scribe.kml.template_reader
import tests.peri_scribe.kml.kml_helpers


def test_interior_progression_icon_filename_names_the_folder() -> None:
    assert (
        peri_scribe.kml.icons.interior_progression_icon_filename()
        == "interior-progression.png"
    )


def test_interior_icon_filename_names_the_folder() -> None:
    assert peri_scribe.kml.icons.interior_icon_filename() == "interior.png"


def test_perimeters_icon_filename_names_the_folder() -> None:
    assert peri_scribe.kml.icons.perimeters_icon_filename() == "perimeters.png"


def test_perimeters_icon_draws_two_full_width_lines() -> None:
    template = peri_scribe.kml.template_reader.template_from(
        peri_scribe.kml.template.template_kml(),
    )
    rows = tests.peri_scribe.kml.kml_helpers.png_pixel_rows(
        peri_scribe.kml.icons.perimeters_icon(template),
    )
    side = peri_scribe.kml.icons.PROGRESSION_ICON_SIDE_LENGTH_IN_PIXELS
    assert len(rows) == side
    top_line_row = side // 3
    bottom_line_row = side - 1 - side // 3
    background = (0x32, 0x4B, 0x32, 255)
    for row_index, row in enumerate(rows):
        if row_index == top_line_row:
            assert row == [(255, 0, 0, 255)] * side
        elif row_index == bottom_line_row:
            assert row == [(255, 255, 0, 255)] * side
        else:
            assert row == [background] * side


def test_perimeters_icon_colors_come_from_template() -> None:
    template = peri_scribe.kml.template_reader.template_from(
        peri_scribe.kml.template.template_kml(),
    )
    styles = {style.id: style for style in template.styles}
    latest_style_id = template.style_urls["Latest Perimeter"].lstrip("#")
    penultimate_style_id = template.style_urls["Penultimate Perimeter"].lstrip("#")
    styles[latest_style_id].linestyle.color = "ff00ff00"
    styles[penultimate_style_id].linestyle.color = "ffff0000"
    rows = tests.peri_scribe.kml.kml_helpers.png_pixel_rows(
        peri_scribe.kml.icons.perimeters_icon(template),
    )
    side = peri_scribe.kml.icons.PROGRESSION_ICON_SIDE_LENGTH_IN_PIXELS
    assert rows[side // 3] == [(0, 255, 0, 255)] * side
    assert rows[side - 1 - side // 3] == [(0, 0, 255, 255)] * side


def test_kml_color_rgb_decodes_aabbggrr() -> None:
    assert peri_scribe.kml.icons.kml_color_rgb("7f002aff") == (255, 42, 0)
    assert peri_scribe.kml.icons.kml_color_rgb("7fbdb7b0") == (176, 183, 189)


def test_solid_color_png_fills_a_square() -> None:
    content = peri_scribe.kml.icons.solid_color_png(1, 2, 3, 4)
    assert tests.peri_scribe.kml.kml_helpers.png_color(content) == (1, 2, 3)


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


def test_interior_icon_matches_template_color() -> None:
    template = peri_scribe.kml.template_reader.template_from(
        peri_scribe.kml.template.template_kml(),
    )
    assert tests.peri_scribe.kml.kml_helpers.png_color(
        peri_scribe.kml.icons.interior_icon(template),
    ) == (255, 0, 0)
