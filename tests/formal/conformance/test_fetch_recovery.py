import pathlib

import tests.formal.helpers.fetch_recovery


def test_run_fetch_stage_matches_all_checked_fetch_completion_states(
    tmp_path: pathlib.Path,
) -> None:
    outcomes = tests.formal.helpers.fetch_recovery.outcomes(tmp_path / "tlc")
    for index, outcome in enumerate(outcomes):
        tests.formal.helpers.fetch_recovery.replay_outcome(
            outcome,
            tmp_path / str(index) / "2026",
        )


def test_run_fetch_stage_recovers_each_checked_source_interruption_boundary(
    tmp_path: pathlib.Path,
) -> None:
    interruptions = tests.formal.helpers.fetch_recovery.interruptions(tmp_path / "tlc")
    for index, interrupted in enumerate(interruptions):
        tests.formal.helpers.fetch_recovery.replay_interruption(
            interrupted,
            tmp_path / str(index) / "2026",
        )
