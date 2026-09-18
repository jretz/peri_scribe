"""Compact evidence keeps health independent of the interactive log retention window."""

import collections.abc
import compression.zstd
import dataclasses
import datetime
import operator
import pathlib
import threading
import typing

import peri_scribe.monitor.events
import peri_scribe.monitor.model
import peri_scribe.monitor.storage


WINDOW = datetime.timedelta(hours=48)
BATCH_SIZE = 2000
STRUCTURAL_MESSAGES = {
    "Starting command",
    "Finished command",
    "Starting phase",
    "Finished phase",
    "Planned phases",
    "Skipped phases",
    "Another run owns this year; skipping invocation",
    "Required rebuild completed",
}


@dataclasses.dataclass(frozen=True, kw_only=True)
class Coverage:
    """Merged windows preserve timestamp coverage after verbose events are discarded."""

    start: datetime.datetime
    end: datetime.datetime


@dataclasses.dataclass(frozen=True, kw_only=True)
class History:
    """Recent evidence supports counts, recovery, and navigation."""

    state: peri_scribe.monitor.model.State = dataclasses.field(
        default_factory=peri_scribe.monitor.model.State,
    )
    coverage: tuple[Coverage, ...] = ()
    undated: int = 0
    errors: tuple[str, ...] = ()
    caught_up: bool = True
    retained_at: datetime.datetime | None = None
    expires: datetime.datetime | None = None


def important(fields: collections.abc.Mapping[str, object]) -> bool:
    """Retain diagnostic evidence while ordinary verbose messages stay on disk.

    Args:
        fields: A structured log record.

    Returns:
        Whether the record contributes to health or run reconstruction.
    """
    return bool(
        fields.get("exception")
        or fields.get("event") in STRUCTURAL_MESSAGES
        or str(fields.get("event", "")).startswith("Publication gate "),
    )


def last_time(run: peri_scribe.monitor.model.Run) -> datetime.datetime:
    """Order runs by evidence rather than their insertion into an archive scan.

    Args:
        run: A compact or full run.

    Returns:
        Its latest timestamp, or an aware minimum when none is known.
    """
    return max(
        (event.timestamp for event in run.events if event.timestamp),
        default=datetime.datetime.min.replace(tzinfo=datetime.UTC),
    )


def retain(
    state: peri_scribe.monitor.model.State,
    now: datetime.datetime,
) -> tuple[
    peri_scribe.monitor.model.Run,
    ...,
]:
    """Bound status history to recent runs while preserving undated diagnostics.

    Args:
        state: Compact evidence after ingesting another batch.
        now: The observation time determining the rolling window.

    Returns:
        Runs with recent or unknown timestamps, in observation order.
    """
    undated = datetime.datetime.min.replace(tzinfo=datetime.UTC)
    return tuple(
        run
        for timestamp, run in sorted(
            ((last_time(run), run) for run in state.runs),
            key=operator.itemgetter(0),
        )
        if timestamp == undated or timestamp >= now - WINDOW
    )


def append(
    history: History,
    records: tuple[dict[str, object], ...],
    now: datetime.datetime,
) -> History:
    """Preserve every recent exception while bounding ordinary event retention.

    Args:
        history: Previously collected health evidence.
        records: Complete records from a disjoint portion of a log.
        now: The observation time for retention.

    Returns:
        Updated immutable evidence with explicit timestamp coverage.
    """
    if not records:
        if (
            history.retained_at is not None
            and now >= history.retained_at
            and (history.expires is None or now <= history.expires)
        ):
            return history
        return expire(history, now)
    latest: dict[str, int] = {}
    timestamps = []
    undated = history.undated
    for index, fields in enumerate(records):
        latest[str(fields.get("run_id", "unattributed"))] = index
        timestamp = peri_scribe.monitor.events.timestamp(fields.get("timestamp"))
        if timestamp:
            timestamps.append(timestamp)
        else:
            undated += 1
    final = set(latest.values())
    state = peri_scribe.monitor.model.append_records(
        history.state,
        tuple(
            fields
            for index, fields in enumerate(records)
            if index in final or important(fields)
        ),
        bounded=False,
    )
    runs = tuple(
        dataclasses.replace(
            run,
            progress=(),
            events=tuple(
                event
                for event in run.events
                if event is run.events[-1] or important(event.fields)
            ),
        )
        for run in map(chronological_run, state.runs)
    )
    state = dataclasses.replace(state, runs=runs)
    return expire(
        dataclasses.replace(
            history,
            state=state,
            coverage=extend_coverage(history.coverage, timestamps),
            undated=undated,
        ),
        now,
    )


