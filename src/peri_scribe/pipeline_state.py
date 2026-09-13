"""Durable rebuild requirements and one writer per year directory."""

from __future__ import annotations

import contextlib
import fcntl
import pathlib
import tempfile
import typing

import pydantic
import structlog


logger = structlog.get_logger()
type DerivedStage = typing.Literal["geography", "score", "kmz", "reports"]
DERIVED_STAGES: tuple[DerivedStage, ...] = ("geography", "score", "kmz", "reports")


class PendingRun(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")

    version: typing.Literal[1] = 1
    remaining: tuple[DerivedStage, ...] = ()
    unconditional: bool = False


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


def read_state(year_directory: pathlib.Path) -> PendingRun:
    """An invalid recovery marker requires a fresh rebuild rather than a skip.

    Args:
        year_directory: The year directory whose pending work should be read.

    Returns:
        The unfinished stages and whether they must bypass prior derivations.
    """
    path = state_path(year_directory)
    try:
        state = PendingRun.model_validate_json(path.read_bytes())
    except FileNotFoundError:
        return PendingRun()
    except ValueError as error:
        logger.warning(
            "Invalid run state; requiring full rebuild",
            error=str(error),
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
    path = state_path(year_directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent) as directory:
        temporary = pathlib.Path(directory) / path.name
        temporary.write_text(state.model_dump_json())
        temporary.replace(path)


def require_stages(
    year_directory: pathlib.Path,
    stages: tuple[DerivedStage, ...],
    *,
    unconditional: bool = False,
) -> None:
    """New inputs invalidate downstream output even if an earlier attempt failed.

    Args:
        year_directory: The year directory whose outputs need rebuilding.
        stages: The stages to add to any existing pending work.
        unconditional: Whether pending stages must bypass prior derivations.
    """
    state = read_state(year_directory)
    write_state(
        year_directory,
        PendingRun(
            remaining=tuple(
                stage
                for stage in DERIVED_STAGES
                if stage in {*state.remaining, *stages}
            ),
            unconditional=state.unconditional or unconditional,
        ),
    )


def complete_stage(year_directory: pathlib.Path, stage: str) -> None:
    """Only a completed prerequisite allows downstream results to count as current.

    Args:
        year_directory: The year directory whose recovery state should be updated.
        stage: The name of the stage that completed successfully.
    """
    state = read_state(year_directory)
    if not state.remaining or state.remaining[0] != stage:
        return
    remaining = state.remaining[1:]
    write_state(
        year_directory,
        PendingRun(
            remaining=remaining,
            unconditional=state.unconditional if remaining else False,
        ),
    )
    if not remaining:
        logger.info("Required rebuild completed", unconditional=state.unconditional)


@contextlib.contextmanager
def run_lock(year_directory: pathlib.Path) -> typing.Iterator[bool]:
    """Avoid concurrent scheduled writers; the next invocation can retry skipped work.

    Args:
        year_directory: The year directory to protect from concurrent runs.

    Yields:
        Whether this invocation owns the year's writer lock.
    """
    path = lock_path(year_directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)
