"""Coordinate shutdown with an in-flight history batch without timing assumptions."""

import collections.abc
import contextlib
import dataclasses
import datetime
import threading

import peri_scribe.monitor.storage


@contextlib.contextmanager
def observed_lock(
    lock: threading.Lock,
    waiting: threading.Event,
) -> collections.abc.Generator[None]:
    """Acknowledge a shutdown acquisition before waiting on the actual read lock.

    Args:
        lock: The lock already held by an admitted history read.
        waiting: Signals that shutdown has reached its resource ownership boundary.

    Yields:
        Control after the active read releases its ownership.
    """
    waiting.set()
    with lock:
        yield


@dataclasses.dataclass(frozen=True, kw_only=True)
class BlockedPoll:
    """Let a test release a read only after the observer has received shutdown."""

    started: threading.Event
    release: threading.Event

    def __call__(
        self,
        *,
        since: datetime.datetime,
    ) -> peri_scribe.monitor.storage.Batch:
        """Leave more history pending so shutdown must stop the catch-up loop.

        Args:
            since: The observation cutoff supplied by the reader.

        Returns:
            An unfinished read after the test releases it.

        Raises:
            TimeoutError: The controlling test failed to release the read.
        """
        self.started.set()
        if not self.release.wait(timeout=5):
            message = f"Test did not release the read for {since.isoformat()}"
            raise TimeoutError(message)
        return peri_scribe.monitor.storage.Batch(caught_up=False)
