"""Tests for peri_scribe.geo.package."""

from __future__ import annotations

import pathlib
import tempfile

import geopandas
import geopandas.testing
import hypothesis
import hypothesis.strategies
import pandas as pd

import peri_scribe.geo.reading
import tests.helpers.factories.peri_scribe.geo.reading


# This test is slow, so limit examples to keep routine test runs fast.
@hypothesis.settings(max_examples=25, deadline=400)
@hypothesis.given(
    identifiers=hypothesis.strategies.lists(
        hypothesis.strategies.integers(1, 1000),
        unique=True,
        max_size=20,
    ),
    chunk_size=hypothesis.strategies.integers(1, 7),
)
def test_read_layer_chunks_preserves_sparse_features_in_bounded_chunks(
    identifiers: list[int],
    chunk_size: int,
) -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        path = pathlib.Path(temporary_directory) / "layer.gpkg"
        tests.helpers.factories.peri_scribe.geo.reading.write_sparse_layer(
            path,
            identifiers,
        )
        expected = geopandas.read_file(path, layer="features")
        chunks = list(
            peri_scribe.geo.reading.read_layer_chunks(path, "features", chunk_size),
        )
    assert all(0 < len(chunk) <= chunk_size for chunk in chunks)
    assert sum(map(len, chunks)) == len(identifiers)
    if chunks:
        actual = pd.concat(chunks, ignore_index=True)
        geopandas.testing.assert_geodataframe_equal(actual, expected)
