import asyncio
import os
import pathlib
import signal
import sys
import unittest.mock

import pytest

import tests.formal.helpers.process
import tests.formal.helpers.process_checks


def test_run_timeout_drains_output_before_waiting_for_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = unittest.mock.create_autospec(asyncio.subprocess.Process, instance=True)
    process.pid = 123
    process.returncode = None
    process.communicate.side_effect = [
        TimeoutError("proof tool deadline"),
        (b"buffered output", b"buffered diagnostics"),
    ]
    process.wait.side_effect = AssertionError("Undrained pipes can block process exit")
    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        unittest.mock.AsyncMock(return_value=process),
    )
    monkeypatch.setattr(tests.formal.helpers.process, "inherited_group", lambda: None)
    terminate = unittest.mock.Mock()
    monkeypatch.setattr(tests.formal.helpers.process, "kill_group", terminate)
    with pytest.raises(TimeoutError, match="proof tool deadline"):
        tests.formal.helpers.process.run(["proof-tool"])
    terminate.assert_called_once_with(process.pid)
    assert process.communicate.await_args_list == [
        unittest.mock.call(b""),
        unittest.mock.call(),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["parent", "nested", "exited"])
@pytest.mark.parametrize("failure", ["cancel", "timeout", "launch-cancel"])
async def test_execute_releases_descendants_after_failed_job(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    failure: str,
) -> None:
    monkeypatch.delenv(tests.formal.helpers.process.GROUP_VARIABLE, raising=False)
    probe = tests.formal.helpers.process_checks.Probe(
        directory=tmp_path,
        original=asyncio.create_subprocess_exec,
        mode=mode,
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", probe.launch)
    if failure != "launch-cancel":
        probe.release.set()
    task = asyncio.create_task(
        tests.formal.helpers.process.execute(
            probe.command(),
            standard_input="",
            cwd=tests.formal.helpers.process_checks.DIRECTORY,
            maximum_seconds=0 if failure == "timeout" else 60,
        ),
    )
    try:
        async with asyncio.timeout(tests.formal.helpers.process_checks.GUARD_SECONDS):
            await probe.launched.wait()
        if failure != "timeout":
            task.cancel()
        if failure == "launch-cancel":
            await asyncio.sleep(0)
            task.cancel()
            assert not task.done()
            probe.release.set()
        done, _ = await asyncio.wait(
            {task},
            timeout=tests.formal.helpers.process_checks.GUARD_SECONDS,
        )
        assert task in done, "owned descendants kept process cleanup blocked"
        with pytest.raises(
            TimeoutError if failure == "timeout" else asyncio.CancelledError,
        ):
            task.result()
        await probe.assert_released()
    finally:
        await probe.close(task)


@pytest.mark.asyncio
async def test_execute_nested_timeout_aborts_the_failed_job(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(tests.formal.helpers.process.GROUP_VARIABLE, raising=False)
    probe = tests.formal.helpers.process_checks.Probe(
        directory=tmp_path,
        original=asyncio.create_subprocess_exec,
        mode="nested-timeout",
    )
    task = asyncio.create_task(
        tests.formal.helpers.process.execute(
            probe.command(),
            standard_input="",
            cwd=tests.formal.helpers.process_checks.DIRECTORY,
            maximum_seconds=tests.formal.helpers.process_checks.GUARD_SECONDS,
        ),
    )
    try:
        result = await task
        assert result.returncode == -signal.SIGKILL
        assert "terminating its proof job" in result.stderr
        await probe.assert_released()
    finally:
        await probe.close(task)


def test_run_ignores_a_stale_inherited_process_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        tests.formal.helpers.process.GROUP_VARIABLE,
        str(os.getpgrp() + 1),
    )
    result = tests.formal.helpers.process.run([
        sys.executable,
        "-c",
        "import os, sys; print(os.getpgrp()); print('diagnostic', file=sys.stderr)",
    ])
    assert result.returncode == 0
    assert int(result.stdout) != os.getpgrp()
    assert result.stderr == "diagnostic\n"


@pytest.mark.parametrize("status", [7, -signal.SIGPIPE])
def test_run_preserves_the_child_exit_status(
    status: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(tests.formal.helpers.process.GROUP_VARIABLE, raising=False)
    result = tests.formal.helpers.process.run([
        sys.executable,
        "-c",
        (
            "import os, signal, sys\n"
            "status = int(sys.argv[1])\n"
            "if status < 0:\n"
            "    signal.signal(-status, signal.SIG_DFL)\n"
            "    os.kill(os.getpid(), -status)\n"
            "sys.exit(status)\n"
        ),
        str(status),
    ])
    assert result.returncode == status
