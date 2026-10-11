"""Own observable monitoring data independently of any presentation framework.

Algorithm reasoning and contracts:
[Monitor sessions](../../../docs/algorithms/monitor-sessions.md)
"""

import asyncio
import collections.abc
import compression.zstd
import dataclasses
import datetime
import enum
import functools
import heapq
import pathlib
import time

import peri_scribe.concurrency
import peri_scribe.monitor.changes
import peri_scribe.monitor.history
import peri_scribe.monitor.model
import peri_scribe.monitor.projection
import peri_scribe.monitor.status
import peri_scribe.monitor.storage
import peri_scribe.monitor.tasks
import peri_scribe.paths
from measurement_units import units


CLOCK_INTERVAL = 500 * units.milliseconds


class Priority(enum.IntEnum):
    """Urgent requests precede queued maintenance without interrupting readers."""

    IMMEDIATE = 0
    NORMAL = 1
    BACKGROUND = 2


@dataclasses.dataclass(frozen=True, kw_only=True)
class RefreshHealth:
    """Require complete recent evidence and current artifact metadata."""


@dataclasses.dataclass(frozen=True, kw_only=True)
class RefreshRecords:
    """Advance the independently bounded diagnostic record stream."""


@dataclasses.dataclass(frozen=True, kw_only=True)
class LoadOlder:
    """Extend diagnostic records with the next available archived month."""


@dataclasses.dataclass(frozen=True, kw_only=True)
class LoadRun:
    """Recover all available evidence for one command invocation."""

    identifier: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class RefreshReport:
    """Obtain the latest complete report replacement."""


@dataclasses.dataclass(frozen=True, kw_only=True)
class AdvanceClock:
    """Expire evidence and recalculate elapsed-time assessments without file reads."""


type Request = (
    RefreshHealth | RefreshRecords | LoadOlder | LoadRun | RefreshReport | AdvanceClock
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Snapshot:
    """Each version is a consistent immutable result of one admitted domain request."""

    version: int = 0
    health: peri_scribe.monitor.projection.Snapshot | None = None
    history: peri_scribe.monitor.history.History = dataclasses.field(
        default_factory=peri_scribe.monitor.history.History,
    )
    files: peri_scribe.monitor.status.Files | None = None
    records: peri_scribe.monitor.model.State = dataclasses.field(
        default_factory=peri_scribe.monitor.model.State,
    )
    archives: tuple[pathlib.Path, ...] = ()
    loaded_archives: frozenset[pathlib.Path] = frozenset()
    report: peri_scribe.monitor.storage.Report = dataclasses.field(
        default_factory=peri_scribe.monitor.storage.Report,
    )
    evidence: peri_scribe.monitor.model.Run | None = None
    errors: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True, kw_only=True, eq=False)
class Subscription:
    """A slow consumer retains only the newest complete version."""

    queue: asyncio.Queue[Snapshot | None] = dataclasses.field(
        default_factory=lambda: asyncio.Queue(maxsize=1),
    )
    stopped: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    detach: collections.abc.Callable[[Subscription], None]

    def __aiter__(self) -> Subscription:
        """Allow consumers to observe versions until either endpoint closes.

        Returns:
            This subscription's single-consumer iterator.
        """
        return self

    async def __anext__(self) -> Snapshot:
        """End iteration promptly when ownership of the subscription ends.

        Returns:
            The next complete snapshot.

        Raises:
            StopAsyncIteration: Once the subscription closes.
        """
        result = await self.receive()
        if result is None:
            raise StopAsyncIteration
        return result

    async def receive(self) -> Snapshot | None:
        """Wait for a complete version or the terminal closure notification.

        Returns:
            The newest pending snapshot, or None after closure.
        """
        if self.stopped.is_set():
            return None
        return await self.queue.get()

    def close(self) -> None:
        """Release retained evidence and wake a waiting consumer."""
        self.detach(self)
        self.stopped.set()
        offer(self, None)


@dataclasses.dataclass(frozen=True, kw_only=True, order=True)
class Pending:
    """Submission order breaks equal-priority ties without comparing domain payloads."""

    priority: Priority
    sequence: int
    request: Request = dataclasses.field(compare=False)
    result: asyncio.Future[Snapshot] = dataclasses.field(compare=False)
    admitted: asyncio.Event = dataclasses.field(
        default_factory=asyncio.Event,
        compare=False,
    )


