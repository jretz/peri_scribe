"""Stage supervision follows one complete checked execution through every handoff."""

import pathlib

import pytest

import tests.formal.helpers.corpus
import tests.formal.helpers.stage_processes


@pytest.mark.parametrize(
    "scenario",
    [
        {},
        {"skip": True},
        {"failure": 1},
        {"failure": 2},
        {"failure": 3},
        {"cancellation": 1},
        {"cancellation": 2},
        {"launch_failure": 1},
        {"launch_failure": 2},
        {"bad_response": 1},
        {"bad_response": 2},
    ],
)
def test_supervised_segment_paths_match_checked_contract(
    tmp_path: pathlib.Path,
    scenario: tests.formal.helpers.stage_processes.Scenario,
) -> None:
    graph = tests.formal.helpers.corpus.graph(
        "StageProcesses",
        "StageProcesses",
        tmp_path / "model",
    )
    tests.formal.helpers.stage_processes.Replay(
        year=tmp_path / "year",
        checked=tests.formal.helpers.stage_processes.contract(graph),
        **scenario,
    ).run()
