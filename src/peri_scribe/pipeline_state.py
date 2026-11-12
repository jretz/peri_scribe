"""Durable rebuild requirements and one writer per year directory.

Algorithm reasoning and contracts:
[Pipeline publication](../../docs/algorithms/pipeline-publication.md)
[Geography generations](../../docs/algorithms/geography-generations.md)
[Supervised stage processes](../../docs/algorithms/stage-processes.md)
"""

from __future__ import annotations

import contextlib
import contextvars
import dataclasses
import fcntl
import functools
import importlib
import os
import pathlib
import threading
import typing

import pydantic

import peri_scribe.durable_file
import peri_scribe.pipeline_stages


if typing.TYPE_CHECKING:
    import structlog.typing


DERIVED_STAGES: tuple[peri_scribe.pipeline_stages.Stage, ...] = (
    peri_scribe.pipeline_stages.Stage.GEOGRAPHY,
    peri_scribe.pipeline_stages.Stage.SCORE,
    peri_scribe.pipeline_stages.Stage.KMZ,
    peri_scribe.pipeline_stages.Stage.REPORTS,
)


class PendingRun(pydantic.BaseModel):
    """Validated recovery requirements for an unfinished pipeline run."""

    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)

    version: typing.Literal[1] = 1
    remaining: tuple[peri_scribe.pipeline_stages.Stage, ...] = ()
    unconditional: bool = False


@functools.cache
def state_logger() -> structlog.typing.FilteringBoundLogger:
    """Load logging when a state change or warning has something to report.

    Returns:
        The structured logger for recovery state events.
    """
    return importlib.import_module("structlog").get_logger()


def state_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Keep unfinished rebuild requirements separate from fetch completion.

    Args:
        year_directory: The year directory whose rebuild requirements are tracked.

    Returns:
        The recovery state path.
    """
    return year_directory / "run_state.json"


def lock_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Give writers to the same year directory a shared lock location.

    Args:
        year_directory: The year directory whose writers must not overlap.

    Returns:
        The writer lock path.
    """
    return year_directory / ".run.lock"


def deferred_inputs_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Keep saved unpublished inputs visible across pipeline policy changes.

    Args:
        year_directory: The year whose collected inputs may still need derivation.

    Returns:
        The durable deferred-input marker path.
    """
    return year_directory / "deferred_inputs"


def has_deferred_inputs(year_directory: pathlib.Path) -> bool:
    """Determine whether saved inputs may still require derivation.

    Args:
        year_directory: The year whose deferred-input marker should be checked.

    Returns:
        Whether the deferred-input marker exists.
    """
    return peri_scribe.durable_file.at(deferred_inputs_path(year_directory)).exists()


def defer_inputs(year_directory: pathlib.Path) -> None:
    """Record saved inputs before publication can be deferred.

    The marker keeps those inputs visible to later runs even if the publication policy
    changes before they produce outputs.

    Args:
        year_directory: The year whose collection may introduce unpublished inputs.
    """
    peri_scribe.durable_file.at(deferred_inputs_path(year_directory)).touch()


def clear_deferred_inputs(year_directory: pathlib.Path) -> None:
    """Clear the marker once a checkpoint or pending stages account for saved inputs.

    Args:
        year_directory: The year whose deferred inputs have durable coverage.
    """
    peri_scribe.durable_file.at(deferred_inputs_path(year_directory)).remove(
        missing_ok=True,
    )


def read_state(year_directory: pathlib.Path) -> PendingRun:
    """Require a fresh rebuild when the recovery marker is invalid.

    Args:
        year_directory: The year directory whose pending work should be read.

    Returns:
        The unfinished stages and whether they must bypass prior derivations.
    """
    path = state_path(year_directory)
    try:
        raw_state = peri_scribe.durable_file.at(path).read_bytes()
        state = PendingRun.model_validate_json(raw_state)
    except FileNotFoundError:
        return PendingRun()
    except ValueError as error:
        state_logger().warning(
            "Invalid run state; requiring full rebuild",
            error=str(error),
            exc_info=True,
        )
    else:
        expected = tuple(stage for stage in DERIVED_STAGES if stage in state.remaining)
        if expected == state.remaining:
            return state
    return PendingRun(remaining=DERIVED_STAGES, unconditional=True)


def write_state(year_directory: pathlib.Path, state: PendingRun) -> None:
    """Keep the previous recovery requirement intact if a state write is interrupted.

    Args:
        year_directory: The year directory whose recovery state should be replaced.
        state: The pending stages and their unconditional rebuild requirement.
    """
    peri_scribe.durable_file.at(state_path(year_directory)).replace_text(
        state.model_dump_json(),
    )


def required_state(
    state: PendingRun,
    stages: tuple[peri_scribe.pipeline_stages.Stage, ...],
    *,
    unconditional: bool = False,
) -> PendingRun:
    """Combine recovery requirements in dependency order.

    Args:
        state: The captured requirements before invalidating downstream work.
        stages: The additional stages whose inputs changed.
        unconditional: Whether pending work must bypass prior derivations.

    Returns:
        The complete requirements to persist before changing inputs.
    """
    return PendingRun(
        remaining=tuple(
            stage for stage in DERIVED_STAGES if stage in {*state.remaining, *stages}
        ),
        unconditional=state.unconditional or unconditional,
    )


def completed_state(
    state: PendingRun,
    stage: peri_scribe.pipeline_stages.Stage,
) -> PendingRun | None:
    """Acknowledge only the first outstanding prerequisite.

    Args:
        state: The captured requirements before acknowledging successful work.
        stage: The stage that completed successfully.

    Returns:
        The remaining requirements, or None when no write is needed.
    """
    if not state.remaining or state.remaining[0] != stage:
        return None
    remaining = state.remaining[1:]
    return PendingRun(
        remaining=remaining,
        unconditional=state.unconditional if remaining else False,
    )


def require_stages(
    year_directory: pathlib.Path,
    stages: tuple[peri_scribe.pipeline_stages.Stage, ...],
    *,
    unconditional: bool = False,
) -> None:
    """Invalidate downstream output when new inputs arrive after any attempt.

    Args:
        year_directory: The year directory whose outputs need rebuilding.
        stages: The stages to add to any existing pending work.
        unconditional: Whether pending stages must bypass prior derivations.
    """
    state = read_state(year_directory)
    write_state(
        year_directory,
        required_state(state, stages, unconditional=unconditional),
    )


def complete_stage(
    year_directory: pathlib.Path,
    stage: peri_scribe.pipeline_stages.Stage,
) -> None:
    """Only a completed prerequisite allows downstream results to count as current.

    Args:
        year_directory: The year directory whose recovery state should be updated.
        stage: The name of the stage that completed successfully.
    """
    state = read_state(year_directory)
    completed = completed_state(state, stage)
    if completed is None:
        return
    remaining = completed.remaining
    write_state(year_directory, completed)
    if not remaining:
        state_logger().info(
            "Required rebuild completed",
            unconditional=state.unconditional,
        )


@dataclasses.dataclass(kw_only=True)
class WriterOwnership:
    """Permit nested reads only while this process's writer lock remains live."""

    directory: pathlib.Path
    process: int
    thread: int
    active: bool = True


