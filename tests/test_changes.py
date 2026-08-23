"""Tests for peri_scribe.changes."""

from __future__ import annotations

import datetime
import pathlib
import typing

import geopandas
import pyproj
import pytest
import shapely.geometry

import peri_scribe.changes
import peri_scribe.geo_package
import peri_scribe.models
import peri_scribe.snapshots
from tests.factories import change_dataframe, change_feed


UTC = datetime.UTC

SAMPLE_FEATURE_ROW = (1, "a", (0.0, 0.0))


def modified_dataframe(
    rows: list[tuple[int, str, tuple[float, float]]],
) -> geopandas.GeoDataFrame:
    """Return a GeoDataFrame with OBJECTID and modified-time columns.

    Args:
        rows: The OBJECTID, modified time, and coordinates of each feature.

    Returns:
        The GeoDataFrame.
    """
    return geopandas.GeoDataFrame(
        {
            "OBJECTID": [row[0] for row in rows],
            "ModifiedOnDateTime_dt": [row[1] for row in rows],
        },
        geometry=[shapely.geometry.Point(row[2]) for row in rows],
        crs=pyproj.CRS.from_epsg(4326),
    )


def test_parse_iso_datetime_returns_datetime() -> None:
    assert peri_scribe.changes.parse_iso_datetime(
        "2026-01-01T00:00:00",
    ) == datetime.datetime(2026, 1, 1, 0, 0, 0)


def test_parse_iso_datetime_returns_none_for_invalid() -> None:
    assert peri_scribe.changes.parse_iso_datetime("not-a-date") is None


def test_modified_datetime_from_returns_none_for_none() -> None:
    assert peri_scribe.changes.modified_datetime_from(None) is None


def test_modified_datetime_from_returns_none_for_nan() -> None:
    assert peri_scribe.changes.modified_datetime_from(float("nan")) is None


def test_modified_datetime_from_returns_none_for_bool() -> None:
    assert peri_scribe.changes.modified_datetime_from(value=True) is None


def test_modified_datetime_from_returns_none_for_unknown() -> None:
    assert peri_scribe.changes.modified_datetime_from(object()) is None


def test_modified_datetime_from_makes_naive_datetime_utc_aware() -> None:
    result = peri_scribe.changes.modified_datetime_from(
        datetime.datetime(2026, 1, 1, 0, 0, 0),
    )
    assert result == datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def test_modified_datetime_from_converts_aware_datetime_to_utc() -> None:
    aware = datetime.datetime(
        2026,
        1,
        1,
        12,
        0,
        tzinfo=datetime.timezone(datetime.timedelta(hours=2)),
    )
    result = peri_scribe.changes.modified_datetime_from(aware)
    assert result == datetime.datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)


def test_modified_datetime_from_parses_iso_string() -> None:
    result = peri_scribe.changes.modified_datetime_from("2026-01-01T00:00:00Z")
    assert result == datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def test_modified_datetime_from_returns_none_for_invalid_string() -> None:
    assert peri_scribe.changes.modified_datetime_from("nope") is None


def test_modified_datetime_from_parses_epoch_milliseconds() -> None:
    result = peri_scribe.changes.modified_datetime_from(0)
    assert result == datetime.datetime(1970, 1, 1, 0, 0, 0, tzinfo=UTC)


def test_existing_features_returns_none_without_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = change_feed()
    monkeypatch.setattr(
        peri_scribe.snapshots,
        "existing_source_files",
        lambda _directory: [],
    )
    assert peri_scribe.changes.existing_features(pathlib.Path("/sources"), feed) is None


def test_existing_features_returns_none_without_object_id_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = change_feed()
    monkeypatch.setattr(
        peri_scribe.snapshots,
        "existing_source_files",
        lambda _directory: [
            peri_scribe.snapshots.SourceFile(serial_number=0, last_edit_timestamp=0),
        ],
    )
    monkeypatch.setattr(
        peri_scribe.geo_package,
        "read_layer_dataframe",
        lambda _path, _feed: change_dataframe([SAMPLE_FEATURE_ROW]).drop(
            columns=["OBJECTID"],
        ),
    )
    assert peri_scribe.changes.existing_features(pathlib.Path("/sources"), feed) is None


def test_latest_modified_datetime_returns_none_without_existing() -> None:
    feed = change_feed()
    assert peri_scribe.changes.latest_modified_datetime(None, feed) is None


def test_latest_modified_datetime_returns_none_for_empty() -> None:
    feed = change_feed()
    empty = change_dataframe([])
    assert peri_scribe.changes.latest_modified_datetime(empty, feed) is None


