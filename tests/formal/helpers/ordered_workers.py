"""Connect actual scheduler admission and delivery to checked complete TLC paths."""

import concurrent.futures
import dataclasses
import re
import typing
import unittest.mock

import peri_scribe.concurrency
import tests.formal.helpers.paths
import tests.formal.helpers.tlc


type Value = tuple[
    tuple[str, ...],
    tuple[int, ...],
    int,
    tuple[int, ...],
    str,
    str,
    int,
    tuple[int, ...],
    tuple[int, ...],
    bool,
]
TASK_COUNT = 3
CONFIGURATION_COUNT = 3**TASK_COUNT * 2**TASK_COUNT


def numbers(value: str) -> tuple[int, ...]:
    """Decode finite natural-number sequences and sets from TLC.

    Args:
        value: A sequence or set rendered by TLC.

    Returns:
        Its ordered integer members.
    """
    return tuple(map(int, re.findall(r"\d+", value)))


def contract(
    graph: tests.formal.helpers.tlc.Graph,
) -> tests.formal.helpers.paths.Contract[Value]:
    """Preserve the complete scheduler state and actual transition relation.

    Args:
        graph: Successfully checked OrderedWorkers graph.

    Returns:
        Exact state projections and action labels, without internal transition skips.
    """
    return tests.formal.helpers.paths.Contract(
        graph=graph,
        values={
            identifier: (
                tuple(re.findall(r'"([a-z]+)"', state["status"])),
                tuple(sorted(numbers(state["observed"]))),
                int(state["submitted"]),
                numbers(state["delivered"]),
                state["owner"].strip('"'),
                state["outcome"].strip('"'),
                int(state["failed"]),
                numbers(state["weights"]),
                tuple(sorted(numbers(state["failures"]))),
                state["published"] == "TRUE",
            )
            for identifier, state in graph.states.items()
        },
        actions={
            edge: edge.action for edges in graph.outgoing.values() for edge in edges
        },
        internal=frozenset(),
    )


@dataclasses.dataclass(kw_only=True)
class Replay:
    """Control only worker completion; the real scheduler chooses all admissions."""

    checked: tests.formal.helpers.paths.Contract[Value]
    weights: tuple[int, ...]
    failures: tuple[int, ...]
    completion_order: tuple[int, ...]
    stop: int | None = None
    futures: dict[int, ObservedFuture] = dataclasses.field(default_factory=dict)
    observed: set[int] = dataclasses.field(default_factory=set)
    delivered: list[int] = dataclasses.field(default_factory=list)
    owner: str = "active"
    outcome: str = "pending"
    failed: int = 0
    execution: tests.formal.helpers.paths.Path[Value] = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        """Begin from a checked initial state matching these inputs and failures."""
        self.execution = self.checked.start(self.value())

    def value(self) -> Value:
        """Project actual future states and observed delivery into the model.

        Returns:
            The complete current model observation.
        """
        statuses = []
        for item in range(1, 4):
            future = self.futures.get(item)
            if future is None:
                status = "new"
            elif future.cancelled():
                status = "cancelled"
            elif future.done():
                status = "bad" if future.exception() is not None else "good"
            elif future.running():
                status = "running"
            else:
                status = "queued"
            statuses.append(status)
        return (
            tuple(statuses),
            tuple(sorted(self.observed)),
            len(self.futures),
            tuple(self.delivered),
            self.owner,
            self.outcome,
            self.failed,
            self.weights,
            self.failures,
            False,
        )

    def event(self, action: str) -> None:
        """Require every actual effect to continue the same checked path.

        Args:
            action: The effect observed at this concrete adapter boundary.
        """
        self.execution = self.execution.transition(action, self.value())

    def submit(
        self,
        function: typing.Callable[[int], int],
        item: int,
    ) -> ObservedFuture:
        """Record input admission before any worker executes.

        Args:
            function: The application's task, retained until the fake worker runs.
            item: The task's one-based original position.

        Returns:
            A genuine Future with controlled execution and observable delivery.
        """
        future = ObservedFuture(self, item, function)
        self.futures[item] = future
        self.event("Admit")
        return future

    def wait(
        self,
        pending: typing.Iterable[ObservedFuture],
        *,
        return_when: str,
    ) -> tuple[set[ObservedFuture], set[ObservedFuture]]:
        """Choose a legal completion order independently of the scheduler.

        Args:
            pending: Futures admitted by the production scheduler.
            return_when: The expected first-completion wait mode.

        Returns:
            One completed future and all other pending futures.
        """
        assert return_when == concurrent.futures.FIRST_COMPLETED
        candidates = set(pending)
        future = min(
            candidates,
            key=lambda value: self.completion_order.index(value.item),
        )
        assert future.set_running_or_notify_cancel()
        self.event("Start")
        if future.item in self.failures:
            future.set_exception(RuntimeError(str(future.item)))
        else:
            future.set_result(future.function(future.item))
        self.event("Finish")
        self.observed.add(future.item)
        self.event("Observe")
        return {future}, candidates - {future}

    def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
        """Check cleanup flags and retire queued work before resource release.

        Args:
            wait: Whether the owning context joins workers.
            cancel_futures: Whether queued work is cancelled on exit.
        """
        assert wait
        assert cancel_futures
        if self.owner == "active":
            self.owner = "closing"
            self.outcome = (
                "success" if len(self.delivered) == TASK_COUNT else "cancelled"
            )
            self.event("Complete" if self.outcome == "success" else "Cancel")
        for future in self.futures.values():
            if not future.done():
                assert future.cancel()
                self.event("CancelQueued")
        self.owner = "released"
        self.event("Release")

    def run(self) -> None:
        """Drive the real scheduler through one controlled complete execution."""
        actual_error = None
        with (
            unittest.mock.patch.object(
                peri_scribe.concurrency.concurrent.futures,
                "ThreadPoolExecutor",
                return_value=self,
            ),
            unittest.mock.patch.object(
                peri_scribe.concurrency.concurrent.futures,
                "wait",
                self.wait,
            ),
        ):
            try:
                self.consume()
            except RuntimeError as error:
                actual_error = str(error)
        if actual_error is not None:
            assert actual_error == str(self.failed)
            assert self.failed == min(self.failures)
        assert self.owner == "released"

    def consume(self) -> None:
        """Exercise consumer closure independently of worker completion order."""
        with peri_scribe.concurrency.ordered_parallel_map(
            int,
            range(1, 4),
            max_workers=2,
            max_pending=2,
            weight=lambda item: self.weights[item - 1],
            max_weight=2,
        ) as results:
            if self.stop != 0:
                for _value in results:
                    if len(self.delivered) == self.stop:
                        break


class ObservedFuture(concurrent.futures.Future[int]):
    """Observe the application's result retrieval without altering Future semantics."""

    def __init__(
        self,
        replay: Replay,
        item: int,
        function: typing.Callable[[int], int],
    ) -> None:
        """Keep controlled worker input separate from scheduling decisions.

        Args:
            replay: Complete trace observer.
            item: One-based task position.
            function: Task computation to execute on simulated worker completion.
        """
        super().__init__()
        self.replay = replay
        self.item = item
        self.function = function

    def result(self, timeout: float | None = None) -> int:
        """Record ordered delivery or failure at the actual result boundary.

        Args:
            timeout: Optional Future result timeout.

        Returns:
            The real Future's task result.
        """
        if self.exception() is None:
            self.replay.delivered.append(self.item)
            self.replay.event("Deliver")
        else:
            self.replay.owner = "closing"
            self.replay.outcome = "error"
            self.replay.failed = self.item
            self.replay.event("Raise")
        return super().result(timeout)
