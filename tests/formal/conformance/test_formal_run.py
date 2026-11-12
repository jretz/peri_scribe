import asyncio
import contextlib
import pathlib
import unittest.mock

import pytest

import tests.formal.check
import tests.formal.helpers.process
import tests.formal.helpers.session
import tests.formal.run


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ordinary_done", "lean_status", "expected_calls", "expected_status"),
    [
        ((False, False), 0, 2, 7),
        ((False, False), 1, 1, 0),
        ((False, True), 0, 1, 0),
        ((True, True), 0, 0, 0),
    ],
)
async def test_prepare_pristine_requires_a_current_build_and_ordinary_work(
    monkeypatch: pytest.MonkeyPatch,
    ordinary_done: tuple[bool, bool],
    lean_status: int,
    expected_calls: int,
    expected_status: int,
) -> None:
    ordinary = unittest.mock.Mock(spec=asyncio.Task)
    ordinary.done.side_effect = ordinary_done
    execute = unittest.mock.AsyncMock(
        side_effect=[
            tests.formal.helpers.process.Result(
                returncode=lean_status,
                stdout="",
                stderr="",
            ),
            tests.formal.helpers.process.Result(returncode=7, stdout="", stderr=""),
        ],
    )
    monkeypatch.setattr(tests.formal.run.shutil, "which", lambda executable: executable)
    monkeypatch.setattr(tests.formal.helpers.process, "execute", execute)
    assert await tests.formal.run.prepare_pristine(ordinary) == expected_status
    commands = [
        ("--no-build", "build"),
        ("-m", "tests.formal.helpers.fixtures.defects"),
    ]
    assert [tuple(call.args[0][1:]) for call in execute.await_args_list] == commands[
        :expected_calls
    ]


@pytest.mark.parametrize(
    ("regular_status", "models_passed", "expected"),
    [(0, True, 0), (7, True, 7), (0, False, 1)],
)
def test_initial_phases_releases_model_slots_only_after_regular_checks(
    monkeypatch: pytest.MonkeyPatch,
    regular_status: int,
    expected: int,
    *,
    models_passed: bool,
) -> None:
    admitted = asyncio.Event()
    model = tests.formal.check.Model(name="check", module="Check", config="Check")

    async def execute(
        *args: object,
        **kwargs: object,
    ) -> tests.formal.helpers.process.Result:
        """Hold the ordinary process until the first model has a slot.

        Returns:
            The case's ordinary exit status and empty diagnostic streams.
        """
        await admitted.wait()
        return tests.formal.helpers.process.Result(
            returncode=regular_status,
            stdout="",
            stderr="",
        )

    async def run_models(
        *args: object,
        semaphore: asyncio.Semaphore,
        **kwargs: object,
    ) -> bool:
        """Check each admission limit while the previous slots remain occupied.

        Args:
            semaphore: The shared gate used by the two phases.

        Returns:
            Whether the model suite passed in this case.
        """
        async with semaphore:
            assert semaphore.locked()
            admitted.set()
            async with semaphore, semaphore:
                assert semaphore.locked()
        return models_passed

    monkeypatch.setenv("PERI_SCRIBE_TLC_JOBS", "3")
    monkeypatch.setattr(tests.formal.check, "selected_models", lambda: (model,))
    monkeypatch.setattr(
        tests.formal.check,
        "toolchain",
        lambda: ("java", pathlib.Path("tla2tools.jar")),
    )
    monkeypatch.setattr(tests.formal.check, "run_models", run_models)
    monkeypatch.setattr(tests.formal.helpers.process, "execute", execute)
    assert (
        asyncio.run(asyncio.wait_for(tests.formal.run.initial_phases(), 5)) == expected
    )


def test_phases_stop_after_failure_before_starting_dependent_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tests.formal.run.shutil, "which", lambda executable: executable)
    failed_status = 7
    check = unittest.mock.Mock(return_value=0)
    monkeypatch.setattr(tests.formal.check, "main", check)
    run = unittest.mock.Mock(
        return_value=tests.formal.helpers.process.Result(
            returncode=failed_status,
            stdout="",
            stderr="",
        ),
    )
    monkeypatch.setattr(tests.formal.helpers.process, "run", run)
    conformance = unittest.mock.Mock()
    monkeypatch.setattr(pytest, "main", conformance)
    assert tests.formal.run.phases() == failed_status
    check.assert_called_once_with(["tla"])
    run.assert_called_once()
    conformance.assert_not_called()


def test_phases_keep_tlc_and_pytest_in_the_controller_outside_asyncio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check = unittest.mock.Mock(return_value=0)
    run = unittest.mock.Mock(
        return_value=tests.formal.helpers.process.Result(
            returncode=0,
            stdout="",
            stderr="",
        ),
    )
    conformance = unittest.mock.Mock(return_value=pytest.ExitCode.OK)
    ordered = unittest.mock.Mock()
    ordered.attach_mock(check, "models")
    ordered.attach_mock(run, "lean")
    ordered.attach_mock(conformance, "conformance")
    monkeypatch.setattr(tests.formal.run.shutil, "which", lambda executable: executable)
    monkeypatch.setattr(tests.formal.check, "main", check)
    monkeypatch.setattr(tests.formal.helpers.process, "run", run)
    monkeypatch.setattr(pytest, "main", conformance)
    assert tests.formal.run.phases() == 0
    assert [call[0] for call in ordered.mock_calls] == [
        "models",
        "lean",
        "conformance",
        "models",
    ]
    assert check.call_args_list == [
        unittest.mock.call(["tla"]),
        unittest.mock.call(["counterexamples"]),
    ]
    assert run.call_args.args[0] == ["lake", "build"]


def test_main_cleans_its_fresh_corpus_after_cancelled_phase(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inherited = tests.formal.helpers.session.directory()
    temporary = unittest.mock.Mock(return_value=contextlib.nullcontext(str(tmp_path)))
    monkeypatch.setattr(
        tests.formal.helpers.session.tempfile,
        "TemporaryDirectory",
        temporary,
    )
    monkeypatch.setattr(
        tests.formal.run,
        "phases",
        unittest.mock.Mock(side_effect=asyncio.CancelledError),
    )
    with pytest.raises(asyncio.CancelledError):
        tests.formal.run.main()
    temporary.assert_called_once()
    assert tests.formal.helpers.session.directory() == inherited
    assert not (tmp_path / "session.json").exists()
