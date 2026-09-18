"""Coordinate shutdown with an in-flight history batch without timing assumptions."""

import dataclasses
import datetime
import threading

import peri_scribe.monitor.storage


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
