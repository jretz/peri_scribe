"""Tests for peri_scribe.sources.changes."""

from __future__ import annotations

import datetime

import geopandas.testing
import hypothesis
import shapely.geometry

import peri_scribe.sources.changes
import tests.factories
import tests.geometry_strategies
import tests.peri_scribe.sources.changes_helpers


def test_parse_iso_datetime_returns_datetime() -> None:
    assert peri_scribe.sources.changes.parse_iso_datetime(
        "2026-01-01T00:00:00",
    ) == datetime.datetime(2026, 1, 1, 0, 0, 0)


def test_parse_iso_datetime_returns_none_for_invalid() -> None:
    assert peri_scribe.sources.changes.parse_iso_datetime("not-a-date") is None


def test_modified_datetime_from_returns_none_for_none() -> None:
    assert peri_scribe.sources.changes.modified_datetime_from(None) is None


def test_modified_datetime_from_returns_none_for_nan() -> None:
    assert peri_scribe.sources.changes.modified_datetime_from(float("nan")) is None


def test_modified_datetime_from_returns_none_for_bool() -> None:
    assert peri_scribe.sources.changes.modified_datetime_from(value=True) is None


def test_modified_datetime_from_returns_none_for_unknown() -> None:
    assert peri_scribe.sources.changes.modified_datetime_from(object()) is None


def test_modified_datetime_from_makes_naive_datetime_utc_aware() -> None:
    result = peri_scribe.sources.changes.modified_datetime_from(
        datetime.datetime(2026, 1, 1, 0, 0, 0),
    )
    assert result == datetime.datetime(
        2026,
        1,
        1,
        0,
        0,
        0,
        tzinfo=tests.peri_scribe.sources.changes_helpers.UTC,
    )


def test_modified_datetime_from_converts_aware_datetime_to_utc() -> None:
    aware = datetime.datetime(
        2026,
        1,
        1,
        12,
        0,
        tzinfo=datetime.timezone(datetime.timedelta(hours=2)),
    )
    result = peri_scribe.sources.changes.modified_datetime_from(aware)
    assert result == datetime.datetime(
        2026,
        1,
        1,
        10,
        0,
        0,
        tzinfo=tests.peri_scribe.sources.changes_helpers.UTC,
    )


def test_modified_datetime_from_parses_iso_string() -> None:
    result = peri_scribe.sources.changes.modified_datetime_from("2026-01-01T00:00:00Z")
    assert result == datetime.datetime(
        2026,
        1,
        1,
        0,
        0,
        0,
        tzinfo=tests.peri_scribe.sources.changes_helpers.UTC,
    )


def test_modified_datetime_from_returns_none_for_invalid_string() -> None:
    assert peri_scribe.sources.changes.modified_datetime_from("nope") is None


def test_modified_datetime_from_parses_epoch_milliseconds() -> None:
    result = peri_scribe.sources.changes.modified_datetime_from(0)
    assert result == datetime.datetime(
        1970,
        1,
        1,
        0,
        0,
        0,
        tzinfo=tests.peri_scribe.sources.changes_helpers.UTC,
    )


def test_latest_modified_datetime_returns_none_without_existing() -> None:
    feed = tests.factories.change_feed()
    assert peri_scribe.sources.changes.latest_modified_datetime(None, feed) is None


def test_latest_modified_datetime_returns_none_for_empty() -> None:
    feed = tests.factories.change_feed()
    empty = tests.factories.change_dataframe([])
    assert peri_scribe.sources.changes.latest_modified_datetime(empty, feed) is None


def test_latest_modified_datetime_returns_none_without_change_columns() -> None:
    feed = tests.factories.change_feed(change_columns=())
    existing = tests.factories.change_dataframe([
        tests.peri_scribe.sources.changes_helpers.SAMPLE_FEATURE_ROW,
    ])
    assert peri_scribe.sources.changes.latest_modified_datetime(existing, feed) is None


def test_latest_modified_datetime_returns_maximum() -> None:
    feed = tests.factories.change_feed()
    existing = tests.peri_scribe.sources.changes_helpers.modified_dataframe([
        (1, "2026-01-01T00:00:00Z", (0.0, 0.0)),
        (2, "2026-02-01T00:00:00Z", (1.0, 1.0)),
    ])
    result = peri_scribe.sources.changes.latest_modified_datetime(existing, feed)
    assert result == datetime.datetime(
        2026,
        2,
        1,
        0,
        0,
        0,
        tzinfo=tests.peri_scribe.sources.changes_helpers.UTC,
    )


