"""Feed failures and successful siblings compose without lost recovery obligations."""

import pathlib

import tests.formal.helpers.corpus
import tests.formal.helpers.feed_components
import tests.formal.helpers.feed_coordinator


def test_run_fetch_stage_matches_checked_collection_outcomes(
    tmp_path: pathlib.Path,
) -> None:
    states = tuple(
        tests.formal.helpers.corpus.projected_states(
            "FeedCoordinator",
            "FeedCoordinator",
            tmp_path / "model",
            (
                "phase",
                "kind",
                "full",
                "prior",
                "indexFailure",
                "deferIndex",
                "snapshots",
                "indexed",
                "pending",
                "acknowledged",
                "indexAttempted",
                "result",
            ),
            where=("phase", frozenset({'"index"', '"done"', '"failed"'})),
        ),
    )
    checked = tests.formal.helpers.feed_coordinator.cases(states)
    cuts = tests.formal.helpers.feed_components.check_projection(states, checked)
    expected_cases = 2000
    expected_waves = 250
    counts = tests.formal.helpers.feed_components.replay(
        checked,
        cuts,
        tmp_path / "collections",
    )
    assert counts.policies == expected_cases
    assert counts.native in {expected_waves, expected_cases}
    assert counts.coupled == (42 if counts.native == expected_waves else 0)
    expected_cancellations = 32
    assert (
        tests.formal.helpers.feed_coordinator.replay_cancellation(
            checked,
            tmp_path / "cancellations",
        )
        == expected_cancellations
    )
