"""Byte-level plain and compressed log queries agree with the proved search policy."""

import pathlib

import tests.formal.helpers.log_seeking


def test_seek_since_and_complete_lines_match_proved_reference(
    tmp_path: pathlib.Path,
) -> None:
    expected_histories = 8184
    assert (
        tests.formal.helpers.log_seeking.replay(tmp_path / "logs") == expected_histories
    )


def test_reader_preserves_checked_history_through_clock_rollbacks(
    tmp_path: pathlib.Path,
) -> None:
    expected_readers = 128
    assert tests.formal.helpers.log_seeking.replay_monitor(tmp_path) == expected_readers
