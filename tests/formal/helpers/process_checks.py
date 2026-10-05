"""Keep real descendant processes observable until their owner cleans up."""

import asyncio
import collections.abc
import contextlib
import dataclasses
import fcntl
import os
import pathlib
import signal
import sys
import time
import unittest.mock

import tests.formal.helpers.process


GUARD_SECONDS = 30
DIRECTORY = pathlib.Path(__file__).resolve().parents[3]
type Launch = collections.abc.Callable[
    ...,
    collections.abc.Awaitable[asyncio.subprocess.Process],
]


@dataclasses.dataclass(kw_only=True)
class Probe:
    """Expose admission and live descendants independently of elapsed wall time."""

    directory: pathlib.Path
    original: Launch
    mode: str
    launched: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    release: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    processes: list[asyncio.subprocess.Process] = dataclasses.field(
        default_factory=list,
    )

    def command(self) -> list[str]:
        """Keep the probe in a fresh interpreter like a nested conformance job.

        Returns:
            The worker command for this process topology.
        """
        return command(self.mode, self.directory)

    async def launch(
        self,
        *args: str,
        **kwargs: object,
    ) -> asyncio.subprocess.Process:
        """Exclude interpreter startup from the deadline being exercised.

        Args:
            args: The adapter's unchanged executable and arguments.
            kwargs: Its unchanged process ownership and pipe options.

        Returns:
            The real handle, after the descendant holds its observable resource.
        """
        process = await self.original(*args, **kwargs)
        self.processes.append(process)
        await ready(self.directory, "leaf")
        if self.mode == "exited":
            await asyncio.to_thread(wait_until, lambda: process.returncode is not None)
            assert process.returncode == 0
        self.launched.set()
        await self.release.wait()
        return process

    async def close(self, task: asyncio.Task[object]) -> None:
        """A failed regression must not leave its deliberately blocked children alive.

        Args:
            task: The adapter invocation, including any pending cleanup.
        """
        self.release.set()
        for process in self.processes:
            with contextlib.suppress(ProcessLookupError):
                if process.pid == os.getpgid(process.pid) == os.getsid(process.pid):
                    os.killpg(process.pid, signal.SIGKILL)
                elif process.returncode is None:
                    process.kill()
        for name in ("leaf", "parent"):
            identifier = self.directory / f"{name}.pid"
            if identifier.exists() and not released(self.directory, name):
                process = int(identifier.read_text())
                with contextlib.suppress(ProcessLookupError):
                    os.kill(process, signal.SIGKILL)
        async with asyncio.timeout(GUARD_SECONDS):
            await asyncio.gather(task, return_exceptions=True)

    async def assert_released(self) -> None:
        """Require resource release after the kernel finishes process teardown."""
        await asyncio.to_thread(
            wait_until,
            lambda: all(released(self.directory, name) for name in ("parent", "leaf")),
        )


def command(mode: str, directory: pathlib.Path) -> list[str]:
    """Use the same Python runtime and imports as the calling formal adapter.

    Args:
        mode: The descendant or parent lifetime to exercise.
        directory: Private readiness and resource ownership files.

    Returns:
        Direct worker arguments without a command shell.
    """
    return [
        sys.executable,
        "-m",
        "tests.formal.helpers.process_checks",
        mode,
        str(directory),
    ]


async def ready(directory: pathlib.Path, name: str) -> None:
    """Wait for an explicit resource-ownership handshake with a deadlock guard.

    Args:
        directory: The probe's private files.
        name: The process whose admission must be observed.
    """
    await asyncio.to_thread(wait_until, (directory / f"{name}.pid").exists)


def wait_until(observed: collections.abc.Callable[[], bool]) -> None:
    """Bound cross-process file handshakes without delaying the event loop.

    Args:
        observed: The explicit admission or process-exit condition.

    Raises:
        TimeoutError: The worker never reached its required boundary.
    """
    deadline = time.monotonic() + GUARD_SECONDS
    while not observed():
        if time.monotonic() >= deadline:
            message = "process probe did not reach its required boundary"
            raise TimeoutError(message)
        time.sleep(0.01)


def released(directory: pathlib.Path, name: str) -> bool:
    """Observe resource release without confusing a dead process with a zombie.

    Args:
        directory: The probe's private files.
        name: The process that owns the lock while it remains alive.

    Returns:
        Whether that process no longer owns its exclusive lock.
    """
    with (directory / f"{name}.lock").open("ab") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
    return True


async def parent(mode: str, directory: pathlib.Path) -> None:
    """Leave a real pipe-holding descendant after the selected parent boundary.

    Args:
        mode: Whether the parent stays alive or exits before cleanup starts.
        directory: The probe's private files.
    """
    child = await asyncio.create_subprocess_exec(*command("leaf", directory))
    await ready(directory, "leaf")
    if mode == "exited":
        os._exit(0)
    await child.wait()


def main() -> None:
    """Make process resources and inherited pipes outlive cancellation until killed."""
    mode, raw_directory = sys.argv[1:]
    directory = pathlib.Path(raw_directory)
    name = "leaf" if mode == "leaf" else "parent"
    with (directory / f"{name}.lock").open("ab") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        pending = directory / f"{name}.pending"
        pending.write_text(str(os.getpid()))
        pending.replace(directory / f"{name}.pid")
        if mode == "leaf":
            print("descendant output", flush=True)
            while True:
                signal.pause()
        elif mode.startswith("nested"):
            probe = Probe(
                directory=directory,
                original=asyncio.create_subprocess_exec,
                mode="leaf",
            )
            probe.release.set()
            with unittest.mock.patch.object(
                asyncio,
                "create_subprocess_exec",
                probe.launch,
            ):
                tests.formal.helpers.process.run(
                    command("leaf", directory),
                    timeout=0 if mode == "nested-timeout" else GUARD_SECONDS,
                )
        else:
            asyncio.run(parent(mode, directory))


if __name__ == "__main__":
    main()
