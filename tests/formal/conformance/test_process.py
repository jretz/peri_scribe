import asyncio
import contextlib
import errno
import os
import pathlib
import signal
import sys
import typing
import unittest.mock

import pytest

import tests.formal.helpers.process
import tests.formal.helpers.process_checks
import tests.helpers.doubles.attribute_overrides


@pytest.mark.asyncio
@pytest.mark.parametrize("nested_tools", [True, False])
async def test_execute_timeout_preserves_bounded_diagnostics_from_a_real_child(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    nested_tools: bool,
) -> None:
    adapter = tests.formal.helpers.process
    monkeypatch.delenv(adapter.GROUP_VARIABLE, raising=False)
    monkeypatch.setattr(adapter, "MAXIMUM_TIMEOUT_DIAGNOSTIC_BYTES", 128)
    marker = tmp_path / "output-written"
    original = typing.cast(
        "tests.formal.helpers.process_checks.Launch",
        asyncio.create_subprocess_exec,
    )
    children: list[asyncio.subprocess.Process] = []

    async def launch(*args: str, **kwargs: object) -> asyncio.subprocess.Process:
        """Begin the deadline only after both real pipes contain the diagnostics.

        Args:
            args: The adapter's executable and arguments.
            kwargs: Its unchanged process ownership and pipe options.

        Returns:
            The real child handle after its output handshake.
        """
        child = await original(*args, **kwargs)
        children.append(child)
        await asyncio.to_thread(
            tests.formal.helpers.process_checks.wait_until,
            marker.exists,
        )
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    command = [
        sys.executable,
        "-c",
        (
            "import pathlib, signal, sys\n"
            "for stream, name in ((sys.stdout, 'stdout'), (sys.stderr, 'stderr')):\n"
            "    stream.buffer.write(('earliest ' + name).encode() + b'.' * 256\n"
            "                        + b'\\xfflast ' + name.encode()\n"
            "                        + b' diagnostic\\n')\n"
            "    stream.buffer.flush()\n"
            "pathlib.Path(sys.argv[1]).touch()\n"
            "signal.pause()\n"
        ),
        str(marker),
    ]
    try:
        with pytest.raises(TimeoutError) as raised:
            async with asyncio.timeout(
                tests.formal.helpers.process_checks.GUARD_SECONDS,
            ):
                await adapter.execute(
                    command,
                    standard_input="",
                    cwd=None,
                    maximum_seconds=0,
                    can_start_nested_tools=nested_tools,
                )
        diagnostic = str(raised.value)
        assert "last stdout diagnostic" in diagnostic
        assert "last stderr diagnostic" in diagnostic
        assert "earliest stdout" not in diagnostic
        assert "earliest stderr" not in diagnostic
        maximum_message_length = 512
        assert len(diagnostic) < maximum_message_length
        assert len(children) == 1
        assert children[0].returncode is not None
    finally:
        for child in children:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(child.pid, signal.SIGKILL)
            await child.wait()


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
    terminated = asyncio.Event()

    async def communicate(standard_input: bytes) -> tuple[bytes, bytes]:
        """Keep the original pipe reader active until cleanup terminates its owner.

        Returns:
            Both buffered streams after the process exits.
        """
        assert standard_input == b""
        await terminated.wait()
        return b"buffered output", b"buffered diagnostics"

    process.communicate.side_effect = communicate
    process.wait.side_effect = AssertionError("Undrained pipes can block process exit")
    launch = unittest.mock.AsyncMock(return_value=process)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    monkeypatch.setattr(tests.formal.helpers.process, "inherited_group", lambda: None)
    terminate = unittest.mock.Mock(
        side_effect=lambda group: terminated.set() if group == process.pid else None,
    )
    monkeypatch.setattr(tests.formal.helpers.process, "kill_group", terminate)
    with pytest.raises(TimeoutError, match="exceeded 0 seconds") as raised:
        tests.formal.helpers.process.run(
            ["proof-tool"],
            timeout=0,
            can_start_nested_tools=nested_tools,
        )
    assert "buffered output" in str(raised.value)
    assert "buffered diagnostics" in str(raised.value)
    launched = launch.await_args
    assert launched is not None
    assert launched.args == (
        (sys.executable, str(tests.formal.helpers.process.LAUNCHER), "proof-tool")
        if nested_tools
        else ("proof-tool",)
    )
    assert launched.kwargs["start_new_session"] is True
    terminate.assert_called_once_with(process.pid)
    process.communicate.assert_awaited_once_with(b"")


@pytest.mark.asyncio
async def test_execute_interrupts_graceful_tools_before_forcing_the_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = unittest.mock.create_autospec(asyncio.subprocess.Process, instance=True)
    process.pid = 123
    interrupted = asyncio.Event()

    async def communicate(standard_input: bytes) -> tuple[bytes, bytes]:
        """Finish the pending reader only after the tool receives its interrupt.

        Returns:
            The gracefully closed streams.
        """
        assert standard_input == b""
        await interrupted.wait()
        return b"", b""

    process.communicate.side_effect = communicate
    kill = unittest.mock.Mock(
        side_effect=lambda group, requested: (
            interrupted.set()
            if (group, requested) == (process.pid, signal.SIGINT)
            else None
        ),
    )
    launch = unittest.mock.AsyncMock(return_value=process)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    monkeypatch.setattr(tests.formal.helpers.process, "inherited_group", lambda: None)
    monkeypatch.setattr(os, "killpg", kill)
    with pytest.raises(TimeoutError, match="exceeded 0 seconds"):
        await tests.formal.helpers.process.execute(
            ["regular-tool"],
            standard_input="",
            cwd=None,
            maximum_seconds=0,
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
