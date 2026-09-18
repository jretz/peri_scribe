"""Coordinate real worker threads deterministically in concurrency tests."""

import threading


class BlockedOperation:
    """Expose worker lifetime independently of its awaiting coroutine."""

    def __init__(self) -> None:
        """Create independent gates for entry, release, and completion."""
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()

    def run(self, *, fail: bool = False) -> int:
        """Hold a worker until the test permits cleanup.

        Args:
            fail: Whether to simulate a failure after release.

        Returns:
            A recognizable result.

        Raises:
            RuntimeError: When failure is requested.
        """
        self.started.set()
        try:
            assert self.release.wait(5)
            if fail:
                message = "worker failed"
                raise RuntimeError(message)
            return 42
        finally:
            self.finished.set()


class ConcurrentCalls:
    """Measure overlapping work without depending on wall-clock speed."""

    def __init__(self, capacity: int) -> None:
        """Stop the first wave of workers at an observable concurrency boundary.

        Args:
            capacity: The expected number of simultaneous operations.
        """
        self.capacity = capacity
        self.lock = threading.Lock()
        self.ready = threading.Event()
        self.release = threading.Event()
        self.started: list[str] = []
        self.active = 0
        self.peak = 0

    def run(self, value: str) -> str:
        """Keep an operation active while its peers reach the same boundary.

        Args:
            value: A recognizable source identifier.

        Returns:
            The unchanged identifier.
        """
        with self.lock:
            self.started.append(value)
            self.active += 1
            self.peak = max(self.peak, self.active)
            if self.active == self.capacity:
                self.ready.set()
        try:
            assert self.release.wait(5)
            return value
        finally:
            with self.lock:
                self.active -= 1
