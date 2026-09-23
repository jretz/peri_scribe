"""Interrupt individual publication boundaries without replacing their neighbors."""

import collections.abc
import pathlib
import typing

import peri_scribe.publication


if typing.TYPE_CHECKING:
    import pydantic


def failing_state_writer(
    destination: pathlib.Path,
) -> collections.abc.Callable[[pathlib.Path, pydantic.BaseModel], None]:
    """Fail one destination while allowing the journal or checkpoint to persist.

    Args:
        destination: The state file whose write should fail.

    Returns:
        A state writer that raises for the selected destination.
    """
    write_state = peri_scribe.publication.write_state

    def write(path: pathlib.Path, state: pydantic.BaseModel) -> None:
        """Keep unrelated state writes real so interruption ordering is observable.

        Args:
            path: The state destination.
            state: The complete model to persist.

        Raises:
            OSError: If the selected publication boundary is reached.
        """
        if path == destination:
            message = "Interrupted state write"
            raise OSError(message)
        write_state(path, state)

    return write


def failing_unlink(
    destination: pathlib.Path,
) -> collections.abc.Callable[..., None]:
    """Interrupt cleanup after publishing a checkpoint or compressed log.

    Args:
        destination: The path whose removal should fail.

    Returns:
        A Path.unlink replacement preserving every unrelated removal.
    """
    unlink = pathlib.Path.unlink

    def remove(path: pathlib.Path, *, missing_ok: bool = False) -> None:
        """Allow atomic state temporary directories to clean up normally.

        Args:
            path: The file to remove.
            missing_ok: Whether a missing file is acceptable.

        Raises:
            OSError: If removing the selected file is attempted.
        """
        if path == destination:
            message = "Interrupted file removal"
            raise OSError(message)
        unlink(path, missing_ok=missing_ok)

    return remove
