"""Native directory notifications wake readers for changes to monitor inputs."""

import asyncio
import collections.abc
import contextlib
import pathlib

import watchfiles

from measurement_units import units


RECONCILE_INTERVAL = 30 * units.seconds
DEBOUNCE = 100 * units.milliseconds


def directories(directory: pathlib.Path) -> tuple[pathlib.Path, ...]:
    """Watch parent directories so replacement, rotation, and new folders stay visible.

    Args:
        directory: The watched year directory.

    Returns:
        Existing directories containing monitor inputs.
    """
    directory = directory.resolve()
    return tuple(
        path
        for path in (
            directory,
            directory / "logs",
            directory / "reports",
            directory / "maps",
        )
        if path.is_dir()
    )


async def wait_for_retry(stopped: asyncio.Event) -> None:
    """Allow shutdown to interrupt a delayed attempt at restoring notifications.

    Args:
        stopped: Cooperative shutdown signal for the native watcher.
    """
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stopped.wait(), RECONCILE_INTERVAL.m_as("seconds"))


async def watch(
    directory: pathlib.Path,
    stopped: asyncio.Event,
) -> collections.abc.AsyncIterator[None]:
    """Deliver change hints while allowing periodic reconciliation to recover.

    Args:
        directory: The watched year directory.
        stopped: Cooperative shutdown signal for the native watcher.

    Yields:
        A wake-up for each coalesced batch of filesystem changes.
    """
    while not stopped.is_set():
        paths = directories(directory)
        if not paths:
            await wait_for_retry(stopped)
            continue
        try:
            async for changes in watchfiles.awatch(
                *paths,
                stop_event=stopped,
                recursive=False,
                watch_filter=None,
                debounce=int(DEBOUNCE.m_as("milliseconds")),
            ):
                yield None
                replaced = any(
                    change != watchfiles.Change.modified and pathlib.Path(path) in paths
                    for change, path in changes
                )
                if replaced or directories(directory) != paths:
                    break
        except OSError, RuntimeError:
            await wait_for_retry(stopped)
