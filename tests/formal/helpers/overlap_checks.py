"""Control coordinator prerequisites while retaining real admission and cleanup."""

from __future__ import annotations

import asyncio
import collections.abc
import contextlib
import dataclasses
import json
import os
import pathlib
import sys
import time
import unittest.mock

import pytest

import tests.formal.check
import tests.formal.helpers.fixtures.defects
import tests.formal.helpers.overlap
import tests.formal.helpers.process
import tests.formal.helpers.session
import tests.helpers.ordinary_lanes


GUARD_SECONDS = 15
EXPECTED_FULL_WORKERS = 5


@dataclasses.dataclass(kw_only=True)
class Events:
    """Expose every independent prerequisite before allowing the next phase."""

    models: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    lean: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    pristine: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    regular: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    formal: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    models_started: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    lean_started: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    pristine_started: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    regular_started: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    formal_started: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    formal_cancelled: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    regular_status: int = 0
    formal_status: int = 0
    formal_arguments: list[str] = dataclasses.field(default_factory=list)

    def ready(self) -> None:
        """Release proof replies for a control focused on another boundary."""
        self.models.set()
        self.lean.set()
        self.pristine.set()


@dataclasses.dataclass(frozen=True, kw_only=True)
class Controlled:
    """Keep the coordinator, handshakes and editable source under one owner."""

    coordinator: tests.formal.helpers.overlap.Coordinator
    events: Events
    source: pathlib.Path


@contextlib.contextmanager
def controlled(directory: pathlib.Path) -> collections.abc.Generator[Controlled]:
    """Replace expensive phase commands while keeping coordinator decisions real.

    Args:
        directory: Private source, audit and admission storage.

    Yields:
        The actual coordinator with separately controlled native replies.
    """
    source = directory / "owned-source.py"
    source.write_text("value = 1\n")
    events = Events()
    coverage = directory / "coverage"
    coverage.mkdir()
    (coverage / "session.json").write_text(
        json.dumps({"directory": str(coverage), "runId": "current"}),
    )

    async def models(*arguments: object, **keywords: object) -> bool:
        """Signal model execution before allowing its native reply.

        Args:
            arguments: Original positional model-runner arguments.
            keywords: Original model-runner options.

        Returns:
            A successful reply after the model boundary is released.
        """
        del arguments, keywords
        events.models_started.set()
        await events.models.wait()
        return True

    async def execute(
        command: list[str],
        **keywords: object,
    ) -> tests.formal.helpers.process.Result:
        """Keep Lean and pristine work as independent prerequisite boundaries.

        Args:
            command: The unchanged native proof command.
            keywords: Original timeout and ownership options.

        Returns:
            A native-shaped success after its explicit boundary is released.
        """
        del keywords
        if command == ["controlled-lake", "build"]:
            events.lean_started.set()
            await events.lean.wait()
        else:
            assert command[-1] == "tests.formal.helpers.fixtures.defects"
            events.pristine_started.set()
            await events.pristine.wait()
        return tests.formal.helpers.process.Result(returncode=0, stdout="", stderr="")

    async def native(
        coordinator: tests.formal.helpers.overlap.Coordinator,
        command: list[str],
        phase: str,
    ) -> tests.formal.helpers.process.Result:
        """Expose native phase completion and cancellation without starting pytest.

        Args:
            coordinator: The actual owner recording phase completion.
            command: Original native regular or conformance arguments.
            phase: The phase whose boundary is controlled.

        Returns:
            A successful native reply after the controlled phase completes.

        Raises:
            asyncio.CancelledError: The owner cancelled admitted formal work.
        """
        if phase == "regular":
            events.regular_started.set()
            await events.regular.wait()
            tests.formal.helpers.overlap.require_success(events.regular_status, phase)
        else:
            assert phase == "formal"
            events.formal_arguments[:] = command
            events.formal_started.set()
            try:
                await events.formal.wait()
            except asyncio.CancelledError:
                events.formal_cancelled.set()
                raise
            tests.formal.helpers.overlap.require_success(events.formal_status, phase)
        coordinator.record(phase + "_graph_closed")
        return tests.formal.helpers.process.Result(
            returncode=0,
            stdout=f"Test artifacts: {coverage}\n" if phase == "regular" else "",
            stderr="",
        )

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            tests.formal.helpers.overlap,
            "source_inventory",
            lambda: {source: tests.helpers.ordinary_lanes.generation(source)},
        )
        coordinator = tests.formal.helpers.overlap.Coordinator(
            directory=directory,
            seal=tests.formal.helpers.overlap.source_seal(directory),
        )
        patch.setattr(
            tests.formal.check,
            "toolchain",
            unittest.mock.Mock(return_value=("controlled-java", pathlib.Path("jar"))),
        )
        patch.setattr(tests.formal.check, "run_models", models)
        patch.setattr(
            tests.formal.helpers.overlap.shutil,
            "which",
            unittest.mock.Mock(return_value="controlled-lake"),
        )
        patch.setattr(tests.formal.helpers.process, "execute", execute)
        patch.setattr(
            tests.formal.helpers.session,
            "directory",
            unittest.mock.Mock(return_value=directory / "corpus"),
        )
        patch.setattr(
            tests.formal.helpers.fixtures.defects,
            "require_pristine_targets",
            unittest.mock.Mock(return_value=19),
        )
        patch.setattr(tests.formal.helpers.overlap.Coordinator, "native", native)
        yield Controlled(coordinator=coordinator, events=events, source=source)


