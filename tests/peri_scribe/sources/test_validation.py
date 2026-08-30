"""Tests for peri_scribe.sources.validation."""

from __future__ import annotations

import pathlib
import typing

import geopandas
import pyproj
import shapely.geometry

import peri_scribe.geo.reading
import peri_scribe.sources.feed_state
import peri_scribe.sources.feed_types
import peri_scribe.sources.validation
from tests.factories import change_dataframe, change_feed


if typing.TYPE_CHECKING:
    import pytest


def validation_feed(index: int) -> peri_scribe.sources.feed_types.ArcGISFeed:
    """Return a feed with a name unique to *index*.

    Args:
        index: The number that distinguishes the feed's name.

    Returns:
        The feed.
    """
    return peri_scribe.sources.feed_types.ArcGISFeed(
        url=(f"https://example.test/ArcGIS/rest/services/Fires{index}/FeatureServer/0"),
        fire_name_column="name",
        status_column="status",
    )


def frame_without_object_id() -> geopandas.GeoDataFrame:
    """Return a GeoDataFrame with one point feature and no OBJECTID column.

    Returns:
        The GeoDataFrame.
    """
    return geopandas.GeoDataFrame(
        {"name": ["a"]},
        geometry=[shapely.geometry.Point(0.0, 0.0)],
        crs=pyproj.CRS.from_epsg(4326),
    )


def test_validate_feed_clean_when_stored_covers_complete() -> None:
    complete = change_dataframe([(1, "a", (0.0, 0.0)), (2, "b", (1.0, 1.0))])
    result = peri_scribe.sources.validation.validate_feed(
        change_feed(),
        complete,
        complete,
    )
    assert not result.has_problems
    assert result.feed_name == "Fires_0"
    assert result.complete_feature_count == len(complete)
    assert result.missing_object_ids == frozenset()
    assert result.mismatched_object_ids == frozenset()
    assert result.columns_missing_from_stored == frozenset()


def test_validate_feed_reports_missing_features() -> None:
    complete = change_dataframe([(1, "a", (0.0, 0.0)), (2, "b", (1.0, 1.0))])
    stored = change_dataframe([(1, "a", (0.0, 0.0))])
    result = peri_scribe.sources.validation.validate_feed(
        change_feed(),
        complete,
        stored,
    )
    assert result.has_problems
    assert result.missing_object_ids == frozenset({2})
    assert result.mismatched_object_ids == frozenset()


def test_validate_feed_reports_mismatched_attribute_values() -> None:
    complete = change_dataframe([(1, "a", (0.0, 0.0))])
    stored = change_dataframe([(1, "b", (0.0, 0.0))])
    result = peri_scribe.sources.validation.validate_feed(
        change_feed(),
        complete,
        stored,
    )
    assert result.has_problems
    assert result.missing_object_ids == frozenset()
    assert result.mismatched_object_ids == frozenset({1})


def test_validate_feed_reports_mismatched_geometry() -> None:
    complete = change_dataframe([(1, "a", (0.0, 0.0))])
    stored = change_dataframe([(1, "a", (5.0, 5.0))])
    result = peri_scribe.sources.validation.validate_feed(
        change_feed(),
        complete,
        stored,
    )
    assert result.has_problems
    assert result.missing_object_ids == frozenset()
    assert result.mismatched_object_ids == frozenset({1})


def test_validate_feed_ignores_geometry_type_wrapper_differences() -> None:
    ring = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]
    complete = geopandas.GeoDataFrame(
        {"OBJECTID": [1], "name": ["a"]},
        geometry=[shapely.geometry.MultiPolygon([shapely.geometry.Polygon(ring)])],
        crs=pyproj.CRS.from_epsg(4326),
    )
    stored = geopandas.GeoDataFrame(
        {"OBJECTID": [1], "name": ["a"]},
        geometry=[shapely.geometry.Polygon(ring)],
        crs=pyproj.CRS.from_epsg(4326),
    )
    result = peri_scribe.sources.validation.validate_feed(
        change_feed(),
        complete,
        stored,
    )
    assert not result.has_problems


def test_validate_feed_still_reports_split_geometry() -> None:
    ring = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]
    complete = geopandas.GeoDataFrame(
        {"OBJECTID": [1], "name": ["a"]},
        geometry=[
            shapely.geometry.MultiPolygon(
                [
                    shapely.geometry.Polygon(ring),
                    shapely.geometry.Polygon(
                        [(5.0, 5.0), (5.0, 6.0), (6.0, 6.0), (6.0, 5.0), (5.0, 5.0)],
                    ),
                ],
            ),
        ],
        crs=pyproj.CRS.from_epsg(4326),
    )
    stored = geopandas.GeoDataFrame(
        {"OBJECTID": [1], "name": ["a"]},
        geometry=[shapely.geometry.Polygon(ring)],
        crs=pyproj.CRS.from_epsg(4326),
    )
    result = peri_scribe.sources.validation.validate_feed(
        change_feed(),
        complete,
        stored,
    )
    assert result.has_problems
    assert result.mismatched_object_ids == frozenset({1})


