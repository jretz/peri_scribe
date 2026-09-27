"""Replay checked collection outcomes through the real asyncio and pipeline control."""

import asyncio
import dataclasses
import datetime
import pathlib
import re
import threading
import time
import typing

import pytest
import structlog.testing

import peri_scribe.fires.index
import peri_scribe.pipeline
import peri_scribe.pipeline_stages
import peri_scribe.pipeline_state
import peri_scribe.publication
import peri_scribe.sources.feed_types
import peri_scribe.sources.feeds
import peri_scribe.sources.fetching
import peri_scribe.sources.full_fetch_state
import tests.helpers.doubles.peri_scribe.sources.fetching
from measurement_units import units


CAPACITY = 2


class CollectionBoundary(BaseException):
    """Stop a gated invocation at collection, before its separately modeled gate."""


@dataclasses.dataclass(frozen=True, kw_only=True)
class Case:
    """Inputs chosen independently of the concurrent schedule."""

    kinds: tuple[str, ...]
    full: bool
    prior: bool
    index_failure: bool
    deferred: bool


@dataclasses.dataclass(frozen=True, kw_only=True)
class Outcome:
    """Persisted effects and coordinator termination visible to callers."""

    snapshots: frozenset[int]
    indexed: frozenset[int]
    pending: bool
    acknowledged: bool
    attempted: bool
    phase: str


def integer_set(value: str) -> frozenset[int]:
    """Read a TLC set without introducing a second policy implementation.

    Args:
        value: A TLC set of feed numbers.

    Returns:
        Exactly those numbers.
    """
    return frozenset(map(int, re.findall(r"\d+", value)))


def cases(states: list[dict[str, str]]) -> dict[Case, set[Outcome]]:
    """Retain every legal final outcome for each checked input configuration.

    Args:
        states: Complete checked graph.

    Returns:
        Inputs mapped to the set of permitted concurrent results.
    """
    result: dict[Case, set[Outcome]] = {}
    for state in states:
        phase = state["phase"].strip('"')
        if phase not in {"done", "failed"}:
            continue
        case = Case(
            kinds=tuple(re.findall(r'"([^\"]+)"', state["kind"])),
            full=state["full"] == "TRUE",
            prior=state["prior"] == "TRUE",
            index_failure=state["indexFailure"] == "TRUE",
            deferred=state["deferIndex"] == "TRUE",
        )
        result.setdefault(case, set()).add(
            Outcome(
                snapshots=integer_set(state["snapshots"]),
                indexed=integer_set(state["indexed"]),
                pending=state["pending"] == "TRUE",
                acknowledged=state["acknowledged"] == "TRUE",
                attempted=state["indexAttempted"] == "TRUE",
                phase=phase,
            ),
        )
    return result


