import pathlib

import structlog.testing

import tests.formal.helpers.pipeline_state


def test_require_stages_and_complete_stage_match_every_checked_tlc_transition(
    tmp_path: pathlib.Path,
) -> None:
    transitions = tests.formal.helpers.pipeline_state.transitions(tmp_path)
    tests.formal.helpers.pipeline_state.check_lean(transitions)
    with structlog.testing.capture_logs():
        total, native = tests.formal.helpers.pipeline_state.replay_all(
            transitions,
            tmp_path / "year",
        )
    assert total == len(transitions)
    assert native in {288, len(transitions)}