def test_latest_modified_datetime_returns_maximum_across_change_columns() -> None:
    feed = tests.factories.change_feed(
        change_columns=("ModifiedOnDateTime_dt", "poly_DateCurrent"),
    )
    existing = tests.peri_scribe.sources.changes_helpers.modified_dataframe([
        (1, "2026-01-01T00:00:00Z", (0.0, 0.0)),
        (2, "2026-02-01T00:00:00Z", (1.0, 1.0)),
    ])
    existing["poly_DateCurrent"] = ["2026-03-01T00:00:00Z", "2026-01-15T00:00:00Z"]
    result = peri_scribe.sources.changes.latest_modified_datetime(existing, feed)
    assert result == datetime.datetime(
        2026,
        3,
        1,
        0,
        0,
        0,
        tzinfo=tests.peri_scribe.sources.changes_helpers.UTC,
    )


def test_latest_modified_datetime_returns_none_when_no_values_parse() -> None:
    feed = tests.factories.change_feed()
    existing = tests.peri_scribe.sources.changes_helpers.modified_dataframe([
        (1, "nope", (0.0, 0.0)),
        (2, "also-nope", (1.0, 1.0)),
    ])
    assert peri_scribe.sources.changes.latest_modified_datetime(existing, feed) is None


def test_incremental_cutoff_returns_epoch_without_existing() -> None:
    feed = tests.factories.change_feed()
    assert peri_scribe.sources.changes.incremental_cutoff(
        None,
        feed,
    ) == datetime.datetime(
        1970,
        1,
        1,
        0,
        0,
        0,
        tzinfo=tests.peri_scribe.sources.changes_helpers.UTC,
    )


def test_incremental_cutoff_subtracts_overlap() -> None:
    feed = tests.factories.change_feed()
    existing = tests.peri_scribe.sources.changes_helpers.modified_dataframe([
        (1, "2026-01-01T00:10:00Z", (0.0, 0.0)),
    ])
    result = peri_scribe.sources.changes.incremental_cutoff(existing, feed)
    assert result == datetime.datetime(
        2026,
        1,
        1,
        0,
        10,
        0,
        tzinfo=tests.peri_scribe.sources.changes_helpers.UTC,
    ) - (peri_scribe.sources.changes.OVERLAP)


def test_normalized_attribute_value_returns_none_for_none() -> None:
    assert peri_scribe.sources.changes.normalized_attribute_value(None) is None


def test_normalized_attribute_value_returns_none_for_nan() -> None:
    assert peri_scribe.sources.changes.normalized_attribute_value(float("nan")) is None


def test_normalized_attribute_value_truncates_datetime() -> None:
    result = peri_scribe.sources.changes.normalized_attribute_value(
        datetime.datetime(2026, 1, 1, 0, 0, 0, 123456),
    )
    assert result == datetime.datetime(2026, 1, 1, 0, 0, 0)


def test_normalized_attribute_value_passes_through_other_values() -> None:
    number = 7
    assert peri_scribe.sources.changes.normalized_attribute_value("abc") == "abc"
    assert peri_scribe.sources.changes.normalized_attribute_value(number) == number


def test_attribute_columns_excludes_geometry() -> None:
    new = tests.factories.change_dataframe([
        tests.peri_scribe.sources.changes_helpers.SAMPLE_FEATURE_ROW,
    ])
    existing = tests.factories.change_dataframe([
        tests.peri_scribe.sources.changes_helpers.SAMPLE_FEATURE_ROW,
    ])
    assert peri_scribe.sources.changes.attribute_columns(new, existing) == [
        "OBJECTID",
        "name",
    ]


