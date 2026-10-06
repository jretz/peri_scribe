import asyncio
import contextlib
import pathlib
import unittest.mock

import pytest

import tests.formal.check
import tests.formal.helpers.process
import tests.formal.helpers.session
import tests.formal.run


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