def test_latest_modified_datetime_returns_none_without_modified_column() -> None:
    feed = change_feed()
    existing = change_dataframe([SAMPLE_FEATURE_ROW])
    assert peri_scribe.changes.latest_modified_datetime(existing, feed) is None


def test_latest_modified_datetime_returns_maximum() -> None:
    feed = change_feed()
    existing = modified_dataframe([
        (1, "2026-01-01T00:00:00Z", (0.0, 0.0)),
        (2, "2026-02-01T00:00:00Z", (1.0, 1.0)),
    ])
    result = peri_scribe.changes.latest_modified_datetime(existing, feed)
    assert result == datetime.datetime(2026, 2, 1, 0, 0, 0, tzinfo=UTC)


def test_latest_modified_datetime_returns_none_when_no_values_parse() -> None:
    feed = change_feed()
    existing = modified_dataframe([
        (1, "nope", (0.0, 0.0)),
        (2, "also-nope", (1.0, 1.0)),
    ])
    assert peri_scribe.changes.latest_modified_datetime(existing, feed) is None


def test_stored_object_ids_returns_empty_without_existing() -> None:
    assert peri_scribe.changes.stored_object_ids(None) == set()


def test_stored_object_ids_returns_empty_without_object_id_column() -> None:
    existing = typing.cast(
        "geopandas.GeoDataFrame",
        change_dataframe([SAMPLE_FEATURE_ROW]).drop(columns=["OBJECTID"]),
    )
    assert peri_scribe.changes.stored_object_ids(existing) == set()


def test_stored_object_ids_returns_object_ids() -> None:
    existing = change_dataframe([SAMPLE_FEATURE_ROW, (2, "b", (1.0, 1.0))])
    assert peri_scribe.changes.stored_object_ids(existing) == {1, 2}


def status_dataframe(
    rows: list[tuple[int, object, tuple[float, float]]],
) -> geopandas.GeoDataFrame:
    """Return a GeoDataFrame with OBJECTID and status columns.

    Args:
        rows: The OBJECTID, raw status value, and coordinates of each feature.

    Returns:
        The GeoDataFrame.
    """
    return geopandas.GeoDataFrame(
        {
            "OBJECTID": [row[0] for row in rows],
            "status": [row[1] for row in rows],
        },
        geometry=[shapely.geometry.Point(row[2]) for row in rows],
        crs=pyproj.CRS.from_epsg(4326),
    )


def test_sql_literal_quotes_text() -> None:
    assert peri_scribe.changes.sql_literal("Inactive") == "'Inactive'"


def test_sql_literal_formats_booleans() -> None:
    assert peri_scribe.changes.sql_literal(value=True) == "true"
    assert peri_scribe.changes.sql_literal(value=False) == "false"


def test_sql_literal_formats_numbers() -> None:
    assert peri_scribe.changes.sql_literal(0) == "0"
    assert peri_scribe.changes.sql_literal(1.0) == "1"


def test_sql_literal_raises_for_unsupported_type() -> None:
    with pytest.raises(ValueError, match="Unsupported SQL literal"):
        peri_scribe.changes.sql_literal(object())


def test_stored_status_object_ids_returns_empty_without_existing() -> None:
    feed = change_feed()
    assert (
        peri_scribe.changes.stored_status_object_ids(
            None,
            feed,
            peri_scribe.models.FireStatus.ACTIVE,
        )
        == []
    )


def test_stored_status_object_ids_returns_empty_without_status_column() -> None:
    feed = change_feed()
    existing = change_dataframe([SAMPLE_FEATURE_ROW])
    assert (
        peri_scribe.changes.stored_status_object_ids(
            existing,
            feed,
            peri_scribe.models.FireStatus.ACTIVE,
        )
        == []
    )


def test_stored_status_object_ids_returns_empty_without_object_id_column() -> None:
    feed = change_feed()
    existing = status_dataframe([(1, "Active", (0.0, 0.0))]).drop(
        columns=["OBJECTID"],
    )
    assert (
        peri_scribe.changes.stored_status_object_ids(
            typing.cast("geopandas.GeoDataFrame", existing),
            feed,
            peri_scribe.models.FireStatus.ACTIVE,
        )
        == []
    )


def test_stored_status_object_ids_selects_status_and_ignores_unknown() -> None:
    feed = change_feed()
    existing = status_dataframe([
        (1, "Active", (0.0, 0.0)),
        (2, "Inactive", (1.0, 1.0)),
        (3, "Active", (2.0, 2.0)),
        (4, "unknown-status", (3.0, 3.0)),
    ])
    assert peri_scribe.changes.stored_status_object_ids(
        existing,
        feed,
        peri_scribe.models.FireStatus.ACTIVE,
    ) == [1, 3]
    assert peri_scribe.changes.stored_status_object_ids(
        existing,
        feed,
        peri_scribe.models.FireStatus.INACTIVE,
    ) == [2]