@dataclasses.dataclass(kw_only=True)
class CollectionProbe:
    """Control external feeds and index I/O while preserving production coordination."""

    case: Case
    directory: pathlib.Path
    active: set[int] = dataclasses.field(default_factory=set)
    finished: set[int] = dataclasses.field(default_factory=set)
    started: set[int] = dataclasses.field(default_factory=set)
    saved: set[int] = dataclasses.field(default_factory=set)
    indexed: frozenset[int] = frozenset()
    attempted: bool = False
    peak: int = 0
    mutex: threading.Lock = dataclasses.field(default_factory=threading.Lock)

    def fetch(
        self,
        feed: peri_scribe.sources.feed_types.Feed,
        *,
        base_dir: pathlib.Path,
        year: int,
        full: bool,
    ) -> peri_scribe.sources.fetching.FeedOutcome:
        """Persist selected feed effects before returning or raising in a real worker.

        Args:
            feed: Source selected by the real coordinator.
            base_dir: Isolated data root.
            year: Selected year.
            full: Scheduling decision from production full-fetch state.

        Returns:
            Expected per-feed success or source failure.

        Raises:
            RuntimeError: A fatal failure before or after persistent snapshot output.
        """
        assert base_dir / "data" / str(year) == self.directory
        assert full == self.case.full
        identifier = int(feed.name)
        with self.mutex:
            self.active.add(identifier)
            self.started.add(identifier)
            self.peak = max(self.peak, len(self.active))
        try:
            assert (
                peri_scribe.pipeline_state.read_state(self.directory).remaining
                or peri_scribe.pipeline_state.deferred_inputs_path(
                    self.directory,
                ).exists()
            )
            kind = self.case.kinds[identifier - 1]
            path = self.directory / "sources" / f"{identifier}.gpkg"
            if kind in {"change", "fatalAfter"}:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("complete saved snapshot", encoding="utf-8")
                with self.mutex:
                    self.saved.add(identifier)
            if kind in {"fatalBefore", "fatalAfter"}:
                message = f"fatal feed {identifier}"
                raise RuntimeError(message)
            if kind == "sourceError":
                return peri_scribe.sources.fetching.FeedOutcome(
                    error=f"unavailable feed {identifier}",
                )
            return peri_scribe.sources.fetching.FeedOutcome(
                path=path,
                changed=kind == "change",
            )
        finally:
            with self.mutex:
                self.active.remove(identifier)
                self.finished.add(identifier)

    def index(self, directory: pathlib.Path) -> None:
        """Ensure the coordinator joins workers before reading saved snapshots.

        Args:
            directory: Source root handed to the real index entry point.

        Raises:
            OSError: Configured index publication failure.
        """
        assert directory == self.directory
        assert not self.active
        assert self.finished == self.started
        self.attempted = True
        if self.case.index_failure:
            message = "index publication failed"
            raise OSError(message)
        self.indexed = frozenset(self.saved)

    def install(self, patch: pytest.MonkeyPatch) -> None:
        """Leave concurrency, aggregation, markers, and acknowledgment writes intact.

        Args:
            patch: An isolated dependency replacement context.
        """
        feeds = tuple(
            tests.helpers.doubles.peri_scribe.sources.fetching.FeedStub(
                name=str(number),
                url=f"https://example.test/{number}",
                last_edit_timestamp=1,
            )
            for number in range(1, len(self.case.kinds) + 1)
        )
        patch.setattr(peri_scribe.sources.feeds, "FEEDS", feeds)
        patch.setattr(peri_scribe.sources.fetching, "FEED_CONCURRENCY", CAPACITY)
        patch.setattr(peri_scribe.sources.fetching, "fetch_feed_snapshot", self.fetch)
        patch.setattr(peri_scribe.fires.index, "index_fire_sources", self.index)
        patch.setattr(
            peri_scribe.pipeline,
            "prepare_administrative_boundaries",
            lambda _directory: None,
        )
        patch.setattr(
            peri_scribe.pipeline,
            "refresh_external_sources",
            lambda _directory: False,
        )
        patch.setattr(
            peri_scribe.pipeline,
            "fetch_external_source",
            lambda _source, _directory: None,
        )
        patch.setattr(
            peri_scribe.pipeline,
            "publication_decision",
            stop_after_collection,
        )

    def run(self) -> Outcome:
        """Execute a complete ungated invocation or the gated collection boundary.

        Returns:
            Durable output compared with checked reachable states.
        """
        self.directory.mkdir(parents=True)
        if self.case.prior:
            peri_scribe.pipeline_state.require_stages(
                self.directory,
                (peri_scribe.pipeline_stages.Stage.REPORTS,),
            )
        threshold = (
            peri_scribe.publication.Threshold(
                area=1 * units.acre,
                interval=datetime.timedelta(hours=1),
            )
            if self.case.deferred
            else None
        )
        phase = "done"
        with pytest.MonkeyPatch.context() as patch, structlog.testing.capture_logs():
            self.install(patch)
            try:
                peri_scribe.pipeline.run_fetch_stage(
                    self.directory,
                    full_fetch_interval=(
                        datetime.timedelta(days=1) if self.case.full else None
                    ),
                    unconditional=False,
                    publish_threshold=threshold,
                )
            except CollectionBoundary:
                assert self.case.deferred
            except ExceptionGroup, OSError, SystemExit:
                phase = "failed"
        assert not self.active
        assert self.finished == self.started
        assert self.peak <= CAPACITY
        assert (
            frozenset(
                int(path.stem) for path in (self.directory / "sources").glob("*.gpkg")
            )
            == self.saved
        )
        return Outcome(
            snapshots=frozenset(self.saved),
            indexed=self.indexed,
            pending=bool(
                peri_scribe.pipeline_state.read_state(self.directory).remaining
                or peri_scribe.pipeline_state.deferred_inputs_path(
                    self.directory,
                ).exists(),
            ),
            acknowledged=peri_scribe.sources.full_fetch_state.state_path(
                self.directory,
            ).exists(),
            attempted=self.attempted,
            phase=phase,
        )


