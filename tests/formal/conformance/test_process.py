import asyncio
import errno
import os
import pathlib
import signal
import sys
import unittest.mock

import pytest

import tests.formal.helpers.process
import tests.formal.helpers.process_checks
import tests.helpers.doubles.attribute_overrides


def test_kill_group_waits_for_darwin_to_reap_an_exited_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = tests.formal.helpers.process
    kill = unittest.mock.Mock(
        side_effect=[
            PermissionError(errno.EPERM, "Only exited members remain"),
            ProcessLookupError(errno.ESRCH, "Group reaped"),
        ],
    )
    pause = unittest.mock.Mock()
    monkeypatch.setattr(process.sys, "platform", "darwin")
    monkeypatch.setattr(process.os, "killpg", kill)
    monkeypatch.setattr(process.time, "sleep", pause)

    process.kill_group(123)

    assert kill.call_args_list == [unittest.mock.call(123, signal.SIGKILL)] * 2
    pause.assert_called_once()


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_kill_group_preserves_a_persistent_permission_error(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
) -> None:
    process = tests.formal.helpers.process
    error = PermissionError(errno.EPERM, "Group signal denied")
    kill = unittest.mock.Mock(side_effect=error)
    pause = unittest.mock.Mock()
    monkeypatch.setattr(process.sys, "platform", platform)
    monkeypatch.setattr(process.os, "killpg", kill)
    monkeypatch.setattr(process.time, "sleep", pause)

    with pytest.raises(PermissionError) as raised:
        process.kill_group(123)

    assert raised.value is error
    retries = process.DARWIN_SIGNAL_RETRIES if platform == "darwin" else 0
    assert kill.call_count == retries + 1
    assert pause.call_count == retries


@pytest.mark.parametrize("nested_tools", [True, False])
def test_run_timeout_drains_output_before_waiting_for_exit(
    monkeypatch: pytest.MonkeyPatch,
    *,
    nested_tools: bool,
) -> None:
    process = unittest.mock.create_autospec(asyncio.subprocess.Process, instance=True)
    process.pid = 123
    process.returncode = None
    process.communicate.side_effect = [
        TimeoutError("proof tool deadline"),
        (b"buffered output", b"buffered diagnostics"),
    ]
    process.wait.side_effect = AssertionError("Undrained pipes can block process exit")
    launch = unittest.mock.AsyncMock(return_value=process)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    monkeypatch.setattr(tests.formal.helpers.process, "inherited_group", lambda: None)
    terminate = unittest.mock.Mock()
    monkeypatch.setattr(tests.formal.helpers.process, "kill_group", terminate)
    with pytest.raises(TimeoutError, match="proof tool deadline"):
        tests.formal.helpers.process.run(
            ["proof-tool"],
            can_start_nested_tools=nested_tools,
        )
    launched = launch.await_args
    assert launched is not None
    assert launched.args == (
        (sys.executable, str(tests.formal.helpers.process.LAUNCHER), "proof-tool")
        if nested_tools
        else ("proof-tool",)
    )
    assert launched.kwargs["start_new_session"] is True
    terminate.assert_called_once_with(process.pid)
    assert process.communicate.await_args_list == [
        unittest.mock.call(b""),
        unittest.mock.call(),
    ]


@pytest.mark.asyncio
async def test_execute_interrupts_graceful_tools_before_forcing_the_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = unittest.mock.create_autospec(asyncio.subprocess.Process, instance=True)
    process.pid = 123
    process.communicate.side_effect = [TimeoutError("deadline"), (b"", b"")]
    kill = unittest.mock.Mock()
    launch = unittest.mock.AsyncMock(return_value=process)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    monkeypatch.setattr(tests.formal.helpers.process, "inherited_group", lambda: None)
    monkeypatch.setattr(os, "killpg", kill)
    with pytest.raises(TimeoutError, match="deadline"):
        await tests.formal.helpers.process.execute(
            ["regular-tool"],
            standard_input="",
            cwd=None,
            maximum_seconds=60,
            can_start_nested_tools=False,
            interrupt_grace_seconds=1,
        )
    assert kill.call_args_list == [
        unittest.mock.call(process.pid, signal.SIGINT),
        unittest.mock.call(process.pid, signal.SIGKILL),
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


def test_attribute_overrides_restore_inherited_lookup_after_an_exception() -> None:
    class Base:
        """Expose an inherited descriptor without a child namespace entry."""

        @staticmethod
        def value() -> str:
            """Return the original descriptor's value."""
            return "original"

    class Child(Base):
        """Keep the original inheritance relationship after both scopes close."""

    def fail_inside_scope() -> None:
        """Unwind the outer override after the nested value has been restored.

        Raises:
            LookupError: The fixture failure that forces the outer scope to unwind.
        """
        with tests.helpers.doubles.attribute_overrides.AttributeOverrides() as outer:
            outer.setattr(Child, "value", staticmethod(lambda: "outer"))
            with (
                tests.helpers.doubles.attribute_overrides.AttributeOverrides() as inner
            ):
                inner.setattr(Child, "value", staticmethod(lambda: "inner"))
                assert Child.value() == "inner"
            assert Child.value() == "outer"
            message = "scope failed"
            raise LookupError(message)

    with pytest.raises(LookupError, match="scope failed"):
        fail_inside_scope()
    assert "value" not in vars(Child)
    assert Child.value() == "original"
