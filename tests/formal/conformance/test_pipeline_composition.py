import pathlib

import pytest

import tests.formal.helpers.pipeline_batches
import tests.formal.helpers.pipeline_composition


@pytest.mark.parametrize(
    "batch",
    range(tests.formal.helpers.pipeline_composition.BATCH_COUNT),
)
def test_run_selected_stages_matches_composed_invocations_and_crash_boundaries(
    tmp_path: pathlib.Path,
    pipeline_executions: tests.formal.helpers.pipeline_composition.Executions,
    pipeline_batches: tuple[
        tuple[tests.formal.helpers.pipeline_batches.Branch, ...],
        ...,
    ],
    batch: int,
) -> None:
    selected = pipeline_batches[batch]
    completed = tests.formal.helpers.pipeline_batches.replay(
        selected,
        tmp_path,
        pipeline_executions.checked,
    )
    assert set(completed) == set(
        tests.formal.helpers.pipeline_batches.histories(selected),
    )
