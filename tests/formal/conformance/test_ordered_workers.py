"""Ordered worker executions follow complete checked scheduler paths."""

import itertools
import pathlib

import tests.formal.helpers.corpus
import tests.formal.helpers.ordered_workers


def test_ordered_parallel_map_preserves_checked_complete_paths(
    tmp_path: pathlib.Path,
) -> None:
    graph = tests.formal.helpers.corpus.graph(
        "OrderedWorkers",
        "OrderedWorkers",
        tmp_path,
    )
    checked = tests.formal.helpers.ordered_workers.contract(graph)
    initial = {
        (checked.values[state][7], checked.values[state][8]) for state in graph.initial
    }
    assert len(initial) == tests.formal.helpers.ordered_workers.CONFIGURATION_COUNT
    for weights, failures in initial:
        for completion_order in itertools.permutations((1, 2, 3)):
            for stop in (None, 0, 1):
                tests.formal.helpers.ordered_workers.Replay(
                    checked=checked,
                    weights=weights,
                    failures=failures,
                    completion_order=completion_order,
                    stop=stop,
                ).run()
