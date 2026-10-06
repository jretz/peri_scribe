"""Real diagnostics retain every occurrence across the checked rotation protocol."""

import pathlib

import tests.formal.helpers.corpus
import tests.formal.helpers.log_rotation


def test_compress_log_matches_checked_interruption_histories(
    tmp_path: pathlib.Path,
) -> None:
    graph = tests.formal.helpers.corpus.graph(
        "LogRotation",
        "LogRotation",
        tmp_path / "model",
    )
    expected_histories = 162
    assert (
        tests.formal.helpers.log_rotation.replay(
            graph,
            tmp_path / "rotations",
        )
        == expected_histories
    )
