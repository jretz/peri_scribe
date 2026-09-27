"""Source races can defer observations, and a stable full fetch repairs them."""

import pathlib

import tests.formal.helpers.snapshot_collection
import tests.formal.helpers.tlc


def test_fetch_feed_snapshot_matches_checked_query_interleavings(
    tmp_path: pathlib.Path,
) -> None:
    states = tests.formal.helpers.tlc.states(
        "SnapshotCollection",
        "SnapshotCollection",
        tmp_path / "model",
    )
    cases = tests.formal.helpers.snapshot_collection.cases(states)
    expected_cases = 177
    assert len(cases) == expected_cases
    stale_cases = 0
    for number, case in enumerate(cases):
        actual = tests.formal.helpers.snapshot_collection.replay_case(
            case,
            tmp_path / "cases" / str(number),
        )
        completed = {
            tests.formal.helpers.snapshot_collection.numbers(state["saved"])
            for state in states
            if state["recovery"] == "TRUE"
            and state["phase"] == '"done"'
            and tests.formal.helpers.snapshot_collection.numbers(state["remote"])
            == case.remote
            and int(state["observedMarker"]) == case.remote_marker
            and tests.formal.helpers.snapshot_collection.numbers(state["recoveryBase"])
            == case.saved
        }
        assert len(completed) == 1
        assert actual == next(iter(completed))
        assert all(
            not version or actual[index] == version
            for index, version in enumerate(case.remote)
        )
        stale_cases += any(
            version and case.saved[index] != version
            for index, version in enumerate(case.remote)
        )
    expected_stale_cases = 97
    assert stale_cases == expected_stale_cases
