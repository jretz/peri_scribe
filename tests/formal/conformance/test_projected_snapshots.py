"""Current ownership and chronological history compose into exact emitted snapshots."""

import tests.formal.helpers.projected_snapshots


def test_snapshot_from_entries_matches_projected_complete_history_reference() -> None:
    expected = 24576
    assert (
        tests.formal.helpers.projected_snapshots.compare(
            tests.formal.helpers.projected_snapshots.cases(),
        )
        == expected
    )
