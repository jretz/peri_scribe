"""Tests for peri_scribe.sources.fetching."""

from __future__ import annotations

import contextlib
import datetime
import pathlib
import sqlite3
import typing

import hypothesis
import pytest
import shapely.geometry

import peri_scribe.sources.changes
import peri_scribe.sources.feed_state
import peri_scribe.sources.fetching
import peri_scribe.sources.snapshots
import tests.helpers.doubles.peri_scribe.sources.fetching
import tests.helpers.factories.peri_scribe.sources.feed_types
import tests.helpers.factories.peri_scribe.sources.fetching
import tests.helpers.strategies.peri_scribe.sources.fetching


if typing.TYPE_CHECKING:
    import arcgis.features


# This test is slow, so limit examples to keep routine test runs fast.
@hypothesis.settings(max_examples=25)
@hypothesis.given(
    scenario=tests.helpers.strategies.peri_scribe.sources.fetching.fetch_scenarios(),
    full=hypothesis.infer,
)
def test_fetch_feed_dataframe_matches_independent_change_selection(
    scenario: tuple[
        dict[int, tests.helpers.factories.peri_scribe.sources.fetching.FetchFeature],
        dict[int, tests.helpers.factories.peri_scribe.sources.fetching.FetchFeature],
    ],
    *,
    full: bool,
) -> None:
    stored, current = scenario
    expected = {
        identifier: feature
        for identifier, feature in current.items()
        if feature != stored.get(identifier)
        and (
            full
            or identifier not in stored
            or feature.modified_minute is None
            or datetime.timedelta(minutes=feature.modified_minute)
            >= -peri_scribe.sources.changes.OVERLAP
            or (stored[identifier].active and not feature.active)
        )
    }
    stored_frame = tests.helpers.factories.peri_scribe.sources.fetching.fetch_frame(
        stored,
    )
    with (
        contextlib.closing(sqlite3.connect(":memory:")) as database,
        pytest.MonkeyPatch.context() as patch,
    ):
        layer = (
            tests.helpers.doubles.peri_scribe.sources.fetching.QueryableFeatureLayer(
                database,
                current,
            )
        )
        patch.setattr(
            peri_scribe.sources.feed_state,
            "read_current_features",
            lambda _directory, _feed: stored_frame,
        )
        actual = peri_scribe.sources.fetching.fetch_feed_dataframe(
            tests.helpers.factories.peri_scribe.sources.feed_types.change_feed(),
            typing.cast("arcgis.features.FeatureLayer", layer),
            [
                peri_scribe.sources.snapshots.SourceFile(
                    serial_number=0,
                    last_edit_timestamp=0,
                ),
            ],
            pathlib.Path("/unused-source-directory"),
            full=full,
        )
    if not expected:
        assert actual is None
        return
    assert actual is not None
    assert len(actual) == len(expected)
    assert set(actual.OBJECTID) == set(expected)
    for _, row in actual.iterrows():
        feature = expected[row.OBJECTID]
        assert row["name"] == feature.name
        assert row["status"] == ("Active" if feature.active else "Inactive")
        assert row[actual.geometry.name] == shapely.geometry.Point(feature.longitude, 0)
