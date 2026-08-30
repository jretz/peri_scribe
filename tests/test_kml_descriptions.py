"""Tests for peri_scribe.kml_descriptions."""

from __future__ import annotations

import datetime
import math

import pytest

import peri_scribe.kml_descriptions


def full_description() -> peri_scribe.kml_descriptions.FireDescription:
    """Return a fire description with every field populated.

    Returns:
        The description.
    """
    return peri_scribe.kml_descriptions.FireDescription(
        identifier="2026-cabug-000001",
        source="FIRIS / NIFC",
        mission="CA-BUG-000001",
        area_in_acres=102003.46,
        exterior_perimeter_in_miles=33.1,
        percent_contained=77.0,
        estimated_cost_to_date_in_dollars=104600000.0,
        estimated_final_cost_in_dollars=120000000.0,
        total_personnel=1234.0,
        protecting_unit="CALMU",
        discovery_time=datetime.datetime(2026, 6, 29, 12, 4, 46, tzinfo=datetime.UTC),
        observation_time=datetime.datetime(2026, 8, 2, 5, 30, tzinfo=datetime.UTC),
        initial_response_time=datetime.datetime(
            2026,
            7,
            27,
            19,
            24,
            tzinfo=datetime.UTC,
        ),
        incident_type="Wildfire",
        incident_complexity="Type 3 Incident; Type 4 Incident; Type 3 Team",
        fuel_model="Timber (Litter and Understory); Brush (2 feet); GS1; Grass",
        fire_behavior="Active; Creeping; Smoldering",
        landowner_category="Federal",
        of_note="Over 100,000 acres, and a Type 1 Incident.",
    )


def test_format_number_returns_none_for_none() -> None:
    assert peri_scribe.kml_descriptions.format_number(None) is None


def test_format_number_rounds_to_whole_number() -> None:
    assert peri_scribe.kml_descriptions.format_number(1234567.89, 0) == "1,234,568"


def test_format_number_keeps_decimal_places_and_separators() -> None:
    assert peri_scribe.kml_descriptions.format_number(1234567.89, 2) == "1,234,567.89"


def test_format_number_drops_trailing_zeros() -> None:
    assert peri_scribe.kml_descriptions.format_number(6.0, 1) == "6"


def test_format_in_acres_returns_none_for_none() -> None:
    assert peri_scribe.kml_descriptions.format_in_acres(None) is None


def test_format_in_acres_uses_whole_acres_for_large_fires() -> None:
    assert peri_scribe.kml_descriptions.format_in_acres(102003.46) == "102,003 acres"


def test_format_in_acres_uses_one_decimal_for_small_fires() -> None:
    assert peri_scribe.kml_descriptions.format_in_acres(6.5) == "6.5 acres"


def test_format_in_acres_uses_two_decimals_for_fractional_acres() -> None:
    assert peri_scribe.kml_descriptions.format_in_acres(0.017) == "0.02 acres"


def test_format_in_percent_returns_none_for_none() -> None:
    assert peri_scribe.kml_descriptions.format_in_percent(None) is None


def test_format_in_percent_uses_whole_percent() -> None:
    assert peri_scribe.kml_descriptions.format_in_percent(77.0) == "77%"


def test_format_in_percent_uses_one_decimal_for_fractional_percent() -> None:
    assert peri_scribe.kml_descriptions.format_in_percent(0.5) == "0.5%"


def test_format_in_miles_returns_none_for_none() -> None:
    assert peri_scribe.kml_descriptions.format_in_miles(None) is None


def test_format_in_miles_adds_unit_and_one_decimal() -> None:
    assert peri_scribe.kml_descriptions.format_in_miles(33.1) == "33.1 miles"


def test_format_in_miles_drops_trailing_zero() -> None:
    assert peri_scribe.kml_descriptions.format_in_miles(33.0) == "33 miles"


