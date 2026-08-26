"""Tests for peri_scribe.history_attributes."""

from __future__ import annotations

import datetime

import pytest

import peri_scribe.history_attributes


def test_attribute_value_returns_first_present_value() -> None:
    first = 10
    second = 11
    assert (
        peri_scribe.history_attributes.attribute_value(
            {"area_acres": first, "poly_GISAcres": second},
            "area_acres",
            "poly_GISAcres",
        )
        == first
    )
    assert (
        peri_scribe.history_attributes.attribute_value(
            {"poly_GISAcres": second},
            "area_acres",
            "poly_GISAcres",
        )
        == second
    )
    assert peri_scribe.history_attributes.attribute_value({}, "area_acres") is None


def test_text_attribute_returns_non_blank_text() -> None:
    assert (
        peri_scribe.history_attributes.text_attribute({"type": " Heat "}, "type")
        == "Heat"
    )
    assert peri_scribe.history_attributes.text_attribute({"type": "  "}, "type") is None
    assert peri_scribe.history_attributes.text_attribute({}, "type") is None


def test_float_attribute_returns_number_or_none() -> None:
    expected = 10.5
    assert peri_scribe.history_attributes.float_attribute(
        {"area_acres": "10.5"},
        "area_acres",
    ) == pytest.approx(expected)
    assert (
        peri_scribe.history_attributes.float_attribute(
            {"area_acres": "x"},
            "area_acres",
        )
        is None
    )
    assert peri_scribe.history_attributes.float_attribute({}, "area_acres") is None
    assert (
        peri_scribe.history_attributes.float_attribute(
            {"area_acres": True},
            "area_acres",
        )
        is None
    )
    assert (
        peri_scribe.history_attributes.float_attribute(
            {"area_acres": [1, 2]},
            "area_acres",
        )
        is None
    )


def test_datetime_attribute_returns_datetime_or_none() -> None:
    value = "2026-08-16T00:10:45"
    expected = datetime.datetime(2026, 8, 16, 0, 10, 45, tzinfo=datetime.UTC)
    assert (
        peri_scribe.history_attributes.datetime_attribute({"t": value}, "t") == expected
    )
    assert peri_scribe.history_attributes.datetime_attribute({}, "t") is None
