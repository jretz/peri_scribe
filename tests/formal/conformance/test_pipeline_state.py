import pathlib

import tests.formal.helpers.pipeline_state


def test_require_stages_and_complete_stage_match_every_checked_tlc_transition(
    tmp_path: pathlib.Path,
) -> None:
    transitions = tests.formal.helpers.pipeline_state.transitions(tmp_path)
    tests.formal.helpers.pipeline_state.check_lean(transitions)
    for transition in transitions:
        tests.formal.helpers.pipeline_state.replay(transition, tmp_path / "year")
