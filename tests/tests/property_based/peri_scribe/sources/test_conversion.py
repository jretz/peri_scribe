"""Tests for peri_scribe.sources.external_sources."""

from __future__ import annotations

import json
import pathlib
import tempfile

import geopandas
import geopandas.testing
import hypothesis
import hypothesis.strategies
import pandas as pd

import peri_scribe.models
import peri_scribe.sources.conversion
import tests.helpers.factories.geography
import tests.helpers.peri_scribe.sources.conversion
import tests.helpers.strategies.geometry
import tests.helpers.strategies.peri_scribe.sources.conversion


# This test is slow, so limit examples to keep routine test runs fast.
@hypothesis.settings(max_examples=25)
@hypothesis.given(
    features=tests.helpers.strategies.peri_scribe.sources.conversion.feature_collections(),
    chunk_size=hypothesis.strategies.integers(1, 10),
)
def test_geojson_feature_chunks_preserves_features_across_chunk_boundaries(
    features: list[dict[str, object]],
    chunk_size: int,
) -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        path = pathlib.Path(temporary_directory) / "features.geojson"
        path.write_text(
            json.dumps({"type": "FeatureCollection", "features": features}),
            encoding="utf-8",
        )
        chunks = list(
            peri_scribe.sources.conversion.geojson_feature_chunks(path, chunk_size),
        )
    assert all(0 < len(chunk) <= chunk_size for chunk in chunks)
    assert sum(len(chunk) for chunk in chunks) == len(features)
    if features:
        expected = geopandas.GeoDataFrame.from_features(
            features,
            crs=peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID,
        )
        actual = pd.concat(chunks, ignore_index=True)
        assert isinstance(actual, geopandas.GeoDataFrame)
        pd.testing.assert_frame_equal(
            tests.helpers.peri_scribe.sources.conversion.comparable_attributes(actual),
            tests.helpers.peri_scribe.sources.conversion.comparable_attributes(
                expected,
            ),
            check_like=True,
        )
        geopandas.testing.assert_geoseries_equal(actual.geometry, expected.geometry)


@hypothesis.given(
    geometry=tests.helpers.strategies.geometry.footprints(),
    projected=...,
)
def test_centroid_dataframe_preserves_its_input(
    geometry: tests.helpers.strategies.geometry.Footprint,
    *,
    projected: bool,
) -> None:
    frame = tests.helpers.factories.geography.geo_frame({"name": ["River"]}, [geometry])
    if projected:
        frame = frame.to_crs(3857)
    original = frame.copy(deep=True)
    peri_scribe.sources.conversion.centroid_dataframe(frame)
    geopandas.testing.assert_geodataframe_equal(frame, original)
