import pathlib
import unittest.mock

import pytest

import tests.formal.check
import tests.formal.helpers.process
import tests.formal.helpers.tlc


def test_models_rejects_unregistered_configuration(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "models.toml").write_text(
        '[[models]]\nname = "example"\nmodule = "Example"\nconfig = "Example"\n',
    )
    (tmp_path / "Example.tla").touch()
    (tmp_path / "Example.cfg").touch()
    (tmp_path / "Unregistered.cfg").touch()
    monkeypatch.setattr(tests.formal.check, "DIRECTORY", tmp_path)
    with pytest.raises(
        ValueError,
        match="Register each TLC configuration exactly once",
    ):
        tests.formal.check.models()


def test_states_uses_final_count_after_intermediate_progress(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "states.dump").write_text("State 1:\n/\\ x = 0\nState 2:\n/\\ x = 1\n")
    monkeypatch.setattr(
        tests.formal.helpers.tlc.shutil,
        "which",
        unittest.mock.Mock(return_value="java"),
    )
    monkeypatch.setenv("PERI_SCRIBE_TLA_JAR", "tools.jar")
    monkeypatch.setattr(
        tests.formal.helpers.process,
        "run",
        unittest.mock.Mock(
            return_value=tests.formal.helpers.process.Result(
                returncode=0,
                stdout="Progress: 1 distinct states found\n"
                "Model checking completed. No error has been found.\n"
                "2 distinct states found\n",
                stderr="",
            ),
        ),
    )
    assert tests.formal.helpers.tlc.states("Example", "Example", tmp_path) == [
        {"x": "0"},
        {"x": "1"},
    ]


@pytest.mark.parametrize(
    ("returncode", "output", "accepted"),
    [
        (0, "Model checking completed. No error has been found.", True),
        (0, "Parsing file Example.tla", False),
        (1, "Model checking completed. No error has been found.", False),
    ],
)
@pytest.mark.asyncio
async def test_run_model_requires_successful_complete_exploration(
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    output: str,
    *,
    accepted: bool,
) -> None:
    result = tests.formal.helpers.process.Result(
        returncode=returncode,
        stdout=output,
        stderr="",
    )
    monkeypatch.setattr(
        tests.formal.helpers.process,
        "execute",
        unittest.mock.AsyncMock(return_value=result),
    )
    model = tests.formal.check.Model(
        name="example",
        module="Example",
        config="Example",
    )
    assert (
        await tests.formal.check.run_model(model, "java", pathlib.Path("tools.jar"))
        is accepted
    )


@pytest.mark.parametrize(
    ("returncode", "output", "accepted"),
    [
        (12, "Error: Invariant KnownLimit is violated.", True),
        (12, "Error: Invariant DifferentLimit is violated.", False),
        (1, "Error: Invariant KnownLimit is violated.", False),
        (0, "Model checking completed. No error has been found.", False),
    ],
)
@pytest.mark.asyncio
async def test_run_model_requires_exact_registered_counterexample(
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    output: str,
    *,
    accepted: bool,
) -> None:
    result = tests.formal.helpers.process.Result(
        returncode=returncode,
        stdout=output,
        stderr="",
    )
    monkeypatch.setattr(
        tests.formal.helpers.process,
        "execute",
        unittest.mock.AsyncMock(return_value=result),
    )
    model = tests.formal.check.Model(
        name="known-limit",
        module="Example",
        config="ExampleExpected",
        expected_invariant="KnownLimit",
    )
    assert (
        await tests.formal.check.run_model(model, "java", pathlib.Path("tools.jar"))
        is accepted
    )
