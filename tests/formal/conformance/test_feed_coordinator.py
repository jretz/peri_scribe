"""Feed failures and successful siblings compose without lost recovery obligations."""

import pathlib

import tests.formal.helpers.feed_coordinator
import tests.formal.helpers.tlc


def test_run_fetch_stage_matches_checked_collection_outcomes(
    tmp_path: pathlib.Path,
) -> None:
    states = tests.formal.helpers.tlc.states(
        "FeedCoordinator",
        "FeedCoordinator",
        tmp_path / "model",
    )
    expected_cases = 2000
    assert (
        tests.formal.helpers.feed_coordinator.replay(
            states,
            tmp_path / "collections",
        )
        == expected_cases
    )
    expected_cancellations = 32
    assert (
        tests.formal.helpers.feed_coordinator.replay_cancellation(
            states,
            tmp_path / "cancellations",
        )
        == expected_cancellations
    )
