"""Cooperating readers observe complete histories through every rotation boundary."""

import pathlib

import tests.formal.helpers.corpus
import tests.formal.helpers.log_readers


def test_complete_lines_matches_checked_reader_observations(
    tmp_path: pathlib.Path,
) -> None:
    graph = tests.formal.helpers.corpus.graph(
        "LogReaders",
        "LogReaders",
        tmp_path / "model",
    )
    states = list(graph.states.values())
    root = tmp_path / "reads"
    root.mkdir()
    expected_states = 20
    assert tests.formal.helpers.log_readers.replay(states, root) == expected_states
    tests.formal.helpers.log_readers.concurrent_replay(states, tmp_path / "concurrent")
    sequences = tmp_path / "sequences"
    sequences.mkdir()
    expected_pairs = 110
    assert (
        tests.formal.helpers.log_readers.successive_replay(graph, sequences)
        == expected_pairs
    )
