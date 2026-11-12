import asyncio
import pathlib
import unittest.mock

import pytest

import tests.formal.check
import tests.formal.helpers.corpus
import tests.formal.helpers.model_registry
import tests.formal.helpers.process
import tests.formal.helpers.session
import tests.formal.helpers.tlc
import tests.formal.helpers.tlc_worker


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    ["parsed-cache", "parsed-cache-read", "source-summaries"],
)
async def test_stock_models_run_independently_of_the_frame_worker(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    monkeypatch.delenv(tests.formal.helpers.session.VARIABLE, raising=False)
    java, jar = tests.formal.check.toolchain()
    worker = unittest.mock.Mock(
        cwd=tests.formal.check.DIRECTORY,
        framed=True,
        execute=unittest.mock.AsyncMock(
            side_effect=AssertionError("Stock TLC requires a fresh JVM"),
        ),
    )
    model = next(model for model in tests.formal.check.models() if model.name == name)
    assert await tests.formal.check.run_model(
        model,
        java,
        jar,
        tmp_path,
        worker=worker,
    )
    worker.execute.assert_not_awaited()
    if name == "parsed-cache-read":
        expected_states = 696
        states = tests.formal.helpers.corpus.states(
            model.module,
            model.config,
            tmp_path,
        )
        assert len(states) == expected_states


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
    (tmp_path / "states.dump").write_text(
        "State 1:\n/\\ x = 0\n\nState 2:\n/\\ x = 1\n\n",
    )
    monkeypatch.setattr(
        tests.formal.helpers.tlc.shutil,
        "which",
        unittest.mock.Mock(return_value="java"),
    )
    monkeypatch.setenv("PERI_SCRIBE_TLA_JAR", "tools.jar")
    monkeypatch.setattr(
        tests.formal.helpers.process,
        "execute",
        unittest.mock.AsyncMock(
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


@pytest.mark.asyncio
async def test_run_model_exports_once_for_graph_and_state_consumers(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(tests.formal.helpers.session.VARIABLE, raising=False)
    output = (
        "Finished computing initial states: 1 distinct state generated\n"
        "Model checking completed. No error has been found.\n"
        "2 distinct states found\n"
    )
    explore = unittest.mock.AsyncMock(
        return_value=(
            (
                'digraph {\n-1 [label="/\\\\ x = <<0,\\n  1>>\\n/\\\\ y = 2",'
                "style = filled];\n"
                '2 [label="/\\\\ x = 1"];\n'
                '-1 -> 2 [label="Next \\"step\\"",color="black"];\n'
                '-1 -> -1 [style="dashed"];\n}\n'
            ),
            output,
        ),
    )
    monkeypatch.setattr(tests.formal.helpers.tlc, "explore_async", explore)
    model = tests.formal.check.Model(
        name="example",
        module="Example",
        config="Bounded",
        conformance=tests.formal.helpers.model_registry.Export.GRAPH,
    )
    assert await tests.formal.check.run_model(
        model,
        "java",
        pathlib.Path("tools.jar"),
        tmp_path,
    )
    graph = tests.formal.helpers.corpus.graph("Example", "Bounded", tmp_path)
    assert graph.initial == frozenset({-1})
    assert graph.outgoing[-1] == (
        tests.formal.helpers.tlc.Edge(source=-1, target=2, action='Next "step"'),
    )
    assert tests.formal.helpers.corpus.states("Example", "Bounded", tmp_path) == [
        {"x": "<<0,\n  1>>", "y": "2"},
        {"x": "1"},
    ]
    explore.assert_awaited_once()


@pytest.mark.asyncio
async def test_state_only_receipt_cannot_satisfy_graph_consumers(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(tests.formal.helpers.session.VARIABLE, raising=False)
    output = (
        "Model checking completed. No error has been found.\n"
        "2 states generated, 2 distinct states found, 0 states left on queue.\n"
    )
    explore = unittest.mock.AsyncMock(
        return_value=("State 1:\n/\\ x = 0\n\nState 2:\n/\\ x = 1\n\n", output),
    )
    monkeypatch.setattr(tests.formal.helpers.tlc, "explore_async", explore)
    model = next(
        model for model in tests.formal.check.models() if model.name == "boundary-spill"
    )
    corpus = tests.formal.helpers.corpus
    arguments = (model.module, model.config, tmp_path)
    with pytest.raises(ValueError, match="A graph is required"):
        corpus.graph(*arguments)
    assert await tests.formal.check.run_model(
        model,
        "java",
        pathlib.Path("tools.jar"),
        tmp_path,
    )
    assert corpus.states(*arguments) == [{"x": "0"}, {"x": "1"}]
    with pytest.raises(ValueError, match="A graph is required"):
        await corpus.checked_graph(*arguments)
    assert (tmp_path / "states-BoundarySpill-BoundarySpill.json").is_file()
    assert not (tmp_path / "graph-BoundarySpill-BoundarySpill.json").exists()
    explore.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_models_reuses_a_worker_after_a_reported_model_failure(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models = tuple(
        tests.formal.check.Model(name=name, module=name, config=name)
        for name in ("first", "failure", "last")
    )
    classes = tmp_path / "classes"
    compile_worker = unittest.mock.AsyncMock(return_value=classes)
    worker = unittest.mock.Mock(close=unittest.mock.AsyncMock())
    create_worker = unittest.mock.Mock(return_value=worker)
    run_model = unittest.mock.AsyncMock(side_effect=(True, False, True))
    monkeypatch.setattr(tests.formal.helpers.process, "inherited_group", lambda: None)
    monkeypatch.setattr(
        tests.formal.helpers.tlc_worker,
        "compile_worker",
        compile_worker,
    )
    monkeypatch.setattr(tests.formal.helpers.tlc_worker, "Worker", create_worker)
    monkeypatch.setattr(tests.formal.check, "run_model", run_model)
    jar = tmp_path / "tools.jar"
    jar.write_bytes(b"mocked checker archive")
    assert not await tests.formal.check.run_models(
        models,
        "java",
        jar,
        semaphore=asyncio.Semaphore(1),
        corpus_directory=tmp_path,
    )
    compile_worker.assert_awaited_once_with("java", tmp_path, jar=jar)
    create_worker.assert_called_once_with(
        "java",
        jar,
        classes,
        tests.formal.check.DIRECTORY,
    )
    assert [call.args[0] for call in run_model.await_args_list] == list(models)
    assert all(call.kwargs["worker"] is worker for call in run_model.await_args_list)
    worker.close.assert_awaited_once_with()


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