def test_stored_status_literals_returns_empty_without_existing() -> None:
    feed = change_feed()
    assert (
        peri_scribe.changes.stored_status_literals(
            None,
            feed,
            peri_scribe.models.FireStatus.INACTIVE,
        )
        == ()
    )


def test_stored_status_literals_returns_empty_without_status_column() -> None:
    feed = change_feed()
    existing = change_dataframe([SAMPLE_FEATURE_ROW])
    assert (
        peri_scribe.changes.stored_status_literals(
            existing,
            feed,
            peri_scribe.models.FireStatus.INACTIVE,
        )
        == ()
    )


def test_stored_status_literals_distinct_in_first_seen_order() -> None:
    feed = change_feed()
    existing = status_dataframe([
        (1, "Inactive", (0.0, 0.0)),
        (2, "Active", (1.0, 1.0)),
        (3, "Inactive", (2.0, 2.0)),
        (4, "0", (3.0, 3.0)),
        (5, 0, (4.0, 4.0)),
        (6, False, (5.0, 5.0)),
        (7, "unknown-status", (6.0, 6.0)),
    ])
    assert peri_scribe.changes.stored_status_literals(
        existing,
        feed,
        peri_scribe.models.FireStatus.INACTIVE,
    ) == ("'Inactive'", "'0'", "0", "false")


def test_stored_status_literals_selects_active_values() -> None:
    feed = change_feed()
    existing = status_dataframe([
        (1, "Active", (0.0, 0.0)),
        (2, 1, (1.0, 1.0)),
    ])
    assert peri_scribe.changes.stored_status_literals(
        existing,
        feed,
        peri_scribe.models.FireStatus.ACTIVE,
    ) == ("'Active'", "1")


def test_incremental_cutoff_returns_epoch_without_existing() -> None:
    feed = change_feed()
    assert peri_scribe.changes.incremental_cutoff(
        None,
        feed,
    ) == datetime.datetime(1970, 1, 1, 0, 0, 0, tzinfo=UTC)


def test_incremental_cutoff_subtracts_overlap() -> None:
    feed = change_feed()
    existing = modified_dataframe([(1, "2026-01-01T00:10:00Z", (0.0, 0.0))])
    result = peri_scribe.changes.incremental_cutoff(existing, feed)
    assert result == datetime.datetime(2026, 1, 1, 0, 10, 0, tzinfo=UTC) - (
        peri_scribe.changes.OVERLAP
    )


def test_where_clause_for_formats_cutoff() -> None:
    cutoff = datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    result = peri_scribe.changes.where_clause_for("ModifiedOnDateTime_dt", cutoff)
    assert result == (
        "ModifiedOnDateTime_dt >= timestamp '2026-01-01T00:00:00Z' "
        "OR ModifiedOnDateTime_dt IS NULL"
    )


def test_where_clause_for_includes_null_modified_timestamps() -> None:
    cutoff = datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    result = peri_scribe.changes.where_clause_for("EditDate", cutoff)
    assert "EditDate IS NULL" in result


def test_normalized_attribute_value_returns_none_for_none() -> None:
    assert peri_scribe.changes.normalized_attribute_value(None) is None


def test_normalized_attribute_value_returns_none_for_nan() -> None:
    assert peri_scribe.changes.normalized_attribute_value(float("nan")) is None


def test_normalized_attribute_value_truncates_datetime() -> None:
    result = peri_scribe.changes.normalized_attribute_value(
        datetime.datetime(2026, 1, 1, 0, 0, 0, 123456),
    )
    assert result == datetime.datetime(2026, 1, 1, 0, 0, 0)


def test_normalized_attribute_value_passes_through_other_values() -> None:
    number = 7
    assert peri_scribe.changes.normalized_attribute_value("abc") == "abc"
    assert peri_scribe.changes.normalized_attribute_value(number) == number


def test_attribute_columns_excludes_geometry() -> None:
    new = change_dataframe([SAMPLE_FEATURE_ROW])
    existing = change_dataframe([SAMPLE_FEATURE_ROW])
    assert peri_scribe.changes.attribute_columns(new, existing) == [
        "OBJECTID",
        "name",
    ]


def test_features_are_identical_returns_true_for_matching_rows() -> None:
    geometry = shapely.geometry.Point(0, 0)
    values = {"OBJECTID": 1, "name": "a"}
    existing = {"OBJECTID": 1, "name": "a"}
    assert peri_scribe.changes.features_are_identical(
        values,
        geometry,
        existing,
        geometry,
        ["OBJECTID", "name"],
    )