class MonitorSession:
    """Own readers and asynchronous observation while publishing immutable data."""

    def __init__(self, year_directory: pathlib.Path, report_path: pathlib.Path) -> None:
        """Keep resource mutation at the filesystem and asynchronous ownership boundary.

        Args:
            year_directory: The observed year's data directory.
            report_path: The configured report output.
        """
        self.year_directory = year_directory
        self.report_path = report_path
        self.kmz_path = peri_scribe.paths.kmz_path(year_directory)
        self.follower = peri_scribe.monitor.storage.Follower(year_directory / "logs")
        self.history_reader = peri_scribe.monitor.history.Reader(
            year_directory / "logs",
        )
        self.owner = peri_scribe.monitor.tasks.Owner()
        self.snapshot = Snapshot()
        self.subscriptions: set[Subscription] = set()
        self.pending: list[Pending] = []
        self.submitted = 0
        self.dispatcher: asyncio.Task[None] | None = None
        self.observers: tuple[asyncio.Task[None], ...] = ()
        self.watching_stopped = asyncio.Event()
        self.records_requested = False
        self.report_requested = False
        self.files_changed = True
        self.reconcile_at = 0.0

    async def start(self, *, observe: bool = True) -> Snapshot:
        """Obtain complete health before attaching ongoing observation.

        Args:
            observe: Whether to start native hints and periodic reconciliation.

        Returns:
            The complete initial health snapshot.
        """
        self.files_changed = False
        snapshot = await self.request(RefreshHealth())
        if observe and not self.observers and not self.owner.stopped.is_set():
            self.observers = (
                asyncio.create_task(watch(self)),
                asyncio.create_task(clock(self)),
            )
        return snapshot

    def subscribe(self) -> Subscription:
        """Start with the current version and retain bounded pending delivery.

        Returns:
            A subscription that can be closed independently of the session.
        """
        subscription = Subscription(detach=self.subscriptions.discard)
        if self.owner.stopped.is_set():
            subscription.close()
        else:
            self.subscriptions.add(subscription)
            offer(subscription, self.snapshot)
        return subscription

    async def request(
        self,
        request: Request,
        *,
        priority: Priority = Priority.NORMAL,
    ) -> Snapshot:
        """Serialize admitted work through publication and caller cancellation.

        Args:
            request: The domain evidence required by a consumer.
            priority: Admission precedence among requests waiting for ownership.

        Returns:
            The resulting snapshot, or the final snapshot after shutdown begins.

        Raises:
            asyncio.CancelledError: After admitted work settles on cancellation.
        """
        if self.owner.stopped.is_set():
            return self.snapshot
        self.submitted += 1
        pending = Pending(
            priority=priority,
            sequence=self.submitted,
            request=request,
            result=asyncio.get_running_loop().create_future(),
        )
        heapq.heappush(self.pending, pending)
        if self.dispatcher is None or self.dispatcher.done():
            self.dispatcher = asyncio.create_task(dispatch(self))
        try:
            return await asyncio.shield(pending.result)
        except asyncio.CancelledError:
            if pending.admitted.is_set():
                await peri_scribe.concurrency.finish_worker(
                    asyncio.create_task(result_of(pending)),
                )
            else:
                pending.result.cancel()
            raise

    async def tick(self) -> None:
        """Reconcile missed notifications and advance time-based health policies."""
        if self.files_changed or time.monotonic() >= self.reconcile_at:
            self.files_changed = False
            await self.request(RefreshHealth(), priority=Priority.BACKGROUND)
            if self.records_requested:
                await self.request(RefreshRecords(), priority=Priority.BACKGROUND)
            if self.report_requested:
                await self.request(RefreshReport(), priority=Priority.BACKGROUND)
        else:
            await self.request(AdvanceClock(), priority=Priority.BACKGROUND)

    def promote(
        self,
        request: Request,
        *,
        priority: Priority = Priority.IMMEDIATE,
    ) -> bool:
        """Upgrade one queued request without duplicating or interrupting its work.

        Args:
            request: The identical request object retained by its original caller.
            priority: The requested stronger admission precedence.

        Returns:
            Whether a waiting request acquired stronger precedence.
        """
        for index, pending in enumerate(self.pending):
            if (
                pending.request is request
                and not pending.result.cancelled()
                and priority < pending.priority
            ):
                self.pending[index] = dataclasses.replace(pending, priority=priority)
                heapq.heapify(self.pending)
                return True
        return False

    async def close(self) -> None:
        """Stop admission and publication before settling workers and readers."""
        self.owner.stopped.set()
        self.watching_stopped.set()
        self.history_reader.stopped.set()
        while self.pending:
            pending = heapq.heappop(self.pending)
            if not pending.result.done():
                pending.result.set_result(self.snapshot)
        await peri_scribe.monitor.tasks.settle(asyncio.create_task(finish(self)))


