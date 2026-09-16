"""Tests for peri_scribe.sources.changes."""

from __future__ import annotations

import geopandas.testing
import hypothesis
import shapely.geometry

import peri_scribe.sources.changes
import tests.helpers.factories.peri_scribe.sources.changes
import tests.helpers.strategies.geometry
import tests.helpers.strategies.peri_scribe.sources.changes


# This test is slow, so limit examples to keep routine test runs fast.
@hypothesis.settings(max_examples=25)
@hypothesis.given(
    rows=tests.helpers.strategies.peri_scribe.sources.changes.feature_pairs(),
    rename_geometry=...,
)
def test_drop_features_already_present_matches_feature_dictionary(
    rows: tuple[
        list[tests.helpers.factories.peri_scribe.sources.changes.FeatureRow],
        list[tests.helpers.factories.peri_scribe.sources.changes.FeatureRow],
    ],
    *,
    rename_geometry: bool,
) -> None:
    existing_rows, fetched_rows = rows
    existing = tests.helpers.factories.peri_scribe.sources.changes.change_dataframe(
        existing_rows,
    )
    fetched = tests.helpers.factories.peri_scribe.sources.changes.change_dataframe(
        fetched_rows,
    )
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


@hypothesis.given(geometry=tests.helpers.strategies.geometry.polygons())
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