def extend_coverage(
    coverage: tuple[Coverage, ...],
    timestamps: list[datetime.datetime],
) -> tuple[Coverage, ...]:
    """Compress overlapping windows without letting future records mask recent ones.

    Args:
        coverage: Previous intervals when at least one record is within 48 hours.
        timestamps: Times from every record, including discarded verbose events.

    Returns:
        Disjoint inclusive coverage intervals in chronological order.
    """
    maximum = datetime.datetime.max.replace(tzinfo=datetime.UTC)
    periods = [
        *coverage,
        *(
            Coverage(
                start=timestamp,
                end=timestamp + WINDOW if timestamp <= maximum - WINDOW else maximum,
            )
            for timestamp in timestamps
        ),
    ]
    merged: list[Coverage] = []
    for period in sorted(periods, key=operator.attrgetter("start")):
        if merged and period.start <= merged[-1].end:
            merged[-1] = dataclasses.replace(
                merged[-1],
                end=max(merged[-1].end, period.end),
            )
        else:
            merged.append(period)
    return tuple(merged)


def expire(history: History, now: datetime.datetime) -> History:
    """Schedule retention work for the first run that can leave the window.

    Args:
        history: Evidence needing a retention check.
        now: The observation time for the inclusive rolling window.

    Returns:
        Retained evidence and its next possible expiry.
    """
    runs = retain(history.state, now)
    undated = datetime.datetime.min.replace(tzinfo=datetime.UTC)
    first = next((last_time(run) for run in runs if last_time(run) != undated), None)
    coverage = tuple(period for period in history.coverage if period.end >= now)
    maximum = datetime.datetime.max.replace(tzinfo=datetime.UTC)
    deadlines = [period.end for period in coverage if period.end < maximum]
    if first and first <= maximum - WINDOW:
        deadlines.append(first + WINDOW)
    return dataclasses.replace(
        history,
        state=history.state
        if runs == history.state.runs
        else dataclasses.replace(history.state, runs=runs),
        coverage=coverage,
        retained_at=now,
        expires=min(deadlines, default=None),
    )


def chronological_run(
    run: peri_scribe.monitor.model.Run,
) -> peri_scribe.monitor.model.Run:
    """Monthly reads can arrive out of order without moving the observed phase backward.

    Args:
        run: Evidence accumulated across current logs and archives.

    Returns:
        The run interpreted in observation order, retaining stable event identities.
    """
    ordered = tuple(
        sorted(
            run.events,
            key=lambda event: (
                event.timestamp or datetime.datetime.min.replace(tzinfo=datetime.UTC),
                event.sequence,
            ),
        ),
    )
    if ordered == run.events:
        return run
    replayed = peri_scribe.monitor.model.append_records(
        peri_scribe.monitor.model.State(),
        tuple(dict(event.fields) for event in ordered),
        bounded=False,
    ).runs[0]
    return dataclasses.replace(
        replayed,
        identifier=run.identifier,
        events=tuple(
            dataclasses.replace(original, path=updated.path)
            for original, updated in zip(ordered, replayed.events, strict=True)
        ),
    )


