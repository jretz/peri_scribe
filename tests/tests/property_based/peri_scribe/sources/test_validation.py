"""Tests for peri_scribe.sources.validation."""

from __future__ import annotations

import typing

import hypothesis

import peri_scribe.sources.validation
import tests.helpers.factories.peri_scribe.sources.changes
import tests.helpers.factories.peri_scribe.sources.validation
import tests.helpers.strategies.peri_scribe.sources.changes


if typing.TYPE_CHECKING:
    import geopandas


@hypothesis.given(
    rows=tests.helpers.strategies.peri_scribe.sources.changes.feature_pairs(),
    omit_name=...,
)
def test_validate_feed_matches_feature_and_schema_differences(
    rows: tuple[
        list[tests.helpers.factories.peri_scribe.sources.changes.FeatureRow],
        list[tests.helpers.factories.peri_scribe.sources.changes.FeatureRow],
    ],
    *,
    omit_name: bool,
) -> None:
    stored_rows, complete_rows = rows
    stored = tests.helpers.factories.peri_scribe.sources.changes.change_dataframe(
        stored_rows,
    )
    complete = tests.helpers.factories.peri_scribe.sources.changes.change_dataframe(
        complete_rows,
    )
    if omit_name:
        stored = typing.cast("geopandas.GeoDataFrame", stored.drop(columns="name"))
    stored_by_id = {row[0]: row for row in stored_rows}
    missing = frozenset(row[0] for row in complete_rows if row[0] not in stored_by_id)
    mismatched = frozenset(
        identifier
        for identifier, name, coordinates in complete_rows
        if identifier in stored_by_id
        and (
            stored_by_id[identifier][2] != coordinates
            or (not omit_name and stored_by_id[identifier][1] != name)
        )
    )
    feed = tests.helpers.factories.peri_scribe.sources.validation.validation_feed(0)
    assert peri_scribe.sources.validation.validate_feed(feed, complete, stored) == (
        peri_scribe.sources.validation.FeedValidationResult(
            feed_name=feed.name,
            complete_feature_count=len(complete_rows),
            missing_object_ids=missing,
            mismatched_object_ids=mismatched,
            columns_missing_from_stored=frozenset({"name"})
            if omit_name
            else frozenset(),
        )
    )