async def observe(event: asyncio.Event) -> None:
    """Wait for an explicit phase boundary with a deadlock guard.

    Args:
        event: The actual admission or prerequisite boundary.
    """
    await asyncio.wait_for(event.wait(), GUARD_SECONDS)


async def condition(predicate: collections.abc.Callable[[], bool]) -> None:
    """Wait for an observable file or coordinator boundary.

    Args:
        predicate: The boundary whose truth releases this control.
    """
    await asyncio.to_thread(wait_until, predicate)


def wait_until(predicate: collections.abc.Callable[[], bool]) -> None:
    """Observe cross-process file changes without blocking the owner's event loop.

    Args:
        predicate: The native observation that releases the waiting control.

    Raises:
        TimeoutError: The native worker did not reach its observation boundary.
    """
    deadline = time.monotonic() + GUARD_SECONDS
    while not predicate():
        if time.monotonic() >= deadline:
            message = "Native overlap control did not reach its observation boundary"
            raise TimeoutError(message)
        time.sleep(0.005)


def exception_messages(error: BaseException) -> list[str]:
    """Retain the underlying failure carried by a native task group.

    Args:
        error: An individual failure or task group's exception collection.

    Returns:
        The original failure types and messages.
    """
    if isinstance(error, BaseExceptionGroup):
        return [
            message
            for child in error.exceptions
            for message in exception_messages(child)
        ]
    return [f"{type(error).__name__}: {error}"]


async def failure(task: asyncio.Task[None]) -> list[str]:
    """Require failure after joining the actual coordinator's sibling cleanup.

    Args:
        task: The running coordinator or native guarded command.

    Returns:
        The underlying errors after the task has finished.

    Raises:
        AssertionError: The failed control returned successfully.
    """
    try:
        await asyncio.wait_for(task, GUARD_SECONDS)
    except (
        tests.formal.helpers.overlap.PhaseError,
        TimeoutError,
        asyncio.CancelledError,
        BaseExceptionGroup,
    ) as error:
        return exception_messages(error)
    message = "A failed coordinator returned successful evidence"
    raise AssertionError(message)


@contextlib.asynccontextmanager
async def running(
    coordinator: tests.formal.helpers.overlap.Coordinator,
) -> collections.abc.AsyncGenerator[asyncio.Task[None]]:
    """Keep a failed assertion from leaving controlled sibling phases blocked.

    Args:
        coordinator: The owner of all positive phases.

    Yields:
        Its running task, cancelled and joined if the test exits early.
    """
    task = asyncio.create_task(coordinator.run())
    try:
        yield task
    finally:
        if not task.done():
            task.cancel()
        async with asyncio.timeout(GUARD_SECONDS):
            await asyncio.gather(task, return_exceptions=True)


def native_owner(
    directory: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tests.formal.helpers.overlap.Coordinator:
    """Seal one real source while retaining all native process behavior.

    Args:
        directory: Private process handshakes and control files.
        monkeypatch: Restore the source inventory after the native control.

    Returns:
        A real coordinator whose native method owns its independent process groups.
    """
    source = directory / "owned-source.py"
    source.write_text("value = 1\n")
    monkeypatch.delenv(tests.formal.helpers.process.GROUP_VARIABLE, raising=False)
    monkeypatch.setattr(
        tests.formal.helpers.overlap,
        "source_inventory",
        lambda: {source: tests.helpers.ordinary_lanes.generation(source)},
    )
    return tests.formal.helpers.overlap.Coordinator(
        directory=directory,
        seal=tests.formal.helpers.overlap.source_seal(directory),
    )


def command(mode: str, directory: pathlib.Path) -> list[str]:
    """Run only a lightweight controller or leaf in the native process control.

    Args:
        mode: The resource ownership scenario.
        directory: Private readiness and cleanup observations.

    Returns:
        A direct Python command without a shell or nested pytest pool.
    """
    return [
        sys.executable,
        "-m",
        "tests.formal.helpers.overlap_worker",
        mode,
        str(directory),
    ]


def identity(directory: pathlib.Path, name: str) -> dict[str, int]:
    """Read a worker's atomically published native identifiers.

    Args:
        directory: Private process observation directory.
        name: The controller or leaf role.

    Returns:
        Actual process, group and session identifiers.
    """
    return json.loads((directory / f"{name}-ready.json").read_text())


async def assert_closed(directory: pathlib.Path) -> None:
    """Require physical group absence after cooperative cleanup completed.

    Args:
        directory: Private identities from the real controller and leaf.
    """
    for name in ("controller", "leaf"):
        observed = identity(directory, name)
        await tests.formal.helpers.process.group_closed(observed["group"])
        with pytest.raises(ProcessLookupError):
            os.kill(observed["pid"], 0)


async def close_native(task: asyncio.Task[None], directory: pathlib.Path) -> None:
    """Retire every observed group if a native control's assertion fails.

    Args:
        task: The controller invocation, including its process cleanup.
        directory: Private role identities that may have been published already.
    """
    if not task.done():
        task.cancel()
    for name in ("controller", "leaf"):
        if (directory / f"{name}-ready.json").exists():
            tests.formal.helpers.process.kill_group(identity(directory, name)["group"])
    async with asyncio.timeout(GUARD_SECONDS):
        await asyncio.gather(task, return_exceptions=True)
