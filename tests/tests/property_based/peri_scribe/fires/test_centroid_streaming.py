"""ZIP transport chunk boundaries must not alter converted geography."""

import json

import hypothesis
import hypothesis.strategies
import numpy as np

import peri_scribe.fires.centroid_streaming
import tests.helpers.factories.peri_scribe.fires.centroid_streaming


@hypothesis.given(chunk_size=hypothesis.strategies.integers(1, 257))
def test_centroid_chunks_ignore_transport_boundaries(chunk_size: int) -> None:
    geometry = tests.helpers.factories.peri_scribe.fires.centroid_streaming.SQUARE
    body = json.dumps({"features": [{"geometry": geometry}]}).encode()
    archive = (
        tests.helpers.factories.peri_scribe.fires.centroid_streaming.archive_bytes(
            {"state.geojson": body},
        )
    )
    chunks = (
        archive[start : start + chunk_size]
        for start in range(0, len(archive), chunk_size)
    )
    actual = np.concatenate(
        list(
            peri_scribe.fires.centroid_streaming.centroid_chunks(
                peri_scribe.fires.centroid_streaming.zip_geometries(chunks),
            ),
        ),
    )
    expected = np.concatenate(
        list(peri_scribe.fires.centroid_streaming.centroid_chunks(iter([geometry]))),
    )
    np.testing.assert_array_equal(actual, expected)
