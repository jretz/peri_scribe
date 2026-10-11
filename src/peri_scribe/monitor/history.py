"""Compact evidence keeps health independent of the interactive log retention window.

Algorithm reasoning and contracts:
[Monitor evidence](../../../docs/algorithms/monitor-evidence.md)
"""

import collections
import collections.abc
import compression.zstd
import dataclasses
import datetime
import operator
import pathlib
import threading
import typing
import weakref

import peri_scribe.log_reading
import peri_scribe.monitor.events
import peri_scribe.monitor.model
import peri_scribe.monitor.storage


WINDOW = datetime.timedelta(hours=48)
BATCH_SIZE = 2000
MAXIMUM_NORMALIZED_RUNS = 4096
NORMALIZED_RUNS: collections.OrderedDict[
    int,
    weakref.ReferenceType[peri_scribe.monitor.model.Run],
] = collections.OrderedDict()
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
    return run.last_timestamp


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
    runs = tuple(compact_run(run) for run in state.runs)
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
    maximum_start = maximum - WINDOW
    periods = [(period.start, period.end) for period in coverage]
    periods.extend(
        (timestamp, timestamp + WINDOW if timestamp <= maximum_start else maximum)
        for timestamp in timestamps
    )
    ordered = iter(sorted(periods, key=operator.itemgetter(0)))
    first = next(ordered, None)
    if first is None:
        return ()
    merged: list[Coverage] = []
    current_start, current_end = first
    for start, end in ordered:
        if start <= current_end:
            current_end = max(current_end, end)
        else:
            merged.append(Coverage(start=current_start, end=current_end))
            current_start, current_end = start, end
    merged.append(Coverage(start=current_start, end=current_end))
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


