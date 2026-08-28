"""Tests for peri_scribe.kml_row_values."""

from __future__ import annotations

import datetime
import json

import geopandas
import pandas as pd
import pytest
import shapely.geometry

import peri_scribe.kml_fire_data
import peri_scribe.kml_row_values
import tests.kml_helpers


def test_latest_matching_row_matches_by_identifier() -> None:
    later = datetime.datetime(2026, 8, 6, 20, 0, tzinfo=datetime.UTC)
    frame = tests.kml_helpers.geometry_frame(
        [
            ("id-a", "Bug", tests.kml_helpers.square(1.0)),
            ("id-a", "Bug", tests.kml_helpers.square(2.0)),
        ],
        observation_times=[
            datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC),
            later,
        ],
    )
    row = peri_scribe.kml_row_values.latest_matching_row(
        frame,
        frozenset({"id-a"}),
        "Bug",
    )
    assert row is not None
    assert row["observation_time"] == later


def test_latest_matching_row_matches_by_name_without_identifier() -> None:
    frame = tests.kml_helpers.geometry_frame([
        (None, "Bug", tests.kml_helpers.square(1.0)),
        (None, "Bug", tests.kml_helpers.square(2.0)),
    ])
    row = peri_scribe.kml_row_values.latest_matching_row(frame, frozenset(), "Bug")
    assert row is not None
    assert row["fire_name"] == "Bug"


def test_latest_matching_row_returns_none_without_match() -> None:
    frame = tests.kml_helpers.geometry_frame([
        ("id-a", "Bug", tests.kml_helpers.square(1.0)),
    ])
    assert (
        peri_scribe.kml_row_values.latest_matching_row(
            frame,
            frozenset({"id-b"}),
            "Bug",
        )
        is None
    )


def test_column_value_returns_none_for_missing_row_or_column() -> None:
    frame = tests.kml_helpers.geometry_frame([
        ("id-a", "Bug", tests.kml_helpers.square(1.0)),
    ])
    row = frame.iloc[0]
    assert peri_scribe.kml_row_values.column_value(row, "fire_name") == "Bug"
    assert peri_scribe.kml_row_values.column_value(row, "not_a_column") is None
    assert peri_scribe.kml_row_values.column_value(None, "fire_name") is None


def test_text_value_returns_none_for_blank() -> None:
    frame = geopandas.GeoDataFrame(
        {
            "fire_identifier": ["id-a"],
            "fire_name": ["Bug"],
            "mission": ["  "],
        },
        geometry=[tests.kml_helpers.square(1.0)],
        crs="EPSG:4326",
    )
    row = frame.iloc[0]
    assert peri_scribe.kml_row_values.text_value(row, "mission") is None
    assert peri_scribe.kml_row_values.text_value(row, "fire_name") == "Bug"
    assert peri_scribe.kml_row_values.text_value(None, "fire_name") is None


def test_float_value_reads_numbers_and_rejects_non_numeric() -> None:
    frame = geopandas.GeoDataFrame(
        {
            "fire_identifier": ["id-a"],
            "fire_name": ["Bug"],
            "area_acres": [12.5],
            "mission": ["x"],
        },
        geometry=[tests.kml_helpers.square(1.0)],
        crs="EPSG:4326",
    )
    row = frame.iloc[0]
    assert peri_scribe.kml_row_values.float_value(row, "area_acres") == pytest.approx(
        12.5,
    )
    assert peri_scribe.kml_row_values.float_value(row, "mission") is None
    assert peri_scribe.kml_row_values.float_value(None, "area_acres") is None


def test_as_datetime_parses_strings_and_timestamps() -> None:
    expected = datetime.datetime(2026, 8, 5, 20, 30, tzinfo=datetime.UTC)
    assert peri_scribe.kml_row_values.as_datetime(None) is None
    assert peri_scribe.kml_row_values.as_datetime("2026-08-05T20:30:00Z") == expected
    assert (
        peri_scribe.kml_row_values.as_datetime(pd.Timestamp("2026-08-05T20:30:00Z"))
        == expected
    )
    assert peri_scribe.kml_row_values.as_datetime("not a date") is None


def test_datetime_value_reads_a_column() -> None:
    expected = datetime.datetime(2026, 8, 5, 20, 30, tzinfo=datetime.UTC)
    frame = tests.kml_helpers.geometry_frame(
        [("id-a", "Bug", tests.kml_helpers.square(1.0))],
        observation_times=[expected],
    )
    assert (
        peri_scribe.kml_row_values.datetime_value(frame.iloc[0], "observation_time")
        == expected
    )
    assert peri_scribe.kml_row_values.datetime_value(None, "observation_time") is None


