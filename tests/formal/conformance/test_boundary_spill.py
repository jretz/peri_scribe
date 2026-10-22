"""Publication-local boundary storage follows complete checked operation prefixes."""

import pathlib

import tests.formal.helpers.boundary_spill
import tests.formal.helpers.corpus
import tests.formal.helpers.ordered_workers


def test_boundary_spool_matches_every_checked_prefix(tmp_path: pathlib.Path) -> None:
    states = tests.formal.helpers.corpus.states(
        "BoundarySpill",
        "BoundarySpill",
        tmp_path,
    )
    assert {int(state["limit"]) for state in states} == {1, 2}
    assert {
        action
        for state in states
        for action in tests.formal.helpers.ordered_workers.numbers(state["trace"])
    } == {1, 2, 11, 12, 13, 21, 22, 23, 31, 32, 33, 41, 42}
    for state in states:
        tests.formal.helpers.boundary_spill.replay(state)
