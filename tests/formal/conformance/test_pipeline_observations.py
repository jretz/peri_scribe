import pathlib
import unittest.mock

import pytest

import tests.formal.helpers.paths
import tests.formal.helpers.pipeline_observations


@pytest.mark.parametrize(
    "boundary",
    [
        "pending replace",
        "publication replace",
        "pending unlink",
        "publication unlink",
        "deferred touch",
        "deferred unlink",
    ],
)
def test_replay_install_observer_reads_all_current_files_at_every_mutation(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    scenario = tests.formal.helpers.pipeline_observations.scenario(tmp_path / "2026")
    execution = unittest.mock.Mock(spec=tests.formal.helpers.paths.Path)
    execution.observe.return_value = execution
    scenario.execution = execution
    scenario.begun = True
    previous = scenario.snapshot()
    scenario.install_observer(monkeypatch)
    scenario.source_path().write_text("1")
    scenario.output_path(4).write_text("1")

    tests.formal.helpers.pipeline_observations.mutate(scenario, boundary)

    observed = scenario.snapshot()
    assert observed != previous
    assert observed.source == 1
    assert observed.outputs[-1] == 1
    execution.observe.assert_called_once_with(observed)


def test_replay_inputs_retains_fresh_inventory_containers(
    tmp_path: pathlib.Path,
) -> None:
    scenario = tests.formal.helpers.pipeline_observations.scenario(tmp_path / "2026")
    first = scenario.inputs(1)
    expected = first.model_copy(deep=True)
    first.files.clear()
    first.mappings.clear()

    assert scenario.inputs(1) == expected
