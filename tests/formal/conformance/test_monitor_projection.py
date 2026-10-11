"""Compaction and cached health assessments agree with checked transitions."""

import pathlib

import tests.formal.helpers.corpus
import tests.formal.helpers.observers


def test_refresh_refines_tlc_compaction_and_projection(tmp_path: pathlib.Path) -> None:
    states = tests.formal.helpers.corpus.states(
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