def test_source_attribute_value_reads_json() -> None:
    frame = geopandas.GeoDataFrame(
        {
            "fire_identifier": ["id-a"],
            "fire_name": ["Bug"],
            "source_attributes": [json.dumps({"POOJurisdictionalUnit": "CANOD"})],
        },
        geometry=[tests.kml_helpers.square(1.0)],
        crs="EPSG:4326",
    )
    assert (
        peri_scribe.kml_row_values.source_attribute_value(
            frame.iloc[0],
            "POOJurisdictionalUnit",
        )
        == "CANOD"
    )
    assert (
        peri_scribe.kml_row_values.source_attribute_value(frame.iloc[0], "Missing")
        is None
    )
    assert (
        peri_scribe.kml_row_values.source_attribute_value(None, "POOJurisdictionalUnit")
        is None
    )


def test_source_attribute_value_rejects_invalid_json() -> None:
    frame = geopandas.GeoDataFrame(
        {
            "fire_identifier": ["id-a"],
            "fire_name": ["Bug"],
            "source_attributes": ["not json"],
        },
        geometry=[tests.kml_helpers.square(1.0)],
        crs="EPSG:4326",
    )
    assert peri_scribe.kml_row_values.source_attribute_value(frame.iloc[0], "X") is None


def test_source_attribute_value_accepts_decoded_dict() -> None:
    frame = geopandas.GeoDataFrame(
        {
            "fire_identifier": ["id-a"],
            "fire_name": ["Bug"],
            "source_attributes": [{"POOJurisdictionalUnit": "CANOD"}],
        },
        geometry=[tests.kml_helpers.square(1.0)],
        crs="EPSG:4326",
    )
    assert (
        peri_scribe.kml_row_values.source_attribute_value(
            frame.iloc[0],
            "POOJurisdictionalUnit",
        )
        == "CANOD"
    )


def test_source_attribute_value_rejects_non_dict_json() -> None:
    frame = geopandas.GeoDataFrame(
        {
            "fire_identifier": ["id-a"],
            "fire_name": ["Bug"],
            "source_attributes": [json.dumps(["a", "b"])],
        },
        geometry=[tests.kml_helpers.square(1.0)],
        crs="EPSG:4326",
    )
    assert peri_scribe.kml_row_values.source_attribute_value(frame.iloc[0], "X") is None


def test_source_text_value_returns_none_for_blank() -> None:
    frame = geopandas.GeoDataFrame(
        {
            "fire_identifier": ["id-a"],
            "fire_name": ["Bug"],
            "source_attributes": [json.dumps({"Unit": "  "})],
        },
        geometry=[tests.kml_helpers.square(1.0)],
        crs="EPSG:4326",
    )
    assert peri_scribe.kml_row_values.source_text_value(frame.iloc[0], "Unit") is None
    assert (
        peri_scribe.kml_row_values.source_text_value(frame.iloc[0], "Missing") is None
    )


def test_numbered_source_text_orders_by_slot_number_and_dedupes() -> None:
    perimeter = geopandas.GeoDataFrame(
        {
            "fire_identifier": ["id-a"],
            "fire_name": ["Bug"],
            "source_attributes": [
                json.dumps(
                    {
                        "attr_FireBehaviorGeneral": "Active",
                        "attr_FireBehaviorGeneral2": "Running",
                    },
                ),
            ],
        },
        geometry=[tests.kml_helpers.square(1.0)],
        crs="EPSG:4326",
    )
    point = geopandas.GeoDataFrame(
        {
            "fire_identifier": ["id-a"],
            "fire_name": ["Bug"],
            "source_attributes": [
                json.dumps(
                    {
                        "FireBehaviorGeneral2": "Running",
                        "FireBehaviorGeneral3": "Smoldering",
                    },
                ),
            ],
        },
        geometry=[shapely.geometry.Point(1.0, 1.0)],
        crs="EPSG:4326",
    )
    assert (
        peri_scribe.kml_row_values.numbered_source_text(
            perimeter.iloc[0],
            point.iloc[0],
            peri_scribe.kml_fire_data.FIRE_BEHAVIOR_ATTRIBUTE_KEYS,
        )
        == "Active; Running; Smoldering"
    )
    empty = geopandas.GeoDataFrame(
        {
            "fire_identifier": ["id-a"],
            "fire_name": ["Bug"],
            "source_attributes": [json.dumps({})],
        },
        geometry=[shapely.geometry.Point(1.0, 1.0)],
        crs="EPSG:4326",
    )
    assert (
        peri_scribe.kml_row_values.numbered_source_text(
            None,
            empty.iloc[0],
            peri_scribe.kml_fire_data.FIRE_BEHAVIOR_ATTRIBUTE_KEYS,
        )
        is None
    )


