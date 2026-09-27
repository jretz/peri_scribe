"""Exact centroid and streaming definitions constrain real arrays and files."""

import pathlib

import pytest

import tests.formal.helpers.building_centroids


def test_projected_centroids_match_lean_exact_moments() -> None:
    tests.formal.helpers.building_centroids.replay_math()


@pytest.mark.parametrize(
    ("limit", "budget"),
    [(1, 1), (2, 6), (3, 20), (10, 100), (0, 0)],
)
def test_collect_geometry_chunk_matches_lean_complete_feature_partition(
    limit: int,
    budget: int,
) -> None:
    tests.formal.helpers.building_centroids.replay_chunks(limit, budget)


@pytest.mark.parametrize(
    ("byte_chunk", "feature_limit", "vertex_budget"),
    [(1, 1, 1), (17, 2, 10), (257, 10, 1_000_000)],
)
def test_convert_zip_stream_preserves_proved_centroids_in_real_geopackage(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    byte_chunk: int,
    feature_limit: int,
    vertex_budget: int,
) -> None:
    tests.formal.helpers.building_centroids.replay_archive(
        tmp_path,
        monkeypatch,
        byte_chunk=byte_chunk,
        feature_limit=feature_limit,
        vertex_budget=vertex_budget,
    )