def records_from(path: pathlib.Path) -> typing.Iterator[dict[str, object]]:
    """Stream archives so loading historical evidence does not require their full text.

    Args:
        path: A plain or compressed monthly log.

    Yields:
        Complete nonempty records, including inspectable malformed lines.

    Raises:
        FileNotFoundError: Neither the requested log nor its rotated copy is available.
    """
    opener = compression.zstd.open if path.suffix == ".zst" else pathlib.Path.open
    try:
        stream = opener(path, "rt", encoding="utf-8", errors="replace")
    except FileNotFoundError:
        if path.suffix == ".zst":
            raise
        # Rotation can replace a discovered plain file before the reader opens it.
        stream = compression.zstd.open(
            path.with_suffix(path.suffix + ".zst"),
            "rt",
            encoding="utf-8",
            errors="replace",
        )
    with stream:
        for line in stream:
            if line.endswith("\n") and line.strip():
                yield peri_scribe.monitor.events.parse_record(line)


def record_batches(
    records: collections.abc.Iterable[dict[str, object]],
) -> typing.Iterator[tuple[dict[str, object], ...]]:
    """Bound ingestion memory without discarding a month's final partial batch.

    Args:
        records: A lazy stream of structured records.

    Yields:
        Batches of at most two thousand complete records.
    """
    batch: list[dict[str, object]] = []
    for record in records:
        batch.append(record)
        if len(batch) == BATCH_SIZE:
            yield tuple(batch)
            batch.clear()
    if batch:
        yield tuple(batch)


def log_paths(
    directory: pathlib.Path,
    *,
    since: datetime.datetime | None = None,
) -> tuple[pathlib.Path, ...]:
    """Prefer the active copy if compression briefly exposes both copies of a month.

    Args:
        directory: The watched log directory.
        since: Exclude months ending before this timestamp in the writer's timezone.

    Returns:
        Monthly logs in chronological filename order without duplicate months.
    """
    paths = {
        path.name.removesuffix(".zst"): path for path in directory.glob("*.jsonl.zst")
    }
    paths.update({path.name: path for path in directory.glob("*.jsonl")})
    first_month = since.astimezone().strftime("%Y-%m") if since else ""
    return tuple(paths[name] for name in sorted(paths) if name >= first_month)


def recent_records(
    records: collections.abc.Iterable[dict[str, object]],
    since: datetime.datetime,
) -> typing.Iterator[dict[str, object]]:
    """Limit health evidence while preserving diagnostics for undated records.

    Args:
        records: Records from a plain or compressed log.
        since: The inclusive start of the observation window.

    Yields:
        Recent records and records whose time cannot be established.
    """
    for fields in records:
        timestamp = peri_scribe.monitor.events.timestamp(fields.get("timestamp"))
        if timestamp is None or timestamp >= since:
            yield fields


def context_records(
    records: collections.abc.Iterable[dict[str, object]],
    cutoffs: collections.abc.Mapping[str, datetime.datetime],
    stopped: threading.Event,
) -> typing.Iterator[dict[str, object]]:
    """Recover skipped run context without duplicating the recent observation window.

    Args:
        records: Records from a plain or compressed log.
        cutoffs: Each selected run's earliest already loaded observation boundary.
        stopped: Cancellation shared with the reader's shutdown path.

    Yields:
        Older diagnostic and structural records belonging to the selected runs.
    """
    for fields in records:
        if stopped.is_set():
            return
        cutoff = cutoffs.get(str(fields.get("run_id") or ""))
        if cutoff is not None and important(fields):
            timestamp = peri_scribe.monitor.events.timestamp(fields.get("timestamp"))
            if timestamp is not None and timestamp < cutoff:
                yield fields


