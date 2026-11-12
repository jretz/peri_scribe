"""Run local proof tools with bounded waits and without a command shell.

Cancelling a proof job must also stop the tools it started. Otherwise a nested process
can keep running or hold an output pipe open after its caller has failed.

Design notes:
[Verification evidence and execution](../../../docs/algorithms/verification-tooling.md).
"""

import asyncio
import contextlib
import dataclasses
import errno
import os
import pathlib
import signal
import sys
import time


GROUP_VARIABLE = "PERI_SCRIBE_FORMAL_PROCESS_GROUP"
LAUNCHER = pathlib.Path(__file__).with_name("process_launcher.py").resolve()
DARWIN_SIGNAL_RETRIES = 10
MAXIMUM_TIMEOUT_DIAGNOSTIC_BYTES = 8192


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

    Raises:
        PermissionError: If the group remains unsignalable after cleanup retries.
    """
    for attempt in range(DARWIN_SIGNAL_RETRIES + 1):
        try:
            os.killpg(group, signal.SIGKILL)
        except ProcessLookupError:
            return
        except PermissionError as error:
            if (
                sys.platform != "darwin"
                or error.errno != errno.EPERM
                or attempt == DARWIN_SIGNAL_RETRIES
            ):
                raise
            # XNU can retain the group briefly after its last member exits.
            time.sleep(0.01)
        else:
            return


async def group_closed(group: int) -> None:
    """Wait for physical group absence before reusing independent native capacity.

    The operating system has ten seconds to release the terminated group.

    Args:
        group: The group whose owning command has completed and been reaped.

    Raises:
        PermissionError: If the group cannot be inspected outside Darwin's exit race.
    """
    async with asyncio.timeout(10):
        while True:
            try:
                os.killpg(group, 0)
            except ProcessLookupError:
                return
            except PermissionError as error:
                if sys.platform != "darwin" or error.errno != errno.EPERM:
                    raise
            await asyncio.sleep(0.01)


async def terminate(
    launch: asyncio.Task[asyncio.subprocess.Process],
    group: int | None,
    *,
    interrupt_grace_seconds: float,
    wait_for_group_exit: bool = False,
    drain: asyncio.Task[tuple[bytes, bytes]] | None = None,
) -> None:
    """Wait for the process handle so the whole failed proof job can be terminated.

    A nested tool shares its enclosing pytest job's process group. Terminating that
    group stops the job and its tools; only the outer caller survives to propagate the
    exception that triggered cleanup. A nonzero tool exit status by itself does not
    trigger termination.

    Args:
        launch: A shielded launch that may still be handing back its process handle.
        group: An inherited job group, or None for a newly isolated job.
        interrupt_grace_seconds: Time for an independently owned tool to clean up
            after SIGINT before terminating its group.
        wait_for_group_exit: Require physical group absence before returning capacity.
        drain: The existing pipe reader, when execution has already started it.
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
    # Pipe-holding descendants must exit before transports can report completion.
    if drain is None:
        drain = asyncio.create_task(process.communicate())
    if group is None and interrupt_grace_seconds > 0:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGINT)
        await asyncio.wait({drain}, timeout=interrupt_grace_seconds)
    kill_group(process.pid if group is None else group)
    await drain
    if wait_for_group_exit and group is None:
        await group_closed(process.pid)


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
    can_start_nested_tools: bool = True,
    interrupt_grace_seconds: float = 0,
    wait_for_group_exit: bool = False,
) -> Result:
    """Terminate proof tools that exceed their caller's explicit time budget.

    Args:
        command: An executable and arguments passed directly to the operating system.
        standard_input: Text supplied through standard input.
        cwd: The tool's working directory.
        maximum_seconds: Maximum execution time in seconds.
        can_start_nested_tools: Whether child proof tools need an inherited group.
        interrupt_grace_seconds: Optional grace period for a tool's SIGINT handler.
        wait_for_group_exit: Require physical group absence before reusing capacity.

    Returns:
        The exit status and both diagnostic streams.

    Raises:
        TimeoutError: If execution exceeds the budget, with bounded tool diagnostics.
        ValueError: If group-exit admission is requested from an inherited owner.
    """
    group = inherited_group()
    if wait_for_group_exit and group is not None:
        message = "Only independently owned commands can release group capacity"
        raise ValueError(message)
    arguments = (
        [sys.executable, str(LAUNCHER), *command]
        if group is None and can_start_nested_tools
        else command
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
    drain: asyncio.Task[tuple[bytes, bytes]] | None = None
    try:
        process = await asyncio.shield(launch)
        drain = asyncio.create_task(process.communicate(standard_input.encode()))
        stdout, stderr = await asyncio.wait_for(
            asyncio.shield(drain),
            timeout=maximum_seconds,
        )
    except BaseException as error:
        cleanup = asyncio.create_task(
            terminate(
                launch,
                group,
                interrupt_grace_seconds=interrupt_grace_seconds,
                wait_for_group_exit=wait_for_group_exit,
                drain=drain,
            ),
        )
        await finish(cleanup)
        if isinstance(error, TimeoutError) and drain is not None:
            stdout, stderr = drain.result()
            message = f"Command exceeded {maximum_seconds:g} seconds"
            for name, output in (("stdout", stdout), ("stderr", stderr)):
                excerpt = output[-MAXIMUM_TIMEOUT_DIAGNOSTIC_BYTES:]
                if excerpt:
                    message += f"\n{name}:\n{excerpt.decode(errors='replace')}"
            raise TimeoutError(message) from error
        raise
    if group is None:
        kill_group(process.pid)
        if wait_for_group_exit:
            cleanup = asyncio.create_task(group_closed(process.pid))
            try:
                await asyncio.shield(cleanup)
            except BaseException:
                await finish(cleanup)
                raise
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
    can_start_nested_tools: bool = True,
) -> Result:
    """Let synchronous checks share the same isolated process adapter.

    Args:
        command: An executable and arguments passed directly to the operating system.
        standard_input: Text supplied through standard input.
        cwd: The tool's working directory.
        timeout: Maximum execution time in seconds.
        can_start_nested_tools: Whether child proof tools need an inherited group.

    Returns:
        The exit status and both diagnostic streams.
    """
    return asyncio.run(
        execute(
            command,
            standard_input=standard_input,
            cwd=cwd,
            maximum_seconds=timeout,
            can_start_nested_tools=can_start_nested_tools,
        ),
    )
