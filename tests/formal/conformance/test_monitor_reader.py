"""Real cursor handles replay complete TLC traces without record loss or repetition."""

import pathlib
import tempfile

import tests.formal.helpers.corpus
import tests.formal.helpers.observers


def test_follower_poll_refines_tlc_cursor_traces(tmp_path: pathlib.Path) -> None:
    states = tests.formal.helpers.corpus.states(
        "MonitorReader",
        "MonitorReader",
        tmp_path,
    )
    assert len(states) == tests.formal.helpers.observers.CURSOR_STATE_COUNT
    traces = {
        tuple(tests.formal.helpers.observers.sequence(state["trace"]))
        for state in states
    }
    assert ("partial", "poll", "truncate", "poll", "write", "poll") in traces
    assert ("write", "poll", "partial", "truncate", "poll", "write", "poll") in traces
    for state in states:
        with tempfile.TemporaryDirectory(dir=tmp_path) as directory:
            tests.formal.helpers.observers.replay_reader(state, pathlib.Path(directory))
