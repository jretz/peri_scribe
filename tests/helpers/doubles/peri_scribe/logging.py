"""Deterministic writer contention makes timestamp ordering regressions repeatable."""

from __future__ import annotations

import datetime
import typing

import structlog

import peri_scribe.logging


if typing.TYPE_CHECKING:
    import pytest
    import time_machine


def overtake_first_writer(
    monkeypatch: pytest.MonkeyPatch,
    clock: time_machine.Traveller,
    later: datetime.datetime,
) -> None:
    """Let a later event append before the first writer acquires its lock.

    Args:
        monkeypatch: Replace the lock operation for the duration of the test.
        clock: The frozen clock shared by both writers.
        later: The timestamp at which the overtaking event occurs.
    """
    flock = peri_scribe.logging.fcntl.flock
    first_writer = True

    def acquire(lock: typing.TextIO, operation: int) -> None:
        """Reproduce writer contention without relying on thread scheduling.

        Args:
            lock: The writer's open lock file.
            operation: The requested file-lock operation.
        """
        nonlocal first_writer
        if first_writer:
            first_writer = False
            clock.move_to(later)
            structlog.get_logger().info("Overtaking writer")
        flock(lock, operation)

    monkeypatch.setattr(peri_scribe.logging.fcntl, "flock", acquire)
