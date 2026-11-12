"""Real cursor handles replay complete TLC traces without record loss or repetition."""

import pathlib

import tests.formal.helpers.corpus
import tests.formal.helpers.observers


def test_follower_poll_refines_tlc_cursor_traces(tmp_path: pathlib.Path) -> None:
    states = tests.formal.helpers.corpus.states(
        "MonitorReader",
        "MonitorReader",
        tmp_path,
    )
    assert len(states) == tests.formal.helpers.observers.CURSOR_STATE_COUNT
    expected = {
        tuple(tests.formal.helpers.observers.sequence(state["trace"])): tuple(
            tests.formal.helpers.observers.sequence(state["delivered"]),
        )
        for state in states
    }
    assert len(expected) == len(states)
    assert ("partial", "poll", "truncate", "poll", "write", "poll") in expected
    assert ("write", "poll", "partial", "truncate", "poll", "write", "poll") in expected
    parents = {trace[:-1] for trace in expected if trace}
    assert parents <= expected.keys()
    checked: set[tests.formal.helpers.observers.ReaderTrace] = set()
    terminal_shapes = set()
    directory = tmp_path / "reader"
    directory.mkdir()
    for trace in expected:
        if trace in parents:
            continue
        terminal_shapes.add(
            tests.formal.helpers.observers.replay_reader(
                trace,
                expected,
                checked,
                directory,
            ),
        )
        for path in directory.iterdir():
            path.unlink()
    assert checked == expected.keys()
    assert terminal_shapes == {
        (False, False),
        (False, True),
        (True, False),
        (True, True),
    }
