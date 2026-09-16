"""Tests for peri_scribe.sources.buildings.

The tests use synthetic in-memory archives and temporary databases; they never touch the
network or the real buildings dataset."""

from __future__ import annotations

import pathlib
import tempfile

import hypothesis
import numpy as np
import shapely.geometry

import peri_scribe.sources.buildings
import tests.helpers.factories.peri_scribe.sources.buildings
import tests.helpers.strategies.peri_scribe.sources.buildings


@hypothesis.given(
    points=tests.helpers.strategies.peri_scribe.sources.buildings.encoded_points(),
)
def test_decode_payload_preserves_coordinate_multiset(
    points: list[tuple[int, int]],
) -> None:
    encoded = np.asarray(points, dtype="<i4").reshape(-1, 2)
    payload = peri_scribe.sources.buildings.compress_tile_points(encoded)
    decoded = peri_scribe.sources.buildings.decode_payload(payload)
    assert sorted(map(tuple, decoded.tolist())) == sorted(points)


@hypothesis.given(
    points=tests.helpers.strategies.peri_scribe.sources.buildings.encoded_points(),
)
def test_compress_tile_points_preserves_input(points: list[tuple[int, int]]) -> None:
    encoded = np.asarray(points, dtype="<i4").reshape(-1, 2)
    original = encoded.copy()
    peri_scribe.sources.buildings.compress_tile_points(encoded)
    np.testing.assert_array_equal(encoded, original)


@hypothesis.given(
    longitude=tests.helpers.strategies.peri_scribe.sources.buildings.encoded_coordinate(
        18_000_000,
    ),
    latitude=tests.helpers.strategies.peri_scribe.sources.buildings.encoded_coordinate(
        9_000_000,
    ),
)
def test_tile_ids_for_box_finds_every_encodable_point(
    longitude: int,
    latitude: int,
) -> None:
    scale = peri_scribe.sources.buildings.COORDINATE_SCALE
    box = (longitude / scale, latitude / scale, longitude / scale, latitude / scale)
    identifiers = peri_scribe.sources.buildings.tile_ids(
        np.asarray([[longitude, latitude]], dtype="<i4"),
    )
    tiles = peri_scribe.sources.buildings.tile_ids_for_box(box)
    assert identifiers[0] in tiles
    assert peri_scribe.sources.buildings.tile_id(longitude, latitude) in tiles


# This test is slow, so limit examples to keep routine test runs fast.
@hypothesis.settings(max_examples=25)
@hypothesis.given(
    scenario=tests.helpers.strategies.peri_scribe.sources.buildings.building_queries(),
)
def test_building_counts_within_matches_exhaustive_containment(
    scenario: tuple[np.ndarray, list[shapely.Geometry | None]],
) -> None:
    points, queries = scenario
    scale = peri_scribe.sources.buildings.COORDINATE_SCALE
    stored_points = [
        shapely.Point(round(longitude * scale) / scale, round(latitude * scale) / scale)
        for longitude, latitude in points
    ]
    expected = [
        0
        if geometry is None
        else sum(geometry.contains(point) for point in stored_points)
        for geometry in queries
    ]
    with tempfile.TemporaryDirectory() as temporary_directory:
        path = pathlib.Path(temporary_directory) / "buildings.sqlite"
        tests.helpers.factories.peri_scribe.sources.buildings.write_database(
            points,
            path,
        )
        actual = peri_scribe.sources.buildings.building_counts_within(queries, path)
    assert actual == expected
