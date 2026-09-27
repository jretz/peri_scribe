"""Run local proof tools with bounded waits and without a command shell."""

import asyncio
import dataclasses
import pathlib


@dataclasses.dataclass(frozen=True, kw_only=True)
class Result:
    """Preserve the tool diagnostics required to distinguish failure from a proof."""

    returncode: int
    stdout: str
    stderr: str


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
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(standard_input.encode()),
            timeout=maximum_seconds,
        )
    except BaseException:
        if process.returncode is None:
            process.kill()
        # Undrained output can prevent pipe transports from reporting process exit.
        await process.communicate()
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
