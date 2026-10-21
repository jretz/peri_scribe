"""Persistent incidence closures agree with the unbounded Lean path specification."""

import pytest

import tests.formal.helpers.retained_source_index


@pytest.mark.parametrize("mixed_tags", [False, True])
def test_affected_rows_matches_every_bounded_retained_inventory_history(
    *,
    mixed_tags: bool,
) -> None:
    assert (
        tests.formal.helpers.retained_source_index.compare_histories(
            mixed_tags=mixed_tags,
        )
        == tests.formal.helpers.retained_source_index.HISTORY_COUNT
    )