WRITERS: contextvars.ContextVar[tuple[WriterOwnership, ...]] = contextvars.ContextVar(
    "year_writers",
    default=(),
)


@contextlib.contextmanager
def run_lock(year_directory: pathlib.Path) -> typing.Generator[bool]:
    """Avoid competing writers while allowing the owner to read its published files.

    Args:
        year_directory: The year directory to protect from concurrent writers.

    Yields:
        Whether this invocation owns the year's writer lock.
    """
    with run_lease(year_directory) as descriptor:
        yield descriptor is not None


@contextlib.contextmanager
def run_lease(year_directory: pathlib.Path) -> typing.Generator[int | None]:
    """Keep an exclusive file description live across supervised child processes.

    Each holder closes its reference without explicitly unlocking the shared open file
    description. A surviving child therefore keeps the lease after its parent dies.

    Args:
        year_directory: The year whose cooperating writers must remain excluded.

    Yields:
        The inheritable lease descriptor, or None when another owner holds the lock.
    """
    path = lock_path(year_directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield None
            return
        with writer_context(year_directory):
            yield stream.fileno()


@contextlib.contextmanager
def inherited_lease(
    year_directory: pathlib.Path,
    descriptor: int,
) -> typing.Generator[None]:
    """Authenticate an inherited descriptor and own its nested reads until exit.

    Args:
        year_directory: The directory protected by the parent's continuous lease.
        descriptor: An inherited reference to that exact lock file description.

    Yields:
        Control while the child holds a validated writer lease.

    Raises:
        ValueError: If the descriptor belongs to a different lock file.
    """
    with os.fdopen(descriptor, "a", closefd=True) as stream:
        actual = os.fstat(stream.fileno())
        expected = lock_path(year_directory).stat()
        if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
            message = "Inherited writer lease does not match this year"
            raise ValueError(message)
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with writer_context(year_directory):
            yield


@contextlib.contextmanager
def writer_context(year_directory: pathlib.Path) -> typing.Generator[None]:
    """Permit nested reads only within this process's verified writer scope.

    Args:
        year_directory: The directory protected by the caller's live lease.

    Yields:
        Control with process and thread ownership registered for nested readers.
    """
    ownership = WriterOwnership(
        directory=year_directory.resolve(),
        process=os.getpid(),
        thread=threading.get_ident(),
    )
    token = WRITERS.set((*WRITERS.get(), ownership))
    try:
        yield
    finally:
        ownership.active = False
        WRITERS.reset(token)


@contextlib.contextmanager
def read_lock(year_directory: pathlib.Path) -> typing.Generator[bool]:
    """Keep related geography files unchanged for an entire multi-layer read.

    Args:
        year_directory: The year whose published files will be read together.

    Yields:
        Whether reading is protected by a shared lock or this context's live writer.
    """
    if any(
        owner.active
        and owner.process == os.getpid()
        and owner.thread == threading.get_ident()
        and owner.directory == year_directory.resolve()
        for owner in WRITERS.get()
    ):
        yield True
        return
    with file_lock(year_directory, shared=True) as acquired:
        yield acquired


@contextlib.contextmanager
def file_lock(year_directory: pathlib.Path, *, shared: bool) -> typing.Generator[bool]:
    """Use the same filesystem lock for readers and every authoritative CLI writer.

    Args:
        year_directory: The directory defining the shared lock location.
        shared: Whether other readers may hold the lock concurrently.

    Yields:
        Whether a nonblocking lock attempt succeeded.
    """
    path = lock_path(year_directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        try:
            mode = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
            fcntl.flock(stream, mode | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)