def test_source_label_names_known_sources() -> None:
    assert peri_scribe.kml_row_values.source_label("firis_perimeter") == "FIRIS / NIFC"
    assert peri_scribe.kml_row_values.source_label("wfigs_perimeter") == "WFIGS"
    assert peri_scribe.kml_row_values.source_label("unknown") is None
    assert peri_scribe.kml_row_values.source_label(None) is None


def test_source_attributes_dictionary_parses_json_strings() -> None:
    assert peri_scribe.kml_row_values.source_attributes_dictionary(
        json.dumps({"TotalIncidentPersonnel": 400}),
    ) == {"TotalIncidentPersonnel": 400}


def test_source_attributes_dictionary_accepts_decoded_dict() -> None:
    assert peri_scribe.kml_row_values.source_attributes_dictionary(
        {"TotalIncidentPersonnel": 400},
    ) == {"TotalIncidentPersonnel": 400}


def test_source_attributes_dictionary_rejects_missing_or_invalid_values() -> None:
    assert peri_scribe.kml_row_values.source_attributes_dictionary(None) is None
    assert peri_scribe.kml_row_values.source_attributes_dictionary("not json") is None
    assert (
        peri_scribe.kml_row_values.source_attributes_dictionary(json.dumps([1, 2]))
        is None
    )


def test_source_attribute_number_reads_numeric_attributes() -> None:
    frame = geopandas.GeoDataFrame(
        {
            "fire_identifier": ["id-a"],
            "fire_name": ["Bug"],
            "source_attributes": [
                json.dumps({"TotalIncidentPersonnel": 400, "Unit": "CANOD"}),
            ],
        },
        geometry=[tests.kml_helpers.square(1.0)],
        crs="EPSG:4326",
    )
    row = frame.iloc[0]
    assert peri_scribe.kml_row_values.source_attribute_number(
        row,
        "TotalIncidentPersonnel",
    ) == pytest.approx(400.0)
    assert peri_scribe.kml_row_values.source_attribute_number(row, "Unit") is None
    assert peri_scribe.kml_row_values.source_attribute_number(row, "Missing") is None
    assert peri_scribe.kml_row_values.source_attribute_number(None, "Unit") is None


def test_first_source_number_prefers_point_feed() -> None:
    perimeter = geopandas.GeoDataFrame(
        {
            "fire_identifier": ["id-a"],
            "fire_name": ["Bug"],
            "source_attributes": [json.dumps({"attr_TotalIncidentPersonnel": 400})],
        },
        geometry=[tests.kml_helpers.square(1.0)],
        crs="EPSG:4326",
    )
    point = geopandas.GeoDataFrame(
        {
            "fire_identifier": ["id-a"],
            "fire_name": ["Bug"],
            "source_attributes": [json.dumps({"TotalIncidentPersonnel": 500})],
        },
        geometry=[shapely.geometry.Point(1.0, 1.0)],
        crs="EPSG:4326",
    )
    assert peri_scribe.kml_row_values.first_source_number(
        perimeter.iloc[0],
        point.iloc[0],
        "TotalIncidentPersonnel",
        "attr_TotalIncidentPersonnel",
    ) == pytest.approx(500.0)


def test_first_source_number_falls_back_to_perimeter_feed() -> None:
    perimeter = geopandas.GeoDataFrame(
        {
            "fire_identifier": ["id-a"],
            "fire_name": ["Bug"],
            "source_attributes": [json.dumps({"attr_TotalIncidentPersonnel": 400})],
        },
        geometry=[tests.kml_helpers.square(1.0)],
        crs="EPSG:4326",
    )
    point = geopandas.GeoDataFrame(
        {
            "fire_identifier": ["id-a"],
            "fire_name": ["Bug"],
            "source_attributes": [json.dumps({})],
        },
        geometry=[shapely.geometry.Point(1.0, 1.0)],
        crs="EPSG:4326",
    )
    assert peri_scribe.kml_row_values.first_source_number(
        perimeter.iloc[0],
        point.iloc[0],
        "TotalIncidentPersonnel",
        "attr_TotalIncidentPersonnel",
    ) == pytest.approx(400.0)


def test_first_source_number_returns_none_without_keys() -> None:
    assert (
        peri_scribe.kml_row_values.first_source_number(
            None,
            None,
            None,
            None,
        )
        is None
    )


def test_first_source_number_returns_none_for_missing_rows() -> None:
    assert (
        peri_scribe.kml_row_values.first_source_number(
            None,
            None,
            "TotalIncidentPersonnel",
            "attr_TotalIncidentPersonnel",
        )
        is None
    )
