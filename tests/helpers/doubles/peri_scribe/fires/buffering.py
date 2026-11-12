"""Observe real buffer futures while retaining native geometry computation."""

from __future__ import annotations

import collections.abc
import concurrent.futures
import dataclasses
import functools
import threading
import typing

import shapely


if typing.TYPE_CHECKING:
    import pytest


@dataclasses.dataclass(frozen=True, kw_only=True)
class BufferingWorkers:
    """Admit one native wave and finish its second future before its first."""

    operation: collections.abc.Callable[[shapely.Geometry], shapely.Geometry]
    positions: dict[bytes, int]
    barrier: threading.Barrier
    lock: threading.Lock = dataclasses.field(default_factory=threading.Lock)
    second_completed: threading.Event = dataclasses.field(
        default_factory=threading.Event,
    )
    counts: dict[str, int] = dataclasses.field(
        default_factory=lambda: {"active": 0, "peak": 0},
    )
    completions: list[int] = dataclasses.field(default_factory=list)
    threads: set[threading.Thread] = dataclasses.field(default_factory=set)

    def __call__(self, geometry: shapely.Geometry) -> shapely.Geometry:
        """Keep the original GEOS operation inside the observed worker lifetime.

        Args:
            geometry: The actual projected geometry submitted by production.

        Returns:
            The original native buffer result.

        Raises:
            TimeoutError: The second future did not complete within the bounded wait.
        """
        index = self.positions[geometry.wkb]
        with self.lock:
            self.counts["active"] += 1
            self.counts["peak"] = max(self.counts["peak"], self.counts["active"])
            self.threads.add(threading.current_thread())
        succeeded = False
        try:
            self.barrier.wait(timeout=5)
            if index == 0 and not self.second_completed.wait(timeout=5):
                message = "The second native buffer future did not complete"
                raise TimeoutError(message)
            result = self.operation(geometry)
            succeeded = True
            return result
        finally:
            if not succeeded:
                self.barrier.abort()
                self.second_completed.set()
            with self.lock:
                self.counts["active"] -= 1

    def completed(self, index: int, _future: concurrent.futures.Future[object]) -> None:
        """Record actual future completion before releasing the first buffer.

        Args:
            index: The original nonmissing input position.
            _future: The completed native executor future.
        """
        with self.lock:
            self.completions.append(index)
        if index == 1:
            self.second_completed.set()


def observe_submissions(
    workers: BufferingWorkers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Attach completion observers to the unchanged native executor's futures.

    Args:
        workers: The gated native buffer callable.
        monkeypatch: The test-owned replacement scope.
    """
    original = concurrent.futures.ThreadPoolExecutor.submit

    def submit(
        executor: concurrent.futures.ThreadPoolExecutor,
        function: collections.abc.Callable[..., object],
        *args: object,
        **kwargs: object,
    ) -> concurrent.futures.Future[object]:
        """Keep native submission and observe only the selected buffer work.

        Args:
            executor: The actual production thread pool.
            function: The submitted callable.
            *args: Original positional arguments.
            **kwargs: Original keyword arguments.

        Returns:
            The unchanged native future.
        """
        future = original(executor, function, *args, **kwargs)
        if function is workers:
            (geometry,) = args
            assert isinstance(geometry, shapely.Geometry)
            index = workers.positions[geometry.wkb]
            future.add_done_callback(functools.partial(workers.completed, index))
        return future

    monkeypatch.setattr(concurrent.futures.ThreadPoolExecutor, "submit", submit)
