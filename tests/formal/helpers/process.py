"""Run local proof tools with bounded waits and without a command shell.

Design notes:
[Verification evidence and execution](../../../docs/algorithms/verification-tooling.md).
"""

import asyncio
import contextlib
import dataclasses
import os
import pathlib
import signal
import sys


GROUP_VARIABLE = "PERI_SCRIBE_FORMAL_PROCESS_GROUP"
LAUNCHER = pathlib.Path(__file__).with_name("process_launcher.py").resolve()


@dataclasses.dataclass(frozen=True, kw_only=True)
class Result:
    """Preserve the tool diagnostics required to distinguish failure from a proof."""

    returncode: int
    stdout: str
    stderr: str


def inherited_group() -> int | None:
    """Recognize only the private session established by an enclosing proof job.

    Returns:
        The enclosing job's group, or None when this caller must isolate a new job.
    """
    value = os.environ.get(GROUP_VARIABLE, "")
    try:
        group = int(value)
    except ValueError:
        return None
    if group > 0 and group == os.getpgrp() == os.getsid(0):
        return group
    return None


def kill_group(group: int) -> None:
    """Include descendants whose immediate parent has already exited.

    Args:
        group: The private process group owned by this proof job.
    """
    with contextlib.suppress(ProcessLookupError):
        os.killpg(group, signal.SIGKILL)


async def terminate(
    launch: asyncio.Task[asyncio.subprocess.Process],
    group: int | None,
) -> None:
    """Finish admission before terminating the entire failed proof job.

    A nested tool failure aborts its enclosing pytest job as well as its tools.
    Only the outer caller survives to propagate its cancellation or timeout.

    Args:
        launch: A shielded launch that may still be handing back its process handle.
        group: An inherited job group, or None for a newly isolated job.
    """
    result = (await asyncio.gather(launch, return_exceptions=True))[0]
    if isinstance(result, BaseException):
        return
    process = result
    if group is not None:
        with contextlib.suppress(OSError, ValueError):
            print(
                "Formal subprocess failed during execution; terminating its proof job.",
                file=sys.stderr,
                flush=True,
            )
    kill_group(process.pid if group is None else group)
    # Pipe-holding descendants must exit before transports can report completion.
    await process.communicate()


async def finish(cleanup: asyncio.Task[None]) -> None:
    """Keep repeated cancellation from abandoning owned processes or output pipes.

    Args:
        cleanup: The single task responsible for termination and reaping.
    """
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            continue
    cleanup.result()


async def execute(
    command: list[str],
    *,
    standard_input: str,
    cwd: pathlib.Path | None,
    maximum_seconds: float,
) -> Result:
    """Terminate proof tools that exceed their caller's explicit time budget.

    Args:
        command: An executable and arguments passed directly to the operating system.
        standard_input: Text supplied through standard input.
        cwd: The tool's working directory.
        maximum_seconds: Maximum execution time in seconds.

    Returns:
        The exit status and both diagnostic streams.
    """
    group = inherited_group()
    arguments = (
        command if group is not None else [sys.executable, str(LAUNCHER), *command]
    )
    launch = asyncio.create_task(
        asyncio.create_subprocess_exec(
            *arguments,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            start_new_session=group is None,
        ),
    )
    try:
        process = await asyncio.shield(launch)
        stdout, stderr = await asyncio.wait_for(
            process.communicate(standard_input.encode()),
            timeout=maximum_seconds,
        )
    except BaseException:
        await finish(asyncio.create_task(terminate(launch, group)))
        raise
    if group is None:
        kill_group(process.pid)
    assert process.returncode is not None
    return Result(
        returncode=process.returncode,
        stdout=stdout.decode(),
        stderr=stderr.decode(),
    )


def run(
    command: list[str],
    *,
    standard_input: str = "",
    cwd: pathlib.Path | None = None,
    timeout: float = 60,
) -> Result:
    """Let synchronous checks share the same isolated process adapter.

    Args:
        command: An executable and arguments passed directly to the operating system.
        standard_input: Text supplied through standard input.
        cwd: The tool's working directory.
        timeout: Maximum execution time in seconds.

    Returns:
        The exit status and both diagnostic streams.
    """
    return asyncio.run(
        execute(
            command,
            standard_input=standard_input,
            cwd=cwd,
            maximum_seconds=timeout,
        ),
    )
