"""Tests for peri_scribe.fetching."""

from __future__ import annotations

import pathlib

import geopandas
import pandas as pd
import pyproj
import pytest

import peri_scribe.changes
import peri_scribe.fetching
import peri_scribe.geo_data
import peri_scribe.snapshots
from tests.factories import change_feed


def test_fetch_feed_dataframe_raises_without_modified_column() -> None:
    feed = change_feed(modified_column=None)
    with pytest.raises(ValueError, match="no modified column"):
        peri_scribe.fetching.fetch_feed_dataframe(
            feed,
            object(),  # ty: ignore
            [peri_scribe.snapshots.SourceFile(serial_number=0, last_edit_timestamp=0)],
            pathlib.Path("/sources"),
        )


def test_fetch_feed_dataframe_returns_none_without_changed_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = change_feed()
    monkeypatch.setattr(
        peri_scribe.changes,
        "existing_features",
        lambda _directory, _feed: None,
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "query_object_ids_with_retry",
        lambda *_arguments, **_keywords: [],
    )
    result = peri_scribe.fetching.fetch_feed_dataframe(
        feed,
        object(),  # ty: ignore
        [peri_scribe.snapshots.SourceFile(serial_number=0, last_edit_timestamp=0)],
        pathlib.Path("/sources"),
    )
    assert result is None


def test_fetch_feed_dataframe_returns_none_when_dedupe_removes_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = change_feed()
    monkeypatch.setattr(
        peri_scribe.changes,
        "existing_features",
        lambda _directory, _feed: None,
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "query_object_ids_with_retry",
        lambda *_arguments, **_keywords: [1],
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "query_with_retry",
        lambda *_arguments, **_keywords: "feature_set",
    )
    empty = geopandas.GeoDataFrame(
        {"OBJECTID": pd.Series([], dtype="int64"), "name": []},
        geometry=[],
        crs=pyproj.CRS.from_epsg(4326),
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "dataframe_for_layer",
        lambda *_arguments, **_keywords: empty,
    )
    result = peri_scribe.fetching.fetch_feed_dataframe(
        feed,
        object(),  # ty: ignore
        [peri_scribe.snapshots.SourceFile(serial_number=0, last_edit_timestamp=0)],
        pathlib.Path("/sources"),
    )
    assert result is None


def test_fetch_feed_dataframe_fetches_full_when_directory_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = change_feed()
    sentinel = object()
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "query_with_retry",
        lambda *_arguments, **_keywords: "feature_set",
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "dataframe_for_layer",
        lambda *_arguments, **_keywords: sentinel,
    )
    result = peri_scribe.fetching.fetch_feed_dataframe(
        feed,
        object(),  # ty: ignore
        [],
        pathlib.Path("/sources"),
    )
    assert result is sentinel
