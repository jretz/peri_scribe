"""Coordinate real worker threads deterministically in concurrency tests."""

import threading
import typing

import peri_scribe.concurrency


REFILL_POSITION = 2


class OrderedCalls:
    """Expose completion order and cleanup without relying on timing ratios."""

    def __init__(self) -> None:
        """Create gates for a blocked first task and independently finishing peers."""
        self.release = threading.Event()
        self.started = threading.Event()
        self.finished = threading.Event()
        self.refilled = threading.Event()
        self.consumer_finished = threading.Event()
        self.errors: list[BaseException] = []
        self.values: list[int] = []

    def refill(self, value: int) -> int:
        """A third task releases the first, requiring completion-driven admission.

        Args:
            value: The task's original position.

        Returns:
            Its unchanged position.
        """
        if value == 0:
            assert self.refilled.wait(5)
        if value == REFILL_POSITION:
            self.refilled.set()
        return value

    def failure(self, value: int) -> int:
        """Make a later failure precede the earlier task's failure.

        Args:
            value: The task's original position.

        Raises:
            RuntimeError: With the failing position after the controlled dependency.
        """
        if value == 0:
            assert self.release.wait(5)
        else:
            self.release.set()
        raise RuntimeError(str(value))

    def blocked(self, value: int) -> int:
        """Hold a worker's resources until the supervising test permits cleanup.

        Args:
            value: The result to return after release.

        Returns:
            The unchanged value.
        """
        self.started.set()
        try:
            assert self.release.wait(5)
            return value
        finally:
            self.finished.set()

    def raising_inputs(self) -> typing.Iterator[int]:
        """Raise while an earlier submitted task still owns its resources.

        Yields:
            One input whose operation blocks before production fails.

        Raises:
            LookupError: After the worker has begun using the first input.
        """
        yield 0
        assert self.started.wait(5)
        message = "input failed"
        raise LookupError(message)

    def consume_failure(self) -> None:
        """Record input failure only after the production context has joined workers."""
        try:
            with peri_scribe.concurrency.ordered_parallel_map(
                self.blocked,
                self.raising_inputs(),
                max_workers=1,
            ) as results:
                self.values.extend(results)
        except LookupError as error:
            self.errors.append(error)
        finally:
            self.consumer_finished.set()

    def close_early(self) -> None:
        """Stop after one result while a second task remains blocked."""
        try:
            with peri_scribe.concurrency.ordered_parallel_map(
                self.after_first,
                range(3),
                max_workers=1,
            ) as results:
                self.values.append(next(results))
                assert self.started.wait(5)
        finally:
            self.consumer_finished.set()

    def after_first(self, value: int) -> int:
        """Permit the first result and hold its follower through context closure.

        Args:
            value: Original task position.

        Returns:
            The position after any required gate.
        """
        return value if value == 0 else self.blocked(value)


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
