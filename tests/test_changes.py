"""Tests for peri_scribe.changes."""

from __future__ import annotations

import datetime
import pathlib
import typing

import geopandas
import pyproj
import shapely.geometry

import peri_scribe.changes
import peri_scribe.snapshots
from tests.factories import change_dataframe, change_feed


if typing.TYPE_CHECKING:
    import pytest


UTC = datetime.UTC


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
        "existing_geopackage_filenames",
        lambda _directory: [],
    )
    assert (
        peri_scribe.changes.existing_features(pathlib.Path("/sources"), feed) is None
    )


def test_latest_modified_datetime_returns_none_without_existing() -> None:
    feed = change_feed()
    assert peri_scribe.changes.latest_modified_datetime(None, feed) is None


def test_latest_modified_datetime_returns_none_for_empty() -> None:
    feed = change_feed()
    empty = change_dataframe([])
    assert peri_scribe.changes.latest_modified_datetime(empty, feed) is None


def test_latest_modified_datetime_returns_none_without_modified_column() -> None:
    feed = change_feed()
    existing = change_dataframe([(1, "a", (0.0, 0.0))])
    assert peri_scribe.changes.latest_modified_datetime(existing, feed) is None


def test_latest_modified_datetime_returns_maximum() -> None:
    feed = change_feed()
    existing = geopandas.GeoDataFrame(
        {
            "OBJECTID": [1, 2],
            "ModifiedOnDateTime_dt": [
                "2026-01-01T00:00:00Z",
                "2026-02-01T00:00:00Z",
            ],
        },
        geometry=[
            shapely.geometry.Point(0.0, 0.0),
            shapely.geometry.Point(1.0, 1.0),
        ],
        crs=pyproj.CRS.from_epsg(4326),
    )
    result = peri_scribe.changes.latest_modified_datetime(existing, feed)
    assert result == datetime.datetime(2026, 2, 1, 0, 0, 0, tzinfo=UTC)


def test_incremental_cutoff_returns_epoch_without_existing() -> None:
    feed = change_feed()
    assert peri_scribe.changes.incremental_cutoff(
        None,
        feed,
    ) == datetime.datetime(1970, 1, 1, 0, 0, 0, tzinfo=UTC)


def test_incremental_cutoff_subtracts_overlap() -> None:
    feed = change_feed()
    existing = geopandas.GeoDataFrame(
        {
            "OBJECTID": [1],
            "ModifiedOnDateTime_dt": ["2026-01-01T00:10:00Z"],
        },
        geometry=[shapely.geometry.Point(0.0, 0.0)],
        crs=pyproj.CRS.from_epsg(4326),
    )
    result = peri_scribe.changes.incremental_cutoff(existing, feed)
    assert result == datetime.datetime(2026, 1, 1, 0, 10, 0, tzinfo=UTC) - (
        peri_scribe.changes.OVERLAP
    )


def test_where_clause_for_formats_cutoff() -> None:
    cutoff = datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    result = peri_scribe.changes.where_clause_for("ModifiedOnDateTime_dt", cutoff)
    assert result == "ModifiedOnDateTime_dt >= timestamp '2026-01-01T00:00:00Z'"


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
    new = change_dataframe([(1, "a", (0.0, 0.0))])
    existing = change_dataframe([(1, "a", (0.0, 0.0))])
    assert peri_scribe.changes.attribute_columns(new, existing) == [
        "OBJECTID",
        "name",
    ]


def test_feature_signatures_keys_by_object_id() -> None:
    dataframe = change_dataframe(
        [(1, "a", (0.0, 0.0)), (2, "b", (1.0, 1.0))],
    )
    signatures = peri_scribe.changes.feature_signatures(
        dataframe,
        ["OBJECTID", "name"],
    )
    assert set(signatures) == {1, 2}
    assert signatures[1][0] == (1, "a")
    assert signatures[1][1] == shapely.geometry.Point(0.0, 0.0).wkb


def test_drop_features_already_present_returns_new_when_no_existing() -> None:
    new = change_dataframe([(1, "a", (0.0, 0.0))])
    result = peri_scribe.changes.drop_features_already_present(new, None)
    assert result is new


def test_drop_features_already_present_keeps_new_object_id() -> None:
    new = change_dataframe([(3, "c", (2.0, 2.0))])
    existing = change_dataframe([(1, "a", (0.0, 0.0)), (2, "b", (1.0, 1.0))])
    result = peri_scribe.changes.drop_features_already_present(new, existing)
    assert list(result["OBJECTID"]) == [3]


def test_drop_features_already_present_drops_identical_feature() -> None:
    new = change_dataframe([(1, "a", (0.0, 0.0))])
    existing = change_dataframe([(1, "a", (0.0, 0.0))])
    result = peri_scribe.changes.drop_features_already_present(new, existing)
    assert result.empty


def test_drop_features_already_present_keeps_changed_feature() -> None:
    new = change_dataframe([(1, "changed", (0.0, 0.0))])
    existing = change_dataframe([(1, "a", (0.0, 0.0))])
    result = peri_scribe.changes.drop_features_already_present(new, existing)
    assert list(result["name"]) == ["changed"]


def test_latest_snapshot_path_returns_none_without_files() -> None:
    assert peri_scribe.changes.latest_snapshot_path(pathlib.Path("/d"), []) is None


def test_latest_snapshot_path_returns_last_file() -> None:
    result = peri_scribe.changes.latest_snapshot_path(
        pathlib.Path("/d"),
        [pathlib.Path("000000.gpkg"), pathlib.Path("000001.gpkg")],
    )
    assert result == pathlib.Path("/d/000001.gpkg")
