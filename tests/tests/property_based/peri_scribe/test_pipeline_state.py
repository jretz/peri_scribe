"""Recovery requirements survive failures and respect stage ordering."""

import pathlib
import tempfile

import hypothesis

import peri_scribe.pipeline_stages
import peri_scribe.pipeline_state
import tests.helpers.strategies.peri_scribe.pipeline_state


@hypothesis.given(
    actions=tests.helpers.strategies.peri_scribe.pipeline_state.run_actions(),
)
def test_complete_stage_matches_recovery_model_after_generated_actions(
    actions: list[tests.helpers.strategies.peri_scribe.pipeline_state.RunAction],
) -> None:
    order = peri_scribe.pipeline_state.DERIVED_STAGES
    pending: set[peri_scribe.pipeline_stages.Stage] = set()
    unconditional = False
    with tempfile.TemporaryDirectory() as directory:
        year_directory = pathlib.Path(directory)
        for action in actions:
            if action.require:
                peri_scribe.pipeline_state.require_stages(
                    year_directory,
                    (action.stage,),
                    unconditional=action.unconditional,
                )
                pending.add(action.stage)
                unconditional |= action.unconditional
            else:
                peri_scribe.pipeline_state.complete_stage(year_directory, action.stage)
                if pending and action.stage == min(pending, key=order.index):
                    pending.remove(action.stage)
                    unconditional &= bool(pending)
            state = peri_scribe.pipeline_state.read_state(year_directory)
            assert state.remaining == tuple(sorted(pending, key=order.index))
            assert state.unconditional == unconditional
