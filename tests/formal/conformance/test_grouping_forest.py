"""Check real geometry forests against every freshly model-checked abstract graph."""

from __future__ import annotations

import itertools
import pathlib
import typing

import shapely

import peri_scribe.fires.proximity
import tests.formal.helpers.corpus
import tests.formal.helpers.grouping_forest
from measurement_units import units


if typing.TYPE_CHECKING:
    import pytest


def test_spanning_pairs_matches_all_checked_graph_forests(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = tests.formal.helpers.corpus.graph(
        "GroupingForest",
        "GroupingForest",
        tmp_path / "tlc",
    )
    final = tests.formal.helpers.grouping_forest.final_forests(graph)
    initial = {
        tests.formal.helpers.grouping_forest.edges(graph.states[node]["graph"])
        for node in graph.initial
    }
    assert final.keys() == initial
    monkeypatch.setattr(peri_scribe.fires.proximity, "SMALL_QUERY_LIMIT", 0)
    for edges, admitted in final.items():
        geometries = tests.formal.helpers.grouping_forest.geometries(edges)
        realized = frozenset(
            (left, right)
            for left, right in itertools.combinations(range(len(geometries)), 2)
            if shapely.dwithin(geometries[left], geometries[right], 0.05)
        )
        assert realized == edges
        actual = frozenset(
            tuple(sorted(pair))
            for pair in peri_scribe.fires.proximity.spanning_pairs(
                geometries,
                tolerance=0.05 * units.degrees,
            )
        )
        assert actual in admitted
