"""Tests for peri_scribe.geo.package."""

from __future__ import annotations

import datetime
import json
import typing

import pandas as pd
import pytest
import shapely.geometry

import peri_scribe.geo.package
import peri_scribe.geo.parsing
import peri_scribe.models
import tests.peri_scribe.geo.geo_helpers


def test_fire_status_from_classifies_active_and_inactive() -> None:
    assert (
        peri_scribe.geo.parsing.fire_status_from("Active")
        is tests.peri_scribe.geo.geo_helpers.ACTIVE
    )
    assert (
        peri_scribe.geo.parsing.fire_status_from("inactive")
        is tests.peri_scribe.geo.geo_helpers.INACTIVE
    )
    assert (
        peri_scribe.geo.parsing.fire_status_from(1)
        is tests.peri_scribe.geo.geo_helpers.ACTIVE
    )
    assert (
        peri_scribe.geo.parsing.fire_status_from(0)
        is tests.peri_scribe.geo.geo_helpers.INACTIVE
    )
    assert (
        peri_scribe.geo.parsing.fire_status_from("TRUE")
        is tests.peri_scribe.geo.geo_helpers.ACTIVE
    )
    assert (
        peri_scribe.geo.parsing.fire_status_from("false")
        is tests.peri_scribe.geo.geo_helpers.INACTIVE
    )


def test_fire_status_from_returns_none_for_blank_values() -> None:
    assert peri_scribe.geo.parsing.fire_status_from(None) is None
    assert peri_scribe.geo.parsing.fire_status_from("") is None
    assert peri_scribe.geo.parsing.fire_status_from("   ") is None


def test_fire_status_from_raises_for_unknown_value() -> None:
    with pytest.raises(ValueError, match="Unknown fire status value"):
        peri_scribe.geo.parsing.fire_status_from("Approved")


def test_is_missing_detects_none() -> None:
    assert peri_scribe.geo.parsing.is_missing(None) is True


def test_is_missing_detects_nan() -> None:
    assert peri_scribe.geo.parsing.is_missing(float("nan")) is True


def test_is_missing_treats_strings_as_present() -> None:
    assert peri_scribe.geo.parsing.is_missing("") is False


def test_is_missing_treats_non_scalar_values_as_present() -> None:
    assert peri_scribe.geo.parsing.is_missing([1, 2]) is False


def test_normalize_identifier() -> None:
    assert peri_scribe.geo.parsing.normalize_identifier(None) is None
    assert peri_scribe.geo.parsing.normalize_identifier(float("nan")) is None
    assert peri_scribe.geo.parsing.normalize_identifier("") is None
    assert peri_scribe.geo.parsing.normalize_identifier("   ") is None
    assert (
        peri_scribe.geo.parsing.normalize_identifier(
            "{286B7F1D-8945-4A5D-9D81-5235C18AF1FE}",
        )
        == "286b7f1d-8945-4a5d-9d81-5235c18af1fe"
    )
    assert (
        peri_scribe.geo.parsing.normalize_identifier(
            " 2026-CACDD-007101 ",
        )
        == "2026-cacdd-007101"
    )


def test_is_complex_child_from() -> None:
    assert peri_scribe.geo.parsing.is_complex_child_from(1) is True
    assert peri_scribe.geo.parsing.is_complex_child_from("TRUE") is True
    assert peri_scribe.geo.parsing.is_complex_child_from("yes") is True
    assert peri_scribe.geo.parsing.is_complex_child_from(0) is False
    assert peri_scribe.geo.parsing.is_complex_child_from("false") is False
    assert peri_scribe.geo.parsing.is_complex_child_from("no") is False
    assert peri_scribe.geo.parsing.is_complex_child_from(None) is False
    assert peri_scribe.geo.parsing.is_complex_child_from("") is False
    with pytest.raises(ValueError, match="Unknown complex child value"):
        peri_scribe.geo.parsing.is_complex_child_from("maybe")


def test_fire_name_from_returns_stripped_name_or_none() -> None:
    assert peri_scribe.geo.parsing.fire_name_from("  Park Fire ") == "Park Fire"
    assert peri_scribe.geo.parsing.fire_name_from(None) is None
    assert peri_scribe.geo.parsing.fire_name_from(float("nan")) is None
    assert peri_scribe.geo.parsing.fire_name_from("   ") is None


def test_mission_name_from_parses_unit_name_and_tail() -> None:
    assert peri_scribe.geo.parsing.mission_name_from(
        "CA-LNU-RUMSEY-UPDATED-N40Y",
    ) == peri_scribe.models.MissionName(
        name="RUMSEY-UPDATED",
        base_name="RUMSEY",
    )
    assert peri_scribe.geo.parsing.mission_name_from(
        "NV-CCD-BUG-N57B",
    ) == peri_scribe.models.MissionName(name="BUG", base_name="BUG")


def test_mission_name_from_handles_bare_names() -> None:
    assert peri_scribe.geo.parsing.mission_name_from(
        "BUG",
    ) == peri_scribe.models.MissionName(name="BUG", base_name="BUG")
    assert peri_scribe.geo.parsing.mission_name_from("BORDER 6") == (
        peri_scribe.models.MissionName(name="BORDER 6", base_name="BORDER 6")
    )


def test_mission_name_from_returns_none_for_blank() -> None:
    assert peri_scribe.geo.parsing.mission_name_from(None) is None
    assert peri_scribe.geo.parsing.mission_name_from(float("nan")) is None
    assert peri_scribe.geo.parsing.mission_name_from("   ") is None


