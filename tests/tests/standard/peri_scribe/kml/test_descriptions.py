"""Tests for peri_scribe.kml.descriptions."""

from __future__ import annotations

import peri_scribe.kml.descriptions
import peri_scribe.presentation.descriptions
import tests.helpers.factories.peri_scribe.presentation.descriptions


def test_escape_html_text_escapes_html_characters() -> None:
    assert (
        peri_scribe.kml.descriptions.escape_html_text("A & B < C") == "A &amp; B &lt; C"
    )


def test_description_html_wraps_table_in_cdata() -> None:
    html = peri_scribe.kml.descriptions.description_html(
        tests.helpers.factories.peri_scribe.presentation.descriptions.full_description(),
    )
    assert html.startswith("<![CDATA[")
    assert html.endswith("]]>")
    assert "<h3" not in html
    assert "<b>Status</b>" not in html
    assert "102,003 acres" in html
    assert "08/01 22:30 PDT" in html


def test_description_html_sizes_the_text() -> None:
    html = peri_scribe.kml.descriptions.description_html(
        tests.helpers.factories.peri_scribe.presentation.descriptions.full_description(),
    )
    body_size = peri_scribe.kml.descriptions.BODY_FONT_SIZE.magnitude
    assert (
        f'<table cellspacing="0" cellpadding="4" '
        f'style="font-size:{body_size}px;">' in html
    )


def test_description_html_alternates_row_backgrounds() -> None:
    html = peri_scribe.kml.descriptions.description_html(
        tests.helpers.factories.peri_scribe.presentation.descriptions.full_description(),
    )
    color = peri_scribe.kml.descriptions.ALT_ROW_BACKGROUND_COLOR
    background = f'<tr style="background-color:{color};"'
    assert f"{background}><td><b>Area</b></td>" in html
    assert "<tr><td><b>Exterior perimeter</b></td>" in html
    assert f"{background}><td><b>Containment</b></td>" in html
    assert "<tr><td><b>Cost to date</b></td>" in html


def test_description_html_leads_with_given_rows() -> None:
    html = peri_scribe.kml.descriptions.description_html(
        tests.helpers.factories.peri_scribe.presentation.descriptions.full_description(),
        leading_rows=((peri_scribe.kml.descriptions.ADDED_AREA_LABEL, "8,523 acres"),),
    )
    color = peri_scribe.kml.descriptions.ALT_ROW_BACKGROUND_COLOR
    background = f'<tr style="background-color:{color};"'
    assert (
        f"{background}><td><b>{peri_scribe.kml.descriptions.ADDED_AREA_LABEL}</b>"
        "</td><td>8,523 acres</td></tr>" in html
    )
    assert "<tr><td><b>Area</b></td>" in html
    assert html.index("<td><b>Added area</b></td>") < html.index("<td><b>Area</b></td>")


def test_description_html_continues_row_alternation_after_leading_rows() -> None:
    html = peri_scribe.kml.descriptions.description_html(
        tests.helpers.factories.peri_scribe.presentation.descriptions.full_description(),
        leading_rows=(
            (peri_scribe.kml.descriptions.ADDED_AREA_LABEL, "0.5 acres"),
            ("Earlier note", "yes"),
        ),
    )
    color = peri_scribe.kml.descriptions.ALT_ROW_BACKGROUND_COLOR
    background = f'<tr style="background-color:{color};"'
    assert f"{background}><td><b>Added area</b></td>" in html
    assert "<tr><td><b>Earlier note</b></td>" in html
    assert f"{background}><td><b>Area</b></td>" in html


def test_description_html_shows_hyphens_for_missing_values() -> None:
    description = peri_scribe.presentation.descriptions.FireDescription()
    html = peri_scribe.kml.descriptions.description_html(description)
    missing_rows = peri_scribe.presentation.descriptions.description_rows(description)
    assert html.count("<td>--</td>") == len(missing_rows)


def test_description_html_shows_hyphens_for_missing_leading_values() -> None:
    html = peri_scribe.kml.descriptions.description_html(
        tests.helpers.factories.peri_scribe.presentation.descriptions.full_description(),
        leading_rows=((peri_scribe.kml.descriptions.ADDED_AREA_LABEL, None),),
    )
    assert html.index("<td><b>Added area</b></td>") < html.index("<td>--</td>")


def test_description_html_includes_images_after_table() -> None:
    html = peri_scribe.kml.descriptions.description_html(
        tests.helpers.factories.peri_scribe.presentation.descriptions.full_description(),
        ("id-bug-area.png", "id-bug-cost.png"),
    )
    assert html.index("</table>") < html.index("id-bug-area.png")
    assert '<img src="id-bug-area.png" />' in html
    assert '<img src="id-bug-cost.png" />' in html


def test_description_html_escapes_image_filenames() -> None:
    html = peri_scribe.kml.descriptions.description_html(
        tests.helpers.factories.peri_scribe.presentation.descriptions.full_description(),
        ('a&b"c.png',),
    )
    assert '<img src="a&amp;b&quot;c.png" />' in html