def test_format_perimeter_length_returns_none_for_none() -> None:
    assert peri_scribe.kml_descriptions.format_perimeter_length(None) is None


def test_round_to_significant_digits_returns_zero_for_zero() -> None:
    assert peri_scribe.kml_descriptions.round_to_significant_digits(
        0.0,
        3,
    ) == pytest.approx(0.0)


def test_round_to_significant_digits_rounds_to_requested_digits() -> None:
    assert peri_scribe.kml_descriptions.round_to_significant_digits(
        1234.0,
        3,
    ) == pytest.approx(1230.0)


def test_format_perimeter_length_keeps_one_decimal_for_small_lengths() -> None:
    assert peri_scribe.kml_descriptions.format_perimeter_length(0.1499) == "0.1"
    assert peri_scribe.kml_descriptions.format_perimeter_length(math.pi) == "3.1"


def test_format_perimeter_length_caps_significant_digits() -> None:
    assert peri_scribe.kml_descriptions.format_perimeter_length(123.6) == "124"
    assert peri_scribe.kml_descriptions.format_perimeter_length(5678.123) == "5,680"


def test_format_in_miles_caps_large_lengths_to_three_significant_digits() -> None:
    assert peri_scribe.kml_descriptions.format_in_miles(123.6) == "124 miles"
    assert peri_scribe.kml_descriptions.format_in_miles(5678.123) == "5,680 miles"


def test_format_in_miles_keeps_small_lengths_at_one_decimal() -> None:
    assert peri_scribe.kml_descriptions.format_in_miles(0.1499) == "0.1 miles"
    assert peri_scribe.kml_descriptions.format_in_miles(math.pi) == "3.1 miles"


def test_format_containment_returns_none_without_percent() -> None:
    assert peri_scribe.kml_descriptions.format_containment(None, 33.1) is None


def test_format_containment_uses_bare_percent_without_length() -> None:
    assert peri_scribe.kml_descriptions.format_containment(68.0, None) == "68%"


def test_format_containment_annotates_contained_length() -> None:
    assert (
        peri_scribe.kml_descriptions.format_containment(68.0, 33.1)
        == "68% (22.5 of 33.1 miles)"
    )


def test_format_containment_drops_annotation_at_full_containment() -> None:
    assert peri_scribe.kml_descriptions.format_containment(100.0, 33.1) == "100%"


def test_format_cost_returns_none_for_none() -> None:
    assert peri_scribe.kml_descriptions.format_cost_in_dollars(None) is None


def test_format_cost_adds_dollar_sign_and_separators() -> None:
    assert (
        peri_scribe.kml_descriptions.format_cost_in_dollars(104600000.0)
        == "$104,600,000"
    )


def test_format_personnel_count_returns_none_for_none() -> None:
    assert peri_scribe.kml_descriptions.format_personnel_count(None) is None


def test_format_personnel_count_uses_whole_numbers_with_separators() -> None:
    assert peri_scribe.kml_descriptions.format_personnel_count(1234.0) == "1,234"


def test_format_pacific_time_returns_none_for_none() -> None:
    assert peri_scribe.kml_descriptions.format_pacific_time(None) is None


def test_format_pacific_time_marks_pacific_daylight_time() -> None:
    value = datetime.datetime(2026, 8, 5, 20, 30, tzinfo=datetime.UTC)
    assert peri_scribe.kml_descriptions.format_pacific_time(value) == (
        "08/05 13:30 PDT"
    )


def test_format_pacific_time_marks_pacific_standard_time() -> None:
    value = datetime.datetime(2026, 1, 15, 20, 30, tzinfo=datetime.UTC)
    assert peri_scribe.kml_descriptions.format_pacific_time(value) == (
        "01/15 12:30 PST"
    )


def test_escape_text_escapes_html_characters() -> None:
    assert peri_scribe.kml_descriptions.escape_text("A & B < C") == "A &amp; B &lt; C"


