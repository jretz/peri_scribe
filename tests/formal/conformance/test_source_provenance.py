"""Lexical source memoization refines the executable pure ordered map contract."""

import pytest

import tests.formal.helpers.source_provenance


@pytest.mark.parametrize("windows", [False, True])
def test_source_paths_matches_bounded_memo_histories(*, windows: bool) -> None:
    expected_histories = 259
    assert (
        tests.formal.helpers.source_provenance.compare_traces(
            windows=windows,
        )
        == expected_histories
    )
