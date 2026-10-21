"""Actual worker reads and pending admission follow the complete checked graph."""

import pathlib

import tests.formal.helpers.corpus
import tests.formal.helpers.parallel_source_authentication
import tests.formal.helpers.source_authentication


def test_inventory_digests_matches_all_checked_parallel_authentication_transitions(
    tmp_path: pathlib.Path,
) -> None:
    graph = tests.formal.helpers.corpus.graph(
        "ParallelSourceAuthentication",
        "ParallelSourceAuthentication",
        tmp_path / "tlc",
    )
    histories = tests.formal.helpers.source_authentication.edge_histories(graph)
    observed = set()
    for index, history in enumerate(histories):
        observed.update(
            tests.formal.helpers.parallel_source_authentication.replay(
                graph,
                history,
                tmp_path / f"replay-{index}",
            ),
        )
    assert len(histories) == sum(map(len, graph.outgoing.values()))
    assert observed == {
        "read",
        "failure",
        "stop",
        "edit",
        "cancel",
        "fork",
        "cleanup",
        "expire",
        "join",
        "publish",
        "reject",
        "failed_join",
    }
