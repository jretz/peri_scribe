"""Compose actual rotation representations with complete current-owner snapshots."""

import pathlib

import tests.formal.helpers.update_log_chronology


def test_read_entries_and_write_updates_page_match_checked_complete_history(
    tmp_path: pathlib.Path,
) -> None:
    catalogue = tests.formal.helpers.update_log_chronology.cases(tmp_path / "tlc")
    assert (
        tests.formal.helpers.update_log_chronology.replay(
            catalogue,
            tmp_path / "replay",
        )
        == tests.formal.helpers.update_log_chronology.COMPOSED_CASES
    )
    tests.formal.helpers.update_log_chronology.concurrent_read(
        catalogue,
        tmp_path / "concurrent",
    )
