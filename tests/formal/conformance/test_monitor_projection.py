"""Compaction and complete cached views agree with checked projection transitions."""

import pathlib

import tests.formal.helpers.observers
import tests.formal.helpers.tlc


def test_refresh_refines_tlc_compaction_and_projection(tmp_path: pathlib.Path) -> None:
    states = tests.formal.helpers.tlc.states(
        "MonitorProjection",
        "MonitorProjection",
        tmp_path,
    )
    histories = {}
    checked = 0
    for state in states:
        if state["phase"] != '"done"':
            continue
        events = tests.formal.helpers.observers.projection_events(state["events"])
        if events not in histories:
            histories[events] = tests.formal.helpers.observers.projection_history(
                events,
            )
        tests.formal.helpers.observers.replay_projection(state, histories[events])
        checked += 1
    assert checked == tests.formal.helpers.observers.PROJECTION_CASE_COUNT
    assert len(histories) == tests.formal.helpers.observers.PROJECTION_HISTORY_COUNT
    for history in histories.values():
        tests.formal.helpers.observers.replay_projection_boundaries(history)
