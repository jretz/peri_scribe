"""Segment readers preserve the occurrences in every checked durable boundary state."""

import pathlib

import tests.formal.helpers.corpus
import tests.formal.helpers.log_segments


def test_complete_lines_matches_every_checked_segment_state(
    tmp_path: pathlib.Path,
) -> None:
    states = tests.formal.helpers.corpus.states(
        "LogSegments",
        "LogSegments",
        tmp_path / "model",
    )
    expected_states = 54
    assert len(states) == expected_states
    for index, state in enumerate(states):
        tests.formal.helpers.log_segments.observe(state, tmp_path / f"state-{index}")