def offer(subscription: Subscription, snapshot: Snapshot | None) -> None:
    """Replace an obsolete undelivered version without blocking the publisher.

    Args:
        subscription: The bounded consumer mailbox.
        snapshot: The latest complete version, or closure notification.
    """
    if not subscription.queue.empty():
        subscription.queue.get_nowait()
    subscription.queue.put_nowait(snapshot)


def publish(session: MonitorSession, snapshot: Snapshot) -> Snapshot:
    """Commit one version only while the owner still permits publication.

    Args:
        session: The exclusive owner of the calculation.
        snapshot: Completed domain data based on the previous committed snapshot.

    Returns:
        The committed snapshot, including its monotonic version.
    """
    if session.owner.stopped.is_set() or snapshot is session.snapshot:
        return session.snapshot
    session.snapshot = dataclasses.replace(
        snapshot,
        version=session.snapshot.version + 1,
    )
    for subscription in session.subscriptions:
        offer(subscription, session.snapshot)
    return session.snapshot


async def result_of(pending: Pending) -> Snapshot:
    """Retain admitted work when its original consumer is cancelled.

    Args:
        pending: The already admitted request.

    Returns:
        Its settled result.
    """
    return await pending.result


async def dispatch(session: MonitorSession) -> None:
    """Keep one request active while honoring priority at each admission boundary.

    Args:
        session: The owner of the request queue and evidence readers.
    """
    while session.pending:
        pending = heapq.heappop(session.pending)
        if pending.result.cancelled():
            continue
        pending.admitted.set()
        outcomes = await asyncio.gather(
            session.owner.run(
                functools.partial(execute, session, pending.request),
            ),
            return_exceptions=True,
        )
        result = outcomes[0]
        if isinstance(result, BaseException):
            pending.result.set_exception(result)
        else:
            pending.result.set_result(result or session.snapshot)


async def execute(session: MonitorSession, request: Request) -> Snapshot:
    """Keep file access and publication under the same resource owner.

    Args:
        session: The session whose operation is admitted.
        request: The domain operation selected by the scheduler.

    Returns:
        A complete published version or the unchanged final version after stop.
    """
    match request:
        case RefreshHealth():
            snapshot = await refresh_health(session)
        case RefreshRecords():
            session.records_requested = True
            snapshot = await refresh_records(session)
        case LoadOlder():
            snapshot = await load_older(session)
        case LoadRun(identifier=identifier):
            snapshot = await load_run(session, identifier)
        case RefreshReport():
            session.report_requested = True
            report = await asyncio.to_thread(
                peri_scribe.monitor.storage.read_report,
                session.report_path,
                session.snapshot.report,
            )
            snapshot = dataclasses.replace(session.snapshot, report=report)
        case _:
            snapshot = advance_clock(session)
    return publish(session, snapshot)


async def refresh_health(session: MonitorSession) -> Snapshot:
    """Publish full recent history and artifact observations as one health result.

    Args:
        session: The session holding exclusive evidence ownership.

    Returns:
        A candidate snapshot whose health evidence is complete.
    """
    now = datetime.datetime.now(datetime.UTC)
    history = await asyncio.to_thread(session.history_reader.catch_up, now)
    files = await asyncio.to_thread(
        peri_scribe.monitor.status.read_files,
        session.year_directory,
        session.kmz_path,
        session.report_path,
    )
    health = await asyncio.to_thread(
        peri_scribe.monitor.projection.refresh,
        history,
        files,
        now,
        session.snapshot.health,
    )
    session.reconcile_at = (
        time.monotonic()
        + peri_scribe.monitor.changes.RECONCILE_INTERVAL.m_as("seconds")
    )
    return dataclasses.replace(
        session.snapshot,
        history=history,
        files=files,
        health=health,
    )


async def refresh_records(session: MonitorSession) -> Snapshot:
    """Advance diagnostic evidence without sharing its cursor with health history.

    Args:
        session: The session holding exclusive evidence ownership.

    Returns:
        Newly retained records and their collection diagnostics.
    """
    batch = await asyncio.to_thread(session.follower.poll)
    records = session.snapshot.records
    if batch.records:
        records = await asyncio.to_thread(
            peri_scribe.monitor.model.append_records,
            records,
            batch.records,
        )
    session.files_changed |= not batch.caught_up
    return dataclasses.replace(
        session.snapshot,
        records=records,
        archives=batch.archives,
        errors=batch.errors,
    )