def test_mission_name_from_returns_none_without_a_fire_name() -> None:
    assert peri_scribe.geo.parsing.mission_name_from("CA-LNU-N40Y") is None


def test_observation_time_from_parses_datetime_and_iso() -> None:
    naive = datetime.datetime(2026, 8, 9, 1, 28, 25)
    assert peri_scribe.geo.parsing.observation_time_from(naive) == (
        datetime.datetime(2026, 8, 9, 1, 28, 25, tzinfo=datetime.UTC)
    )
    assert peri_scribe.geo.parsing.observation_time_from("2026-08-09T01:28:25") == (
        datetime.datetime(2026, 8, 9, 1, 28, 25, tzinfo=datetime.UTC)
    )


def test_observation_time_from_returns_none_for_blank_or_invalid() -> None:
    assert peri_scribe.geo.parsing.observation_time_from(None) is None
    assert peri_scribe.geo.parsing.observation_time_from(float("nan")) is None
    assert peri_scribe.geo.parsing.observation_time_from("not a date") is None
    assert peri_scribe.geo.parsing.observation_time_from(12345) is None


def test_numeric_value_returns_none_for_bool() -> None:
    value = True
    assert peri_scribe.geo.parsing.numeric_value(value) is None


def test_numeric_value_parses_strings() -> None:
    assert peri_scribe.geo.parsing.numeric_value("12.5") == pytest.approx(12.5)


def test_numeric_value_returns_none_for_unparsable_string() -> None:
    assert peri_scribe.geo.parsing.numeric_value("soon") is None


def test_numeric_value_returns_none_for_other_types() -> None:
    assert peri_scribe.geo.parsing.numeric_value({"a": 1}) is None


def test_geometries_describe_same_shape_accepts_re_serialized_geometry() -> None:
    ring = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
    reversed_ring = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]
    assert peri_scribe.geo.parsing.geometries_describe_same_shape(
        shapely.geometry.Polygon(ring),
        shapely.geometry.Polygon(reversed_ring),
    )


def test_geometries_describe_same_shape_accepts_identical_geometry() -> None:
    polygon = shapely.geometry.Polygon(
        [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)],
    )
    assert peri_scribe.geo.parsing.geometries_describe_same_shape(polygon, polygon)


def test_geometries_describe_same_shape_accepts_single_part_multi_polygon() -> None:
    polygon = shapely.geometry.Polygon(
        [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)],
    )
    assert peri_scribe.geo.parsing.geometries_describe_same_shape(
        polygon,
        shapely.geometry.MultiPolygon([polygon]),
    )


def test_geometries_describe_same_shape_rejects_different_shapes() -> None:
    first = shapely.geometry.Polygon(
        [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)],
    )
    different = shapely.geometry.Polygon(
        [(0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0), (0.0, 0.0)],
    )
    assert not peri_scribe.geo.parsing.geometries_describe_same_shape(
        first,
        different,
    )


def test_geometries_describe_same_shape_treats_missing_geometries() -> None:
    assert peri_scribe.geo.parsing.geometries_describe_same_shape(None, None)
    assert not peri_scribe.geo.parsing.geometries_describe_same_shape(
        None,
        shapely.geometry.Point(0, 0),
    )
    assert not peri_scribe.geo.parsing.geometries_describe_same_shape(
        shapely.geometry.Point(0, 0),
        None,
    )


def test_geometries_describe_same_shape_treats_empty_geometries() -> None:
    empty = shapely.geometry.Polygon()
    assert peri_scribe.geo.parsing.geometries_describe_same_shape(empty, empty)
    assert not peri_scribe.geo.parsing.geometries_describe_same_shape(
        empty,
        shapely.geometry.Point(0, 0),
    )


def test_object_id_from_returns_none_for_missing_value() -> None:
    assert (
        peri_scribe.geo.parsing.object_id_from(
            pd.Series({"OBJECTID": float("nan")}),
        )
        is None
    )


def test_row_attributes_excludes_geometry_column() -> None:
    row = pd.Series({
        "OBJECTID": 1,
        "geometry": shapely.geometry.Point(0, 0),
    })
    assert peri_scribe.geo.parsing.row_attributes(row, "geometry") == {"OBJECTID": 1}


def test_observation_time_from_preserves_aware_datetime() -> None:
    aware = datetime.datetime(
        2026,
        8,
        16,
        0,
        10,
        45,
        tzinfo=datetime.timezone(datetime.timedelta(hours=1)),
    )
    assert peri_scribe.geo.parsing.observation_time_from(aware) == aware.astimezone(
        datetime.UTC,
    )


def test_record_cache_row_values_are_json_safe() -> None:
    row = peri_scribe.geo.package.FireRowRecord(
        record=peri_scribe.models.FireRecord(
            name="Park Fire",
            status=tests.peri_scribe.geo.geo_helpers.ACTIVE,
        ),
        object_id=None,
        source_name="sources",
        attributes={
            "when": datetime.datetime(2026, 8, 29, tzinfo=datetime.UTC),
            "count": 5,
            "odd": object(),
        },
    )
    columns = row.to_row(0)
    attributes = json.loads(typing.cast("str", columns[12]))
    json_safe_count = 5
    assert attributes["when"] == "2026-08-29T00:00:00+00:00"
    assert attributes["count"] == json_safe_count
    assert isinstance(attributes["odd"], str)
