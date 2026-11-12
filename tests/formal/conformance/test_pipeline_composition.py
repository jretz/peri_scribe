import pathlib
import unittest.mock

import pytest

import peri_scribe.durable_file
import tests.formal.helpers.paths
import tests.formal.helpers.pipeline_batches
import tests.formal.helpers.pipeline_composition
import tests.formal.helpers.pipeline_effect_matrix
import tests.formal.helpers.pipeline_observations
import tests.formal.helpers.pipeline_replay_files


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
    formal_corpus_directory: pathlib.Path,
    batch: int,
) -> None:
    selected = pipeline_batches[batch]
    effects: tests.formal.helpers.pipeline_replay_files.Effects = {}
    completed = tests.formal.helpers.pipeline_batches.replay_memory(
        selected,
        tmp_path,
        pipeline_executions.checked,
        effects,
    )
    assert set(completed) == set(
        tests.formal.helpers.pipeline_batches.histories(selected),
    )
    tests.formal.helpers.pipeline_effect_matrix.check_effects(
        effects,
        formal_corpus_directory,
    )


def test_replay_memory_observes_unrelated_artifacts_in_the_mutated_branch(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = tests.formal.helpers.pipeline_observations.scenario(
        tmp_path / "real" / "2026",
    )
    image = tests.formal.helpers.pipeline_replay_files.read_image(real.directory)
    directory = tmp_path / "memory" / "2026"
    parent = tests.formal.helpers.pipeline_replay_files.Memory(
        directory=directory,
        effects={},
        entries=list(image),
        maps_present=True,
    )
    branch = parent.fork()
    sibling = parent.fork()
    execution = unittest.mock.Mock(spec=tests.formal.helpers.paths.Path)
    execution.observe.return_value = execution
    replay = tests.formal.helpers.pipeline_composition.Replay(
        invocation=real.invocation,
        directory=directory,
        memory=branch,
        execution=execution,
        begun=True,
    )
    branch.observe = replay.inspect
    monkeypatch.setattr(peri_scribe.durable_file, "at", branch.at)
    replay.files.write_generation(replay.source_path(), b"1")
    replay.files.write_generation(replay.output_path(4), b"1")
    tests.formal.helpers.pipeline_observations.mutate(replay, "pending replace")

    value = replay.snapshot()
    assert value.source == value.outputs[-1] == 1
    execution.observe.assert_called_once_with(value)
    assert tuple(parent.entries) == tuple(sibling.entries) == image