def compact_run(
    run: peri_scribe.monitor.model.Run,
) -> peri_scribe.monitor.model.Run:
    """Reuse normalized immutable runs without retaining discarded run histories.

    Args:
        run: Newly reconstructed or previously compacted evidence.

    Returns:
        Chronological structural evidence and its most recent ordinary event.
    """
    reference = NORMALIZED_RUNS.get(id(run))
    if reference is not None and reference() is run:
        return run
    ordered = chronological_run(run)
    compacted = dataclasses.replace(
        ordered,
        progress=(),
        events=tuple(
            event
            for event in ordered.events
            if event is ordered.events[-1] or important(event.fields)
        ),
    )
    NORMALIZED_RUNS[id(compacted)] = weakref.ref(compacted)
    if len(NORMALIZED_RUNS) > MAXIMUM_NORMALIZED_RUNS:
        NORMALIZED_RUNS.popitem(last=False)
    return compacted


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
    """
    yield from decoded_records(peri_scribe.log_reading.complete_lines(path))


def decoded_records(
    lines: collections.abc.Iterable[bytes],
) -> typing.Iterator[dict[str, object]]:
    """Preserve malformed diagnostics from complete selected log lines.

    Args:
        lines: Complete records from a coherent monthly read or selected component.

    Yields:
        Structured records with replacement characters for damaged UTF-8.
    """
    for line in lines:
        yield peri_scribe.monitor.events.parse_record(
            line.decode("utf-8", errors="replace"),
        )


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


log_paths = peri_scribe.log_reading.log_paths


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


def reverse_lines(
    stream: typing.BinaryIO,
    end: int,
    stopped: threading.Event,
    *,
    block_size: int = 64 * 1024,
) -> typing.Iterator[bytes]:
    """Recover nearby context without retaining unrelated earlier records.

    Args:
        stream: An uncompressed component protected by the reader's shared lock.
        end: The byte immediately after a complete record's newline, or zero.
        stopped: Cancellation shared with the owning reader.
        block_size: Maximum bytes read at once, independent of individual line size.

    Yields:
        Complete nonempty records in reverse file order, without their newlines.
    """
    remaining = end
    fragments: list[bytes] = []
    while remaining and not stopped.is_set():
        size = min(block_size, remaining)
        remaining -= size
        stream.seek(remaining)
        parts = stream.read(size).split(b"\n")
        if len(parts) == 1:
            fragments.append(parts[0])
            continue
        ending = parts.pop() + b"".join(reversed(fragments))
        fragments = [parts[0]]
        if ending.strip():
            yield ending
        for line in reversed(parts[1:]):
            if stopped.is_set():
                return
            if line.strip():
                yield line
    if not stopped.is_set() and (first := b"".join(reversed(fragments))).strip():
        yield first


def backward_context(
    path: pathlib.Path,
    cutoffs: collections.abc.Mapping[str, datetime.datetime],
    stopped: threading.Event,
) -> tuple[dict[str, object], ...] | None:
    """Use local command starts only when the whole selected context is available.

    A command ID starts with its unique start record. Collecting before publication
    permits a streamed fallback when a start belongs to another month or archive.

    Args:
        path: A monthly representative selected under the reader's shared lock.
        cutoffs: The exclusive upper timestamp boundary for each missing command.
        stopped: Cancellation shared with the owning reader.

    Returns:
        Complete selected context in file order, or None to use streamed recovery.
    """
    if not cutoffs or stopped.is_set():
        return ()
    if path.suffix == ".zst" or peri_scribe.log_reading.log_components(path) != (path,):
        return None
    pending = set(cutoffs)
    selected = []
    with path.open("rb") as stream:
        peri_scribe.log_reading.seek_since(stream, max(cutoffs.values()))
        for line in reverse_lines(stream, stream.tell(), stopped):
            if stopped.is_set():
                return ()
            fields = peri_scribe.monitor.events.parse_record(
                line.decode("utf-8", errors="replace"),
            )
            identifier = str(fields.get("run_id") or "")
            if identifier not in pending or not important(fields):
                continue
            timestamp = peri_scribe.monitor.events.timestamp(fields.get("timestamp"))
            if timestamp is None or timestamp >= cutoffs[identifier]:
                continue
            selected.append(fields)
            if fields.get("event") == "Starting command":
                pending.remove(identifier)
                if not pending:
                    return tuple(reversed(selected))
    return () if stopped.is_set() else None


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
        self.archive_signatures: dict[pathlib.Path, tuple[int, int, int, int]] = {}
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
        try:
            with peri_scribe.log_reading.read_lock(self.directory):
                return self.poll_locked(now)
        except OSError as error:
            self.history = dataclasses.replace(
                self.history,
                errors=(*self.archive_errors, str(error)),
                caught_up=False,
            )
            return self.history

    def poll_locked(self, now: datetime.datetime) -> History:
        """Hand archived prefixes to the follower within one coherent read interval.

        Args:
            now: The observation time for the rolling window.

        Returns:
            Current evidence after archive selection and plain cursor discovery.
        """
        archives = {
            path: (
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_size,
                metadata.st_mtime_ns,
            )
            for path in self.directory.glob("????-??.jsonl.zst")
            for metadata in (path.stat(),)
        }
        if any(
            path.name.removesuffix(".zst") in self.months
            and self.archive_signatures.get(path) != signature
            for path, signature in archives.items()
        ):
            self.follower.close()
            self.follower = peri_scribe.monitor.storage.Follower(
                self.directory,
                tail=False,
            )
            self.months.clear()
            self.history = History()
            self.archive_errors = ()
            self.context_checked.clear()
        self.archive_signatures = archives
        self.context_checked.intersection_update(
            run.identifier for run in self.history.state.runs
        )
        since = now - WINDOW
        for path in log_paths(self.directory, since=since):
            month = path.name.removesuffix(".zst")
            if month not in self.months:
                try:
                    archive = next(
                        (
                            component
                            for component in peri_scribe.log_reading.log_components(
                                path,
                            )
                            if component.suffix == ".zst"
                        ),
                        None,
                    )
                    lines = (
                        peri_scribe.log_reading.component_lines(archive)
                        if archive is not None
                        else ()
                    )
                    for batch in record_batches(
                        recent_records(decoded_records(lines), since),
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
                records = backward_context(path, cutoffs, self.stopped)
                for batch in record_batches(
                    records
                    if records is not None
                    else context_records(
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