def test_description_rows_includes_every_present_value() -> None:
    assert peri_scribe.kml_descriptions.description_rows(full_description()) == [
        ("Area", "102,003 acres"),
        ("Exterior perimeter", "33.1 miles"),
        ("Containment", "77% (25.5 of 33.1 miles)"),
        ("Cost to date", "$104,600,000"),
        ("Estimated final cost", "$120,000,000"),
        ("Personnel", "1,234"),
        ("Source", "FIRIS / NIFC"),
        ("Identifier", "2026-cabug-000001"),
        ("Mission", "CA-BUG-000001"),
        ("Protecting unit", "CALMU"),
        ("Discovery", "06/29 05:04 PDT"),
        ("Last update", "08/01 22:30 PDT"),
        ("Initial response", "07/27 12:24 PDT"),
        ("Incident type", "Wildfire"),
        ("Incident complexity", "Type 3 Incident; Type 4 Incident; Type 3 Team"),
        ("Fuel model", "Timber (Litter and Understory); Brush (2 feet); GS1; Grass"),
        ("Fire behavior", "Active; Creeping; Smoldering"),
        ("Landowner category", "Federal"),
        ("Of note", "Over 100,000 acres, and a Type 1 Incident."),
    ]


def test_description_rows_marks_missing_values_with_hyphens() -> None:
    description = peri_scribe.kml_descriptions.FireDescription()
    assert peri_scribe.kml_descriptions.description_rows(description) == [
        ("Area", "--"),
        ("Exterior perimeter", "--"),
        ("Containment", "--"),
        ("Cost to date", "--"),
        ("Estimated final cost", "--"),
        ("Personnel", "--"),
        ("Source", "--"),
        ("Identifier", "--"),
        ("Mission", "--"),
        ("Protecting unit", "--"),
        ("Discovery", "--"),
        ("Last update", "--"),
        ("Initial response", "--"),
        ("Incident type", "--"),
        ("Incident complexity", "--"),
        ("Fuel model", "--"),
        ("Fire behavior", "--"),
        ("Landowner category", "--"),
        ("Of note", "--"),
    ]


def test_description_html_wraps_table_in_cdata() -> None:
    html = peri_scribe.kml_descriptions.description_html(full_description())
    assert html.startswith("<![CDATA[")
    assert html.endswith("]]>")
    assert "<h3" not in html
    assert "<b>Status</b>" not in html
    assert "102,003 acres" in html
    assert "08/01 22:30 PDT" in html


def test_description_html_sizes_the_text() -> None:
    html = peri_scribe.kml_descriptions.description_html(full_description())
    body_size = peri_scribe.kml_descriptions.BODY_FONT_SIZE_IN_PIXELS
    assert (
        f'<table cellspacing="0" cellpadding="4" '
        f'style="font-size:{body_size}px;">' in html
    )


def test_description_html_alternates_row_backgrounds() -> None:
    html = peri_scribe.kml_descriptions.description_html(full_description())
    color = peri_scribe.kml_descriptions.ALT_ROW_BACKGROUND_COLOR
    background = f'<tr style="background-color:{color};"'
    assert f"{background}><td><b>Area</b></td>" in html
    assert "<tr><td><b>Exterior perimeter</b></td>" in html
    assert f"{background}><td><b>Containment</b></td>" in html
    assert "<tr><td><b>Cost to date</b></td>" in html


def test_description_html_includes_images_after_table() -> None:
    html = peri_scribe.kml_descriptions.description_html(
        full_description(),
        ("id-bug-area.png", "id-bug-cost.png"),
    )
    assert html.index("</table>") < html.index("id-bug-area.png")
    assert '<img src="id-bug-area.png" />' in html
    assert '<img src="id-bug-cost.png" />' in html


def test_description_html_escapes_image_filenames() -> None:
    html = peri_scribe.kml_descriptions.description_html(
        full_description(),
        ('a&b"c.png',),
    )
    assert '<img src="a&amp;b&quot;c.png" />' in html
