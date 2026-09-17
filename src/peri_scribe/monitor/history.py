"""Compact evidence keeps health independent of the interactive log retention window."""

import collections.abc
import compression.zstd
import dataclasses
import datetime
import pathlib
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
class History:
    """Recent evidence and older landmarks support counts, recovery, and navigation."""

    state: peri_scribe.monitor.model.State = dataclasses.field(
        default_factory=peri_scribe.monitor.model.State,
    )
    since: datetime.datetime | None = None
    undated: int = 0
    errors: tuple[str, ...] = ()
    caught_up: bool = True


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
    """Keep older recovery landmarks without retaining all historical run details.

    Args:
        state: Compact evidence after ingesting another batch.
        now: The observation time determining the rolling window.

    Returns:
        Recent runs and the latest run supplying each historical landmark.
    """
    runs = sorted(state.runs, key=last_time)
    anchors: dict[object, str] = {}
    for run in runs:
        anchors["command", run.command] = run.identifier
        if run.status == peri_scribe.monitor.model.Status.FAILED:
            anchors["failure", run.command] = run.identifier
        for event in run.events:
            if event.message == "Finished phase":
                anchors[event.path, event.fields.get("status")] = run.identifier
            elif event.message.startswith("Publication gate "):
                anchors["gate"] = run.identifier
    identifiers = set(anchors.values()) | {run.identifier for run in runs[-12:]}
    return tuple(
        run
        for run in runs
        if run.identifier in identifiers or last_time(run) >= now - WINDOW
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
    latest: dict[str, int] = {}
    timestamps = [history.since] if history.since else []
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
    return dataclasses.replace(
        history,
        state=dataclasses.replace(state, runs=retain(state, now)),
        since=min(timestamps) if timestamps else None,
        undated=undated,
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
    """
    opener = compression.zstd.open if path.suffix == ".zst" else pathlib.Path.open
    with opener(path, "rt", encoding="utf-8", errors="replace") as stream:
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


def log_paths(directory: pathlib.Path) -> tuple[pathlib.Path, ...]:
    """Prefer the active copy if compression briefly exposes both copies of a month.

    Args:
        directory: The watched log directory.

    Returns:
        Monthly logs in chronological filename order without duplicate months.
    """
    paths = {
        path.name.removesuffix(".zst"): path for path in directory.glob("*.jsonl.zst")
    }
    paths.update({path.name: path for path in directory.glob("*.jsonl")})
    return tuple(paths[name] for name in sorted(paths))


class Reader:
    """A separate cursor reads complete health history without disturbing browsing."""

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

    def poll(self, now: datetime.datetime) -> History:
        """Load each historical month once and incrementally follow active files.

        Args:
            now: The observation time for the rolling window.

        Returns:
            Current evidence and any limitations on its coverage.
        """
        for path in log_paths(self.directory):
            month = path.name.removesuffix(".zst")
            if month not in self.months and path.suffix == ".zst":
                try:
                    for batch in record_batches(records_from(path)):
                        self.history = append(self.history, batch, now)
                except (OSError, EOFError, compression.zstd.ZstdError) as error:
                    self.archive_errors = (
                        *self.archive_errors,
                        f"{path.name}: {error}",
                    )
            self.months.add(month)
        batch = self.follower.poll()
        self.history = dataclasses.replace(
            append(self.history, batch.records, now),
            errors=(*self.archive_errors, *batch.errors),
            caught_up=batch.caught_up,
        )
        return self.history

    def close(self) -> None:
        """Release active log descriptors when the monitor exits."""
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
