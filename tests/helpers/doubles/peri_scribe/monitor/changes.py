"""Deterministic native-notification streams for directory and shutdown scenarios."""

import asyncio
import collections.abc
import pathlib

import peri_scribe.monitor.changes


async def notifications(
    stopped: asyncio.Event,
    create: pathlib.Path | None = None,
    changed: pathlib.Path | None = None,
) -> collections.abc.AsyncIterator[set[tuple[int, str]]]:
    """Yield a notification before cooperative shutdown, optionally creating a folder.

    Args:
        stopped: The watcher shutdown signal.
        create: A directory appearing while the watch is active.
        changed: An existing watched directory replaced without changing its path.

    Yields:
        One change batch before shutdown.
    """
    if create is not None:
        await asyncio.to_thread(create.mkdir)
    await asyncio.sleep(0)
    yield {(1, str(changed or create))}
    stopped.set()


async def collect(directory: pathlib.Path, stopped: asyncio.Event) -> list[None]:
    """Consume all hints without depending on native event timing.

    Args:
        directory: The isolated year directory.
        stopped: The watcher's shutdown signal.

    Returns:
        Every delivered change hint.
    """
    return [
        hint async for hint in peri_scribe.monitor.changes.watch(directory, stopped)
    ]


async def stop_during_retry(
    directory: pathlib.Path,
    stopped: asyncio.Event,
) -> list[None]:
    """Arrange shutdown at the next suspension inside a retry wait.

    Args:
        directory: The isolated year directory.
        stopped: The watcher's shutdown signal.

    Returns:
        The hints delivered before shutdown.
    """
    asyncio.get_running_loop().call_soon(stopped.set)
    return await collect(directory, stopped)


async def create_during_retry(
    directory: pathlib.Path,
    stopped: asyncio.Event,
) -> list[None]:
    """Let a year directory appear while initial discovery is waiting to retry.

    Args:
        directory: The isolated year directory that does not exist yet.
        stopped: The watcher's shutdown signal.

    Returns:
        The hints delivered after the directory appears.
    """
    asyncio.get_running_loop().call_soon(directory.mkdir)
    return await collect(directory, stopped)