class Reader:
    """A separate cursor reads recent health evidence without disturbing browsing."""

    def __init__(self, directory: pathlib.Path) -> None:
        """Keep all file access at the observation boundary.

        Args:
            directory: The watched monthly logs.
        """
        self.directory = directory
        self.follower = peri_scribe.monitor.storage.Follower(directory, tail=False)
        self.months: set[str] = set()
        self.history = History()
        self.archive_errors: tuple[str, ...] = ()
        self.context_checked: set[str] = set()
        self.stopped = threading.Event()
        self.reading = threading.Lock()

    def catch_up(self, now: datetime.datetime) -> History:
        """Consume the backlog before publishing complete status evidence.

        Args:
            now: The observation time for the rolling window.

        Returns:
            Evidence at end of file, or the last batch before an error or shutdown.
        """
        with self.reading:
            while not self.stopped.is_set():
                history = self.poll(now)
                if history.caught_up or history.errors:
                    break
            return self.history

    def poll(self, now: datetime.datetime) -> History:
        """Seek recent evidence at startup and incrementally follow active files.

        Args:
            now: The observation time for the rolling window.

        Returns:
            Current evidence and any limitations on its coverage.
        """
        self.context_checked.intersection_update(
            run.identifier for run in self.history.state.runs
        )
        since = now - WINDOW
        for path in log_paths(self.directory, since=since):
            month = path.name.removesuffix(".zst")
            if month not in self.months and path.suffix == ".zst":
                try:
                    for batch in record_batches(
                        recent_records(records_from(path), since),
                    ):
                        if self.stopped.is_set():
                            return self.history
                        self.history = append(self.history, batch, now)
                except (OSError, EOFError, compression.zstd.ZstdError) as error:
                    self.archive_errors = (
                        *self.archive_errors,
                        f"{path.name}: {error}",
                    )
            self.months.add(month)
        batch = self.follower.poll(since=since)
        self.history = append(self.history, batch.records, now)
        if batch.caught_up:
            self.restore_context(now)
        self.history = dataclasses.replace(
            self.history,
            errors=(*self.archive_errors, *batch.errors),
            caught_up=batch.caught_up,
        )
        return self.history

    def restore_context(self, now: datetime.datetime) -> None:
        """Keep long-running commands recognizable after the recent-window seek.

        Args:
            now: The observation time used to load recent evidence.
        """
        # Catch-up can span multiple polls without replaying already ingested context.
        cutoffs = {
            run.identifier: min(
                (
                    now - WINDOW,
                    *(event.timestamp for event in run.events if event.timestamp),
                ),
            )
            for run in self.history.state.runs
            if run.identifier not in self.context_checked
            and any(event.fields.get("run_id") for event in run.events)
            and not any(event.message == "Starting command" for event in run.events)
        }
        self.context_checked = {run.identifier for run in self.history.state.runs}
        if not cutoffs:
            return
        for path in reversed(log_paths(self.directory)):
            if not cutoffs or self.stopped.is_set():
                break
            started: set[str] = set()
            try:
                for batch in record_batches(
                    context_records(
                        records_from(path),
                        cutoffs,
                        self.stopped,
                    ),
                ):
                    self.history = append(self.history, batch, now)
                    started.update(
                        str(fields["run_id"])
                        for fields in batch
                        if fields.get("event") == "Starting command"
                    )
            except (OSError, EOFError, compression.zstd.ZstdError) as error:
                self.archive_errors = (*self.archive_errors, f"{path.name}: {error}")
            for identifier in started:
                cutoffs.pop(identifier)

    def close(self) -> None:
        """Release active log descriptors when the monitor exits."""
        self.stopped.set()
        with self.reading:
            self.follower.close()


def load_run(directory: pathlib.Path, identifier: str) -> peri_scribe.monitor.model.Run:
    """Resolve a health link even after its full log rows leave interactive retention.

    Args:
        directory: The available monthly logs.
        identifier: The selected command's recorded identity.

    Returns:
        The full run, or an empty run if its records are no longer available.
    """
    state = peri_scribe.monitor.model.State()
    for path in log_paths(directory):
        for batch in record_batches(
            (
                fields
                for fields in records_from(path)
                if fields.get("run_id") == identifier
            ),
        ):
            state = peri_scribe.monitor.model.append_records(
                state,
                batch,
                bounded=False,
            )
    return next(iter(state.runs), peri_scribe.monitor.model.Run(identifier=identifier))