def test_features_are_identical_returns_false_for_different_attributes() -> None:
    geometry = shapely.geometry.Point(0, 0)
    values = {"OBJECTID": 1, "name": "a"}
    existing = {"OBJECTID": 1, "name": "changed"}
    assert not peri_scribe.changes.features_are_identical(
        values,
        geometry,
        existing,
        geometry,
        ["OBJECTID", "name"],
    )


def test_features_are_identical_returns_false_for_different_geometry() -> None:
    values = {"OBJECTID": 1, "name": "a"}
    existing = {"OBJECTID": 1, "name": "a"}
    assert not peri_scribe.changes.features_are_identical(
        values,
        shapely.geometry.Point(0, 0),
        existing,
        shapely.geometry.Point(1, 1),
        ["OBJECTID", "name"],
    )


def test_features_are_identical_accepts_re_serialized_geometry() -> None:
    ring = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
    reversed_ring = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]
    values = {"OBJECTID": 1, "name": "a"}
    existing = {"OBJECTID": 1, "name": "a"}
    assert peri_scribe.changes.features_are_identical(
        values,
        shapely.geometry.Polygon(ring),
        existing,
        shapely.geometry.Polygon(reversed_ring),
        ["OBJECTID", "name"],
    )


def test_drop_features_already_present_returns_new_when_no_existing() -> None:
    new = change_dataframe([SAMPLE_FEATURE_ROW])
    result = peri_scribe.changes.drop_features_already_present(new, None)
    assert result is new


def test_drop_features_already_present_keeps_new_object_id() -> None:
    new = change_dataframe([(3, "c", (2.0, 2.0))])
    existing = change_dataframe([SAMPLE_FEATURE_ROW, (2, "b", (1.0, 1.0))])
    result = peri_scribe.changes.drop_features_already_present(new, existing)
    assert list(result["OBJECTID"]) == [3]


def test_drop_features_already_present_drops_identical_feature() -> None:
    new = change_dataframe([SAMPLE_FEATURE_ROW])
    existing = change_dataframe([SAMPLE_FEATURE_ROW])
    result = peri_scribe.changes.drop_features_already_present(new, existing)
    assert result.empty


def test_drop_features_already_present_keeps_changed_feature() -> None:
    new = change_dataframe([(1, "changed", (0.0, 0.0))])
    existing = change_dataframe([SAMPLE_FEATURE_ROW])
    result = peri_scribe.changes.drop_features_already_present(new, existing)
    assert list(result["name"]) == ["changed"]


def polygon_feature_dataframe(
    rows: list[tuple[int, str, list[tuple[float, float]]]],
) -> geopandas.GeoDataFrame:
    """Return a GeoDataFrame of polygon features for the given rows.

    Args:
        rows: The OBJECTID, name, and exterior ring of each feature.

    Returns:
        The GeoDataFrame.
    """
    return geopandas.GeoDataFrame(
        {
            "OBJECTID": [row[0] for row in rows],
            "name": [row[1] for row in rows],
        },
        geometry=[shapely.geometry.Polygon(row[2]) for row in rows],
        crs=pyproj.CRS.from_epsg(4326),
    )


def test_drop_features_already_present_drops_re_serialized_feature() -> None:
    ring = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
    reversed_ring = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]
    new = polygon_feature_dataframe([(1, "a", reversed_ring)])
    existing = polygon_feature_dataframe([(1, "a", ring)])
    result = peri_scribe.changes.drop_features_already_present(new, existing)
    assert result.empty


def test_drop_features_already_present_keeps_different_shape() -> None:
    ring = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
    different = [(0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
    new = polygon_feature_dataframe([(1, "a", different)])
    existing = polygon_feature_dataframe([(1, "a", ring)])
    result = peri_scribe.changes.drop_features_already_present(new, existing)
    assert list(result["OBJECTID"]) == [1]


def test_drop_features_already_present_handles_renamed_geometry_column() -> None:
    ring = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
    new = polygon_feature_dataframe([(1, "a", ring)]).rename_geometry("geom")
    assert new is not None
    existing = polygon_feature_dataframe([(1, "a", ring)])
    result = peri_scribe.changes.drop_features_already_present(new, existing)
    assert result.empty


def test_latest_snapshot_path_returns_none_without_files() -> None:
    assert peri_scribe.changes.latest_snapshot_path(pathlib.Path("/d"), []) is None


def test_latest_snapshot_path_returns_last_file() -> None:
    result = peri_scribe.changes.latest_snapshot_path(
        pathlib.Path("/d"),
        [
            peri_scribe.snapshots.SourceFile(serial_number=0, last_edit_timestamp=0),
            peri_scribe.snapshots.SourceFile(serial_number=1, last_edit_timestamp=0),
        ],
    )
    assert result == pathlib.Path("/d/000___/000001,lastEdit=0.gpkg")
