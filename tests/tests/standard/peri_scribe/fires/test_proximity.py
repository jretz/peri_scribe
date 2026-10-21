"""Require exact component coverage without dense true-edge materialization."""

from __future__ import annotations

import math
import unittest.mock

import pytest
import shapely

import peri_scribe.fires.proximity
from measurement_units import units


def test_bounds_tree_candidates_drops_exhausted_subtrees() -> None:
    tree = peri_scribe.fires.proximity.bounds_tree([
        (0.0, 0.0, 0.0, 0.0),
        (2.0, 2.0, 2.0, 2.0),
        (4.0, 4.0, 4.0, 4.0),
    ])
    counts = list(tree.counts)
    assert list(
        peri_scribe.fires.proximity.candidates(tree, counts, (-1, -1, 1, 1)),
    ) == [0]
    peri_scribe.fires.proximity.remove(tree, counts, 0)
    assert (
        list(peri_scribe.fires.proximity.candidates(tree, counts, (-1, -1, 1, 1))) == []
    )
    assert set(
        peri_scribe.fires.proximity.candidates(tree, counts, (-1, -1, 5, 5)),
    ) == {1, 2}


def test_bounds_tree_preserves_vertical_extent() -> None:
    tree = peri_scribe.fires.proximity.bounds_tree([
        (0.0, 0.0, 0.0, 0.0),
        (0.0, 2.0, 0.0, 2.0),
        (0.0, 4.0, 0.0, 4.0),
    ])
    assert list(
        peri_scribe.fires.proximity.candidates(tree, list(tree.counts), (-1, 3, 1, 5)),
    ) == [2]


def test_bounds_tree_handles_empty_input() -> None:
    tree = peri_scribe.fires.proximity.bounds_tree([])
    assert tree.nodes == ()
    assert list(peri_scribe.fires.proximity.candidates(tree, [], (0, 0, 1, 1))) == []


def test_spanning_pairs_emits_only_a_forest_for_dense_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    geometries = [shapely.box(0, 0, 1 + index / 1000, 1) for index in range(80)]
    distance = unittest.mock.Mock(wraps=shapely.dwithin)
    monkeypatch.setattr(shapely, "dwithin", distance)
    edges = list(
        peri_scribe.fires.proximity.spanning_pairs(
            geometries,
            tolerance=0.05 * units.degrees,
        ),
    )
    assert len(edges) == len(geometries) - 1
    assert distance.call_count == len(geometries) - 1
    assert {node for edge in edges for node in edge} == set(range(len(geometries)))


def test_spanning_pairs_retains_multipart_bridges_without_a_metric_assumption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(peri_scribe.fires.proximity, "SMALL_QUERY_LIMIT", 0)
    geometries = [
        shapely.box(0, 0, 1, 1),
        shapely.MultiPolygon([shapely.box(0, 0, 1, 1), shapely.box(10, 0, 11, 1)]),
        shapely.box(10, 0, 11, 1),
    ]
    assert set(
        peri_scribe.fires.proximity.spanning_pairs(
            geometries,
            tolerance=0.05 * units.degrees,
        ),
    ) == {(0, 1), (1, 2)}


def test_spanning_pairs_keeps_exact_predicate_for_envelope_false_positives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(peri_scribe.fires.proximity, "SMALL_QUERY_LIMIT", 0)
    assert (
        list(
            peri_scribe.fires.proximity.spanning_pairs(
                [shapely.Point(0, 0), shapely.Point(0.04, 0.04)],
                tolerance=0.05 * units.degrees,
            ),
        )
        == []
    )


def test_spanning_pairs_keeps_empty_geometry_outside_proximity() -> None:
    assert (
        list(
            peri_scribe.fires.proximity.spanning_pairs(
                [shapely.Point(), shapely.Point(0, 0)],
                tolerance=0.05 * units.degrees,
            ),
        )
        == []
    )


def test_spanning_pairs_keeps_nonfinite_envelopes_in_the_existing_geometry_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(peri_scribe.fires.proximity, "SMALL_QUERY_LIMIT", 0)
    assert (
        list(
            peri_scribe.fires.proximity.spanning_pairs(
                [shapely.Point(), shapely.Point(0, 0)],
                tolerance=0.05 * units.degrees,
            ),
        )
        == []
    )


@pytest.mark.parametrize(
    ("coordinate", "expected"),
    [(0.05, [(0, 1)]), (math.nextafter(0.05, math.inf), [])],
)
def test_spanning_pairs_retains_exact_threshold_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    coordinate: float,
    expected: list[tuple[int, int]],
) -> None:
    monkeypatch.setattr(peri_scribe.fires.proximity, "SMALL_QUERY_LIMIT", 0)
    geometries = [shapely.Point(0, 0), shapely.Point(coordinate, 0)]
    result = list(
        peri_scribe.fires.proximity.spanning_pairs(
            geometries,
            tolerance=0.05 * units.degrees,
        ),
    )
    assert result == expected