def test_features_are_identical_returns_true_for_matching_rows() -> None:
    geometry = shapely.geometry.Point(0, 0)
    values = {"OBJECTID": 1, "name": "a"}
    existing = {"OBJECTID": 1, "name": "a"}
    assert peri_scribe.sources.changes.features_are_identical(
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
    assert not peri_scribe.sources.changes.features_are_identical(
        values,
        geometry,
        existing,
        geometry,
        ["OBJECTID", "name"],
    )


def test_features_are_identical_returns_false_for_different_geometry() -> None:
    values = {"OBJECTID": 1, "name": "a"}
    existing = {"OBJECTID": 1, "name": "a"}
    assert not peri_scribe.sources.changes.features_are_identical(
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
    assert peri_scribe.sources.changes.features_are_identical(
        values,
        shapely.geometry.Polygon(ring),
        existing,
        shapely.geometry.Polygon(reversed_ring),
        ["OBJECTID", "name"],
    )


def test_drop_features_already_present_returns_new_when_no_existing() -> None:
    new = tests.factories.change_dataframe([
        tests.peri_scribe.sources.changes_helpers.SAMPLE_FEATURE_ROW,
    ])
    result = peri_scribe.sources.changes.drop_features_already_present(new, None)
    assert result is new


def test_drop_features_already_present_keeps_new_object_id() -> None:
    new = tests.factories.change_dataframe([(3, "c", (2.0, 2.0))])
    existing = tests.factories.change_dataframe([
        tests.peri_scribe.sources.changes_helpers.SAMPLE_FEATURE_ROW,
        (2, "b", (1.0, 1.0)),
    ])
    result = peri_scribe.sources.changes.drop_features_already_present(new, existing)
    assert list(result["OBJECTID"]) == [3]


def test_drop_features_already_present_drops_identical_feature() -> None:
    new = tests.factories.change_dataframe([
        tests.peri_scribe.sources.changes_helpers.SAMPLE_FEATURE_ROW,
    ])
    existing = tests.factories.change_dataframe([
        tests.peri_scribe.sources.changes_helpers.SAMPLE_FEATURE_ROW,
    ])
    result = peri_scribe.sources.changes.drop_features_already_present(new, existing)
    assert result.empty


def test_drop_features_already_present_preserves_empty_fetched_schema() -> None:
    fetched = tests.factories.change_dataframe([])
    existing = tests.factories.change_dataframe([(0, "", (0.0, 0.0))])
    result = peri_scribe.sources.changes.drop_features_already_present(
        fetched,
        existing,
    )
    geopandas.testing.assert_geodataframe_equal(result, fetched)


# This test is slow, so limit examples to keep routine test runs fast.
@hypothesis.settings(max_examples=25)
@hypothesis.given(
    rows=tests.peri_scribe.sources.changes_helpers.feature_pairs(),
    rename_geometry=...,
)
def test_drop_features_already_present_matches_feature_dictionary(
    rows: tuple[
        list[tests.peri_scribe.sources.changes_helpers.FeatureRow],
        list[tests.peri_scribe.sources.changes_helpers.FeatureRow],
    ],
    *,
    rename_geometry: bool,
) -> None:
    existing_rows, fetched_rows = rows
    existing = tests.factories.change_dataframe(existing_rows)
    fetched = tests.factories.change_dataframe(fetched_rows)
    if rename_geometry:
        fetched = fetched.rename_geometry("geom")
        assert fetched is not None
    stored = {row[0]: row for row in existing_rows}
    expected_positions = [
        position
        for position, row in enumerate(fetched_rows)
        if stored.get(row[0]) != row
    ]
    expected = fetched.iloc[expected_positions].reset_index(drop=True)
    actual = peri_scribe.sources.changes.drop_features_already_present(
        fetched,
        existing,
    )
    geopandas.testing.assert_geodataframe_equal(actual, expected)


@hypothesis.given(geometry=tests.geometry_strategies.polygons())
def test_features_are_identical_accepts_equivalent_polygon_representations(
    geometry: shapely.Polygon,
) -> None:
    republished = shapely.MultiPolygon([shapely.reverse(geometry)])
    values = {"OBJECTID": 1, "name": "River"}
    assert peri_scribe.sources.changes.features_are_identical(
        values,
        geometry,
        values,
        republished,
        list(values),
    )


def test_drop_features_already_present_keeps_changed_feature() -> None:
    new = tests.factories.change_dataframe([(1, "changed", (0.0, 0.0))])
    existing = tests.factories.change_dataframe([
        tests.peri_scribe.sources.changes_helpers.SAMPLE_FEATURE_ROW,
    ])
    result = peri_scribe.sources.changes.drop_features_already_present(new, existing)
    assert list(result["name"]) == ["changed"]


def test_drop_features_already_present_drops_re_serialized_feature() -> None:
    ring = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
    reversed_ring = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]
    new = tests.peri_scribe.sources.changes_helpers.polygon_feature_dataframe([
        (1, "a", reversed_ring),
    ])
    existing = tests.peri_scribe.sources.changes_helpers.polygon_feature_dataframe([
        (1, "a", ring),
    ])
    result = peri_scribe.sources.changes.drop_features_already_present(new, existing)
    assert result.empty


def test_drop_features_already_present_keeps_different_shape() -> None:
    ring = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
    different = [(0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
    new = tests.peri_scribe.sources.changes_helpers.polygon_feature_dataframe([
        (1, "a", different),
    ])
    existing = tests.peri_scribe.sources.changes_helpers.polygon_feature_dataframe([
        (1, "a", ring),
    ])
    result = peri_scribe.sources.changes.drop_features_already_present(new, existing)
    assert list(result["OBJECTID"]) == [1]


def test_drop_features_already_present_handles_renamed_geometry_column() -> None:
    ring = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
    new = tests.peri_scribe.sources.changes_helpers.polygon_feature_dataframe([
        (1, "a", ring),
    ]).rename_geometry("geom")
    assert new is not None
    existing = tests.peri_scribe.sources.changes_helpers.polygon_feature_dataframe([
        (1, "a", ring),
    ])
    result = peri_scribe.sources.changes.drop_features_already_present(new, existing)
    assert result.empty
