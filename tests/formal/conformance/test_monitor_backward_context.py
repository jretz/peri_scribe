"""Backward command recovery matches the checked complete ordered context."""

import pathlib

import tests.formal.helpers.corpus
import tests.formal.helpers.monitor_backward_context


def test_backward_context_matches_checked_searches(tmp_path: pathlib.Path) -> None:
    expected_states = 13460
    expected_searches = 2884
    states = tests.formal.helpers.corpus.states(
        "MonitorBackwardContext",
        "MonitorBackwardContext",
        tmp_path / "model",
    )
    assert len(states) == expected_states
    directory = tmp_path / "logs"
    directory.mkdir()
    checked = 0
    for state in states:
        if state["ready"] == "TRUE":
            tests.formal.helpers.monitor_backward_context.replay(state, directory)
            checked += 1
    assert checked == expected_searches