def test_validate_feed_matches_missing_geometries() -> None:
    complete = geopandas.GeoDataFrame(
        {"OBJECTID": [1], "name": ["a"]},
        geometry=[None],
        crs=pyproj.CRS.from_epsg(4326),
    )
    stored = geopandas.GeoDataFrame(
        {"OBJECTID": [1], "name": ["a"]},
        geometry=[None],
        crs=pyproj.CRS.from_epsg(4326),
    )
    result = peri_scribe.sources.validation.validate_feed(
        change_feed(),
        complete,
        stored,
    )
    assert not result.has_problems


def test_validate_feed_reports_mismatched_missing_geometry() -> None:
    complete = geopandas.GeoDataFrame(
        {"OBJECTID": [1], "name": ["a"]},
        geometry=[None],
        crs=pyproj.CRS.from_epsg(4326),
    )
    stored = change_dataframe([(1, "a", (0.0, 0.0))])
    result = peri_scribe.sources.validation.validate_feed(
        change_feed(),
        complete,
        stored,
    )
    assert result.has_problems
    assert result.mismatched_object_ids == frozenset({1})


def test_validate_feed_reports_columns_missing_from_stored() -> None:
    complete = geopandas.GeoDataFrame(
        {"OBJECTID": [1], "name": ["a"], "size": [4.0]},
        geometry=[shapely.geometry.Point(0.0, 0.0)],
        crs=pyproj.CRS.from_epsg(4326),
    )
    stored = change_dataframe([(1, "a", (0.0, 0.0))])
    result = peri_scribe.sources.validation.validate_feed(
        change_feed(),
        complete,
        stored,
    )
    assert result.has_problems
    assert result.missing_object_ids == frozenset()
    assert result.mismatched_object_ids == frozenset()
    assert result.columns_missing_from_stored == frozenset({"size"})


def test_validate_feed_reports_everything_missing_without_stored_data() -> None:
    complete = change_dataframe([(1, "a", (0.0, 0.0)), (2, "b", (1.0, 1.0))])
    result = peri_scribe.sources.validation.validate_feed(
        change_feed(),
        complete,
        None,
    )
    assert result.has_problems
    assert result.missing_object_ids == frozenset({1, 2})
    assert result.mismatched_object_ids == frozenset()
    assert result.columns_missing_from_stored == frozenset({"name"})


def test_validate_feed_treats_stored_frame_without_object_id_as_missing() -> None:
    complete = change_dataframe([(1, "a", (0.0, 0.0))])
    result = peri_scribe.sources.validation.validate_feed(
        change_feed(),
        complete,
        frame_without_object_id(),
    )
    assert result.has_problems
    assert result.missing_object_ids == frozenset({1})
    assert result.columns_missing_from_stored == frozenset({"name"})


def test_validate_feed_ignores_extra_stored_features_and_columns() -> None:
    complete = change_dataframe([(1, "a", (0.0, 0.0))])
    stored = geopandas.GeoDataFrame(
        {"OBJECTID": [1, 3], "name": ["a", "c"], "old": ["x", "y"]},
        geometry=[
            shapely.geometry.Point(0.0, 0.0),
            shapely.geometry.Point(2.0, 2.0),
        ],
        crs=pyproj.CRS.from_epsg(4326),
    )
    result = peri_scribe.sources.validation.validate_feed(
        change_feed(),
        complete,
        stored,
    )
    assert not result.has_problems
    assert result.missing_object_ids == frozenset()
    assert result.mismatched_object_ids == frozenset()
    assert result.columns_missing_from_stored == frozenset()


def test_validate_complete_sources_validates_each_feed_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    year_directory = pathlib.Path("/base/data/2026")
    feeds = [validation_feed(0), validation_feed(1)]
    complete_frames = {
        "Fires0_0": change_dataframe([(1, "a", (0.0, 0.0))]),
        "Fires1_0": change_dataframe([(2, "b", (1.0, 1.0))]),
    }
    stored_frames = {
        "Fires0_0": change_dataframe([(1, "a", (0.0, 0.0))]),
        "Fires1_0": change_dataframe([(2, "different", (1.0, 1.0))]),
    }
    read_calls: list[tuple[pathlib.Path, peri_scribe.sources.feed_types.Feed]] = []

    def read_layer_dataframe(
        path: pathlib.Path,
        feed: peri_scribe.sources.feed_types.Feed,
    ) -> geopandas.GeoDataFrame:
        read_calls.append((path, feed))
        return complete_frames[feed.name]

    def existing_features(
        directory: pathlib.Path,
        feed: peri_scribe.sources.feed_types.Feed,
    ) -> geopandas.GeoDataFrame:
        assert directory == year_directory / "sources" / feed.name
        return stored_frames[feed.name]

    monkeypatch.setattr(
        peri_scribe.geo.reading,
        "read_layer_dataframe",
        read_layer_dataframe,
    )
    monkeypatch.setattr(
        peri_scribe.sources.feed_state,
        "existing_features",
        existing_features,
    )
    results = peri_scribe.sources.validation.validate_complete_sources(
        year_directory,
        feeds,
    )
    assert [result.feed_name for result in results] == ["Fires0_0", "Fires1_0"]
    assert [result.has_problems for result in results] == [False, True]
    assert read_calls == [
        (
            year_directory / "validation" / "Fires0_0.gpkg",
            feeds[0],
        ),
        (
            year_directory / "validation" / "Fires1_0.gpkg",
            feeds[1],
        ),
    ]