async def load_older(session: MonitorSession) -> Snapshot:
    """Merge archive evidence before the current stream without losing newer records.

    Args:
        session: The session holding exclusive evidence ownership.

    Returns:
        The extended record stream, or the current snapshot after archive exhaustion.
    """
    previous = session.snapshot
    path = next(
        (path for path in previous.archives if path not in previous.loaded_archives),
        None,
    )
    if path is None:
        return previous
    batch = await asyncio.to_thread(peri_scribe.monitor.storage.read_archive, path)
    current = sorted(
        (
            event
            for run in previous.records.runs
            for event in peri_scribe.monitor.model.evidence(run)
        ),
        key=lambda event: event.sequence,
    )
    records = await asyncio.to_thread(
        peri_scribe.monitor.model.append_records,
        peri_scribe.monitor.model.State(),
        (*batch.records, *(dict(event.fields) for event in current)),
    )
    return dataclasses.replace(
        previous,
        records=records,
        loaded_archives=previous.loaded_archives | {path},
        errors=batch.errors,
    )


async def load_run(session: MonitorSession, identifier: str) -> Snapshot:
    """Preserve the original event identities for a requested command's evidence.

    Args:
        session: The session holding exclusive evidence ownership.
        identifier: The command invocation to recover.

    Returns:
        Available evidence or an explicit collection failure.
    """
    try:
        run = await asyncio.to_thread(
            peri_scribe.monitor.history.load_run,
            session.year_directory / "logs",
            identifier,
        )
    except (OSError, EOFError, compression.zstd.ZstdError) as error:
        return dataclasses.replace(
            session.snapshot,
            evidence=None,
            errors=(f"Unable to load run: {error}",),
        )
    return dataclasses.replace(session.snapshot, evidence=run, errors=())


def advance_clock(session: MonitorSession) -> Snapshot:
    """Retain the same evidence cursor while time-dependent policies advance.

    Args:
        session: The session holding exclusive evidence ownership.

    Returns:
        Updated health, or the current snapshot before health becomes available.
    """
    previous = session.snapshot
    if previous.health is None or previous.files is None:
        return previous
    now = datetime.datetime.now(datetime.UTC)
    history = peri_scribe.monitor.history.append(
        session.history_reader.history,
        (),
        now,
    )
    session.history_reader.history = history
    health = peri_scribe.monitor.projection.refresh(
        history,
        previous.files,
        now,
        previous.health,
    )
    if health is previous.health:
        return previous
    return dataclasses.replace(previous, history=history, health=health)


async def watch(session: MonitorSession) -> None:
    """Coalesce native filesystem hints until the next reconciliation opportunity.

    Args:
        session: The observer owning notification lifetime.
    """
    async for _ in peri_scribe.monitor.changes.watch(
        session.year_directory,
        session.watching_stopped,
    ):
        session.files_changed = True


async def clock(session: MonitorSession) -> None:
    """Bound missed-notification recovery while allowing immediate shutdown.

    Args:
        session: The observer owning the reconciliation clock.
    """
    while not session.watching_stopped.is_set():
        try:
            await asyncio.wait_for(
                session.watching_stopped.wait(),
                CLOCK_INTERVAL.m_as("seconds"),
            )
        except TimeoutError:
            await session.tick()


def release(session: MonitorSession) -> None:
    """Retire every descriptor only after admitted work has relinquished ownership.

    Args:
        session: The session whose readers can no longer be accessed.
    """
    session.follower.close()
    session.history_reader.close()


async def finish(session: MonitorSession) -> None:
    """Retain cleanup through repeated cancellation and terminate every subscription.

    Args:
        session: The stopped session awaiting its final resource retirement.

    Raises:
        BaseExceptionGroup: After cleanup if any observation worker failed.
    """
    await session.owner.close(functools.partial(release, session))
    workers = (*session.observers,)
    if session.dispatcher is not None:
        workers = (*workers, session.dispatcher)
    outcomes = await asyncio.gather(*workers, return_exceptions=True)
    for subscription in tuple(session.subscriptions):
        subscription.close()
    failures = tuple(
        outcome for outcome in outcomes if isinstance(outcome, BaseException)
    )
    if failures:
        message = "Monitor observation failed"
        raise BaseExceptionGroup(message, failures)
