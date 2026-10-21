"""Construct distinct real inventory files without persistent application state."""

import os
import pathlib
import time

from measurement_units import units


CTIME_CHANGE_TIMEOUT = 5 * units.seconds
CTIME_POLL_INTERVAL = 1 * units.milliseconds


def inventory(directory: pathlib.Path, count: int = 6) -> tuple[pathlib.Path, ...]:
    """Give every source distinguishable complete bytes and deterministic ordering.

    Args:
        directory: Isolated fixture directory.
        count: Number of independent temporary sources.

    Returns:
        Ordered paths whose content identities can be checked independently.
    """
    result = tuple(directory / f"snapshot-{index}" for index in range(count))
    for index, path in enumerate(result):
        path.write_bytes(f"source bytes {index}".encode())
    return result


def rewrite_with_changed_ctime(
    path: pathlib.Path,
    contents: bytes,
    *,
    timestamps: tuple[int, int] | None = None,
) -> None:
    """Make a real fixture edit satisfy the modeled changed-metadata premise.

    Filesystem timestamps can share one clock tick even when expressed in nanoseconds.
    Repeating utime preserves the selected access and modification times while waiting
    for an observed ctime change. Only tests use this bounded synchronization adapter.

    Args:
        path: Existing temporary source to edit in place.
        contents: Complete replacement source bytes.
        timestamps: Access and modification times in nanoseconds, or the current times.

    Raises:
        AssertionError: If the filesystem does not expose a changed ctime in time.
    """
    previous = path.stat()
    selected = (
        (previous.st_atime_ns, previous.st_mtime_ns)
        if timestamps is None
        else timestamps
    )
    deadline = time.monotonic() * units.seconds + CTIME_CHANGE_TIMEOUT
    path.write_bytes(contents)
    while True:
        os.utime(path, ns=selected)
        current = path.stat()
        if current.st_ctime_ns != previous.st_ctime_ns:
            return
        if time.monotonic() * units.seconds >= deadline:
            details = {
                name: (getattr(previous, name), getattr(current, name))
                for name in (
                    "st_dev",
                    "st_ino",
                    "st_size",
                    "st_mtime_ns",
                    "st_ctime_ns",
                )
            }
            message = (
                f"File ctime did not change within {CTIME_CHANGE_TIMEOUT} for {path}; "
                f"before/after identity: {details}"
            )
            raise AssertionError(message)
        time.sleep(CTIME_POLL_INTERVAL.m_as("seconds"))