def stop_after_collection(
    _directory: pathlib.Path,
    _threshold: peri_scribe.publication.Threshold,
) -> peri_scribe.publication.Decision:
    """Expose the collection boundary before a gate can perform deferred indexing.

    Args:
        _directory: The gate's data root.
        _threshold: The gate's policy, outside this model's scope.

    Raises:
        CollectionBoundary: Collection has returned successfully.
    """
    raise CollectionBoundary


def replay(states: list[dict[str, str]], directory: pathlib.Path) -> int:
    """Run every checked input combination against the actual collection coordinator.

    Args:
        states: Entire checked state graph.
        directory: Isolated tree for persistent pipeline state.

    Returns:
        Number of exercised input combinations.
    """
    checked = cases(states)
    for number, (case, expected) in enumerate(checked.items()):
        probe = CollectionProbe(
            case=case,
            directory=directory / str(number) / "data" / "2026",
        )
        observed = probe.run()
        assert observed in expected, (case, observed, expected)
    return len(checked)


@dataclasses.dataclass(kw_only=True)
class CancelledSibling(CollectionProbe):
    """Hold a sibling worker until its real task has received cancellation."""

    tasks: dict[int, asyncio.Task[object]] = dataclasses.field(default_factory=dict)
    sibling_started: threading.Event = dataclasses.field(
        default_factory=threading.Event,
    )
    cancellation_observed: bool = False

    def fetch(
        self,
        feed: peri_scribe.sources.feed_types.Feed,
        *,
        base_dir: pathlib.Path,
        year: int,
        full: bool,
    ) -> peri_scribe.sources.fetching.FeedOutcome:
        """Force a filesystem write to complete after sibling-triggered cancellation.

        Args:
            feed: Configured source.
            base_dir: Isolated data root.
            year: Configured year.
            full: Production full-fetch scheduling decision.

        Returns:
            The underlying feed outcome after the controlled interleaving.
        """
        identifier = int(feed.name)
        if identifier == 1:
            assert self.sibling_started.wait(5)
        elif identifier == CAPACITY:
            self.sibling_started.set()
            deadline = time.monotonic() + 5
            while (
                not self.tasks[identifier].cancelling() and time.monotonic() < deadline
            ):
                time.sleep(0.001)
            assert self.tasks[identifier].cancelling()
            self.cancellation_observed = True
        return super().fetch(feed, base_dir=base_dir, year=year, full=full)

    def install(self, patch: pytest.MonkeyPatch) -> None:
        """Observe task handles without replacing collection or cancellation behavior.

        Args:
            patch: Isolated replacement context.
        """
        super().install(patch)
        original = peri_scribe.sources.fetching.collect_one_feed

        async def track(
            fetch: typing.Callable[
                [peri_scribe.sources.feed_types.Feed],
                peri_scribe.sources.fetching.FeedOutcome,
            ],
            feed: peri_scribe.sources.feed_types.Feed,
            limit: asyncio.Semaphore,
        ) -> peri_scribe.sources.fetching.FeedOutcome:
            """Expose the genuine task's cancellation state to the blocked worker.

            Args:
                fetch: Production worker operation.
                feed: Configured source.
                limit: Production shared semaphore.

            Returns:
                The unmodified feed outcome.
            """
            task = asyncio.current_task()
            assert task is not None
            self.tasks[int(feed.name)] = task
            return await original(fetch, feed, limit)

        patch.setattr(peri_scribe.sources.fetching, "collect_one_feed", track)


def replay_cancellation(states: list[dict[str, str]], directory: pathlib.Path) -> int:
    """Require actual late sibling writes to remain within checked final outcomes.

    Args:
        states: Complete checked graph.
        directory: Isolated run trees.

    Returns:
        Number of deliberately forced cancellation interleavings.
    """
    checked = cases(states)
    selected = {
        case: expected
        for case, expected in checked.items()
        if case.kinds
        in {
            ("fatalBefore", "change", "change"),
            ("fatalAfter", "change", "same"),
        }
    }
    for number, (case, expected) in enumerate(selected.items()):
        probe = CancelledSibling(
            case=case,
            directory=directory / str(number) / "data" / "2026",
        )
        assert probe.run() in expected
        assert probe.cancellation_observed
        assert CAPACITY in probe.saved
    return len(selected)
