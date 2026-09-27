"""Regression tests for typed field priority in perimeter history."""

import datetime

import pytest

import peri_scribe.perimeters.history_attributes


def test_text_attribute_blank_source_does_not_hide_poly_source() -> None:
    assert (
        peri_scribe.perimeters.history_attributes.text_attribute(
            {"source": "  ", "poly_Source": " FIRIS "},
            "source",
            "poly_Source",
        )
        == "FIRIS"
    )


@pytest.mark.parametrize("value", ["invalid", "", True, "NaN", "Infinity"])
def test_float_attribute_unusable_acreage_does_not_hide_zero(value: object) -> None:
    assert (
        peri_scribe.perimeters.history_attributes.float_attribute(
            {"area_acres": value, "poly_GISAcres": 0},
            "area_acres",
            "poly_GISAcres",
        )
        == 0
    )


@pytest.mark.parametrize("value", ["invalid", "", True])
def test_datetime_attribute_invalid_edit_date_does_not_hide_modified_date(
    value: object,
) -> None:
    assert peri_scribe.perimeters.history_attributes.datetime_attribute(
        {"EditDate": value, "attr_ModifiedOnDateTime_dt": "2026-08-20T12:00:00Z"},
        "EditDate",
        "attr_ModifiedOnDateTime_dt",
    ) == datetime.datetime(2026, 8, 20, 12, tzinfo=datetime.UTC)
