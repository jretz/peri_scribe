"""Tests for peri_scribe.kml.descriptions."""

from __future__ import annotations

import weakref

import pytest

import peri_scribe.execution
import peri_scribe.kml.descriptions
import peri_scribe.presentation.descriptions
import tests.helpers.doubles.peri_scribe.kml.descriptions
import tests.helpers.factories.peri_scribe.presentation.descriptions
import tests.helpers.reference.peri_scribe.kml.descriptions


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


@pytest.mark.parametrize("leading_count", [0, 1, 2, 3, 8])
def test_description_html_matches_original_wire_after_any_prefix(
    leading_count: int,
) -> None:
    description = peri_scribe.presentation.descriptions.FireDescription(
        identifier="North\r\n\x85\x00\ud800 & <fire> ]]>",
        of_note="Literal &amp; 'quoted' \ufffe text",
        area_basis="Reported\rsize",
    )
    images = ('a&b"c\r\n\x00]]>.svg',)
    leading_rows = tuple(
        (f"Added <{index}>", None if index % 2 else "\udfff\x85&--")
        for index in range(leading_count)
    )
    expected = tests.helpers.reference.peri_scribe.kml.descriptions.description_html(
        description,
        images,
        leading_rows,
    )
    with peri_scribe.execution.sharing():
        peri_scribe.kml.descriptions.description_html(description, images)
        actual = peri_scribe.kml.descriptions.description_html(
            description,
            images,
            leading_rows,
        )
        assert str(actual) == expected
        assert (
            peri_scribe.kml.descriptions.description_html(
                description,
                images,
                leading_rows,
            )
            is actual
        )
    assert (
        str(
            peri_scribe.kml.descriptions.description_html(
                description,
                images,
                leading_rows,
            ),
        )
        == expected
    )


def test_balloon_variants_share_common_formatting_within_one_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    description = (
        tests.helpers.factories.peri_scribe.presentation.descriptions.full_description()
    )
    calls: list[peri_scribe.presentation.descriptions.FireDescription] = []
    monkeypatch.setattr(
        peri_scribe.presentation.descriptions,
        "description_rows",
        tests.helpers.doubles.peri_scribe.kml.descriptions.record_rows(
            peri_scribe.presentation.descriptions.description_rows,
            calls,
        ),
    )
    for _publication in range(2):
        with peri_scribe.execution.sharing():
            peri_scribe.kml.descriptions.description_html(description)
            for count in range(1, 5):
                peri_scribe.kml.descriptions.description_html(
                    description,
                    leading_rows=(("Added area", "1 acre"),) * count,
                )
    assert calls == [description, description]


def test_balloon_cache_releases_all_input_and_output_references_at_scope_exit() -> None:
    with peri_scribe.execution.sharing():
        description = peri_scribe.presentation.descriptions.FireDescription(
            identifier="scope-owned",
        )
        balloon = peri_scribe.kml.descriptions.description_html(description)
        description_reference = weakref.ref(description)
        balloon_reference = weakref.ref(balloon)
        del description, balloon
        assert description_reference() is not None
        assert balloon_reference() is not None
    assert description_reference() is None
    assert balloon_reference() is None


def test_standalone_balloons_do_not_retain_input_or_output_references() -> None:
    description = peri_scribe.presentation.descriptions.FireDescription(
        identifier="standalone",
    )
    balloon = peri_scribe.kml.descriptions.description_html(description)
    description_reference = weakref.ref(description)
    balloon_reference = weakref.ref(balloon)
    del description, balloon
    assert description_reference() is None
    assert balloon_reference() is None
