import asyncio
import os
import pathlib
import signal
import sys

import pytest

import tests.formal.check
import tests.formal.helpers.process_checks
import tests.formal.helpers.tlc_worker


DEADLINE_SECONDS = 20


def arguments(
    module: str,
    config: str,
    directory: pathlib.Path,
) -> list[str]:
    """Use the normal checker arguments with a fixed fingerprint for graph parity.

    Args:
        module: The model's source module.
        config: Its exact registered configuration.
        directory: The private graph and state metadata directory.

    Returns:
        The original TLC CLI arguments for the requested check.
    """
    return [
        "-workers",
        "1",
        "-seed",
        "1",
        "-fp",
        "0",
        "-lncheck",
        "final",
        "-metadir",
        str(directory / "metadata"),
        "-dump",
        "dot,actionlabels",
        str(directory / "graph.dot"),
        "-config",
        f"{config}.cfg",
        f"{module}.tla",
    ]


async def cancel_when[Result](
    task: asyncio.Task[Result],
    marker: pathlib.Path,
) -> None:
    """Deliver cancellation only after the worker reaches the observed boundary.

    Args:
        task: The owned worker operation.
        marker: The file whose creation identifies the boundary.
    """
    try:
        await asyncio.to_thread(
            tests.formal.helpers.process_checks.wait_until,
            marker.exists,
        )
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_real_worker_reuses_after_rejection_and_restarts_after_cancellation(
    tmp_path: pathlib.Path,
) -> None:
    java, jar = tests.formal.check.toolchain()
    transport = tests.formal.helpers.tlc_worker
    classes = await transport.compile_worker(java, tmp_path)
    worker = transport.Worker(java, jar, classes, tests.formal.check.DIRECTORY)

    async def run(module: str, config: str, directory: pathlib.Path) -> int:
        """Run a real model and compare its private diagnostic files to the reply.

        Returns:
            TLC's original exit status.
        """
        await asyncio.to_thread(directory.mkdir)
        result = await worker.execute(
            arguments(module, config, directory),
            directory,
            maximum_seconds=DEADLINE_SECONDS,
        )
        assert result.stdout == (directory / transport.OUTPUT).read_text()
        assert result.stderr == (directory / transport.ERRORS).read_text()
        return result.returncode

    try:
        first = tmp_path / "first-é\n\t"
        assert await run("StaticDownload", "StaticDownload", first) == 0
        connection = worker.connection
        assert connection is not None
        original = connection.launch.result()

        rejected = tmp_path / "rejected"
        assert (
            await run("GeographyPublication", "GeographyPairExpected", rejected)
            == tests.formal.check.INVARIANT_VIOLATION
        )
        assert (
            "Invariant PairAlwaysMatches is violated."
            in (rejected / transport.OUTPUT).read_text()
        )
        assert worker.connection is connection

        interrupted = tmp_path / "interrupted"
        active = asyncio.create_task(
            run("PipelineComposition", "PipelineComposition", interrupted),
        )
        await cancel_when(active, interrupted / transport.OUTPUT)
        assert worker.connection is None
        assert original.returncode is not None
        with pytest.raises(ProcessLookupError):
            os.getpgid(original.pid)

        timed_out = tmp_path / "timed-out"
        timed_out.mkdir()
        with pytest.raises(TimeoutError, match="timed out"):
            await worker.execute(
                arguments("StaticDownload", "StaticDownload", timed_out),
                timed_out,
                maximum_seconds=0,
            )
        assert worker.connection is None

        restarted = tmp_path / "restarted"
        assert await run("StaticDownload", "StaticDownload", restarted) == 0
        assert (first / "graph.dot").read_bytes() == (
            restarted / "graph.dot"
        ).read_bytes()
        replacement = worker.connection
        assert replacement is not None
        assert replacement is not connection
        await worker.close()
        assert replacement.launch.result().returncode == 0
        assert worker.connection is None
    finally:
        await worker.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["status", "timeout", "cancel"])
async def test_worker_reaps_after_failed_graceful_shutdown(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    transport = tests.formal.helpers.tlc_worker
    worker = transport.Worker("java", tmp_path / "tools.jar", tmp_path, tmp_path)
    received_eof = tmp_path / "received-eof"
    worker.command = [
        sys.executable,
        "-c",
        (
            "import pathlib, signal, sys\n"
            "input()\n"
            "print('1 0', flush=True)\n"
            "sys.stdin.read()\n"
            "print('shutdown diagnostic', file=sys.stderr, flush=True)\n"
            "pathlib.Path(sys.argv[1]).touch()\n"
            "if sys.argv[2] == 'status':\n"
            "    raise SystemExit(7)\n"
            "signal.pause()\n"
        ),
        str(received_eof),
        failure,
    ]
    (tmp_path / transport.OUTPUT).touch()
    (tmp_path / transport.ERRORS).touch()
    try:
        await worker.execute(["case.tla"], tmp_path, maximum_seconds=DEADLINE_SECONDS)
        connection = worker.connection
        assert connection is not None
        owned = connection.launch.result()
        if failure == "cancel":
            await cancel_when(asyncio.create_task(worker.close()), received_eof)
        else:
            if failure == "timeout":
                monkeypatch.setattr(transport, "CLOSE_SECONDS", 0.5)
            with pytest.raises(OSError, match="shutdown diagnostic") as raised:
                await worker.close()
            expected = "timed out" if failure == "timeout" else "status 7"
            assert expected in str(raised.value)
        assert received_eof.exists()
        assert owned.returncode == (7 if failure == "status" else -signal.SIGKILL)
        assert worker.connection is None
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_worker_rejects_a_reply_for_another_request(
    tmp_path: pathlib.Path,
) -> None:
    transport = tests.formal.helpers.tlc_worker
    worker = transport.Worker("java", tmp_path / "tools.jar", tmp_path, tmp_path)
    worker.command = [
        sys.executable,
        "-c",
        (
            "import sys\n"
            "input()\n"
            "print('transport diagnostic', file=sys.stderr, flush=True)\n"
            "print('0 0', flush=True)\n"
        ),
    ]
    (tmp_path / transport.OUTPUT).write_text("stale model success")
    (tmp_path / transport.ERRORS).touch()
    try:
        with pytest.raises(OSError, match="transport diagnostic"):
            await worker.execute(
                ["case.tla"],
                tmp_path,
                maximum_seconds=DEADLINE_SECONDS,
            )
        assert worker.connection is None
    finally:
        await worker.close()
