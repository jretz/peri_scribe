"""Generate pipeline state examples with constrained domains."""

import dataclasses

import hypothesis.strategies

import peri_scribe.pipeline_stages
import peri_scribe.pipeline_state


@dataclasses.dataclass(frozen=True, kw_only=True)
class RunAction:
    """A generated invalidation or completion can revisit any derived stage."""

    stage: peri_scribe.pipeline_stages.Stage
    require: bool
    unconditional: bool


def run_actions() -> hypothesis.strategies.SearchStrategy[list[RunAction]]:
    """Infer action flags while restricting stages to the recovery domain.

    Returns:
        Bounded sequences of invalidations and stage completions.
    """
    return hypothesis.strategies.lists(
        hypothesis.strategies.builds(
            RunAction,
            stage=hypothesis.strategies.sampled_from(
                peri_scribe.pipeline_state.DERIVED_STAGES,
            ),
        ),
        max_size=25,
    )
