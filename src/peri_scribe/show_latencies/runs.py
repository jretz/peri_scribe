"""Compact run and snapshot evidence from a bounded stream of diagnostic logs."""

from __future__ import annotations

import contextlib
import dataclasses
import datetime
import json
import pathlib
import re
import typing

import peri_scribe.log_reading
from measurement_units import units


if typing.TYPE_CHECKING:
    import pint


COMMAND_EVENT = re.compile(rb'"event"\s*:\s*"(?:Starting|Finished) command"')
PHASE_EVENT = re.compile(rb'"event"\s*:\s*"(?:Starting|Finished) phase"')
EVIDENCE_PHASE = re.compile(
    rb'"(?:phase_path|phase)"\s*:\s*'
    rb'"(?:geography|kmz\.serialize-and-write-kmz|write-snapshot)"',
)


def includes_evidence(line: bytes) -> bool:
    """Avoid interpreting detailed diagnostic records that cannot affect the chart.

    Candidate fields are checked again after deserialization, so similarly named
    nested fields cannot become command or publication evidence.

    Args:
        line: One complete JSON log record.

    Returns:
        Whether the line may describe a command, geography, KMZ, or source snapshot.
    """
    return COMMAND_EVENT.search(line) is not None or (
        PHASE_EVENT.search(line) is not None and EVIDENCE_PHASE.search(line) is not None
    )


@dataclasses.dataclass(frozen=True, kw_only=True)
class Window:
    """Both bounds use the same clock reading and include their endpoints."""

    start: datetime.datetime
    end: datetime.datetime


@dataclasses.dataclass(frozen=True, kw_only=True)
class Run:
    """A completed invocation includes gate stops and failures after writing KMZ."""

    identifier: str
    started: datetime.datetime
    finished: datetime.datetime
    duration: pint.Quantity
    geography: datetime.datetime | None
    produced_kmz: bool


@dataclasses.dataclass(frozen=True, kw_only=True)
class KmzWrite:
    """Successful output consumes its inputs even if the command never finishes."""

    written: datetime.datetime
    geography: datetime.datetime | None
    finished: datetime.datetime | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class Evidence:
    """Source collection times connect retained snapshots to individual publications."""

    runs: tuple[Run, ...]
    snapshots: dict[str, datetime.datetime]
    kmz_writes: tuple[KmzWrite, ...] = ()


@dataclasses.dataclass(frozen=True, kw_only=True)
class Collection:
    """Mutable accumulators remain local to one chronological evidence read."""

    window: Window
    year: str | None
    starts: dict[str, datetime.datetime] = dataclasses.field(default_factory=dict)
    geography: dict[str | None, datetime.datetime] = dataclasses.field(
        default_factory=dict,
    )
    pending_writes: dict[str, list[int]] = dataclasses.field(default_factory=dict)
    kmz_writes: list[KmzWrite] = dataclasses.field(default_factory=list)
    snapshots: dict[str, datetime.datetime] = dataclasses.field(default_factory=dict)
    runs: list[Run] = dataclasses.field(default_factory=list)
    missing_starts: list[datetime.datetime] = dataclasses.field(default_factory=list)


def records(
    directory: pathlib.Path,
    window: Window,
) -> typing.Iterator[dict[str, object]]:
    """Retain only structural evidence after seeking the requested time window.

    Args:
        directory: A year's diagnostic log directory.
        window: The inclusive analysis window.

    Yields:
        Small command and phase records in chronological order.
    """
    # A copied production directory may use a different timezone from this machine.
    first_month = (window.start - datetime.timedelta(days=1)).strftime("%Y-%m")
    last_month = (window.end + datetime.timedelta(days=1)).strftime("%Y-%m")
    paths = [
        path
        for path in peri_scribe.log_reading.log_paths(directory)
        if first_month <= path.name[:7] <= last_month
    ]
    # A plain file covering the cutoff makes earlier archives unnecessary even at a
    # month boundary where the writer's timezone is not known.
    for path in reversed(paths):
        if path.suffix == ".zst":
            continue
        with contextlib.closing(peri_scribe.log_reading.complete_lines(path)) as lines:
            first = peri_scribe.log_reading.line_timestamp(next(lines, b""))
        if first is not None and first <= window.start:
            first_month = path.name[:7]
            break
    for path in paths:
        if path.name[:7] < first_month:
            continue
        for line in peri_scribe.log_reading.complete_lines(
            path,
            since=window.start,
            until=window.end,
            include=includes_evidence,
        ):
            fields = json.loads(line)
            if isinstance(fields, dict):
                yield fields


def relative_snapshot(fields: dict[str, object], year: str | None) -> str | None:
    """Identify the source directory without depending on the original machine's root.

    Args:
        fields: The snapshot completion's original path and feed.
        year: The retained year directory's name when it is a calendar year.

    Returns:
        The path relative to the actual source directory, or None for unrelated paths.
    """
    parts = pathlib.PurePosixPath(str(fields.get("path", ""))).parts
    feed = str(fields.get("feed", ""))
    for index in range(len(parts) - 2, -1, -1):
        if (
            parts[index] == "sources"
            and parts[index + 1] == feed
            and (year is None or (index > 0 and parts[index - 1] == year))
        ):
            return str(pathlib.PurePosixPath(*parts[index + 1 :]))
    return None


def complete_phase(
    state: Collection,
    fields: dict[str, object],
    timestamp: datetime.datetime,
    identifier: str,
) -> None:
    """Capture consumed inputs when KMZ writing succeeds, before reports can fail.

    Args:
        state: Invocation-local evidence accumulators.
        fields: A successful phase completion.
        timestamp: The completion's logged time.
        identifier: The command owning this phase.
    """
    if fields.get("phase_path") == "geography":
        state.geography[None] = state.geography.get(identifier, timestamp)
    if fields.get("phase_path") == "kmz.serialize-and-write-kmz":
        state.pending_writes.setdefault(identifier, []).append(len(state.kmz_writes))
        state.kmz_writes.append(
            KmzWrite(
                written=timestamp,
                geography=state.geography.get(identifier, state.geography.get(None)),
            ),
        )
    if fields.get("phase") == "write-snapshot" and fields.get("feed"):
        relative = relative_snapshot(fields, state.year)
        if relative is not None:
            state.snapshots.setdefault(relative, timestamp)


def complete_command(
    state: Collection,
    fields: dict[str, object],
    timestamp: datetime.datetime,
    identifier: str,
) -> None:
    """Attach an observed command endpoint only to writes from that invocation.

    Args:
        state: Invocation-local evidence accumulators.
        fields: A run command's completion.
        timestamp: Its logged endpoint, independently of duration availability.
        identifier: The command owning any pending writes.
    """
    writes = state.pending_writes.pop(identifier, ())
    for index in writes:
        state.kmz_writes[index] = dataclasses.replace(
            state.kmz_writes[index],
            finished=timestamp,
        )
    duration = fields.get("duration")
    if not isinstance(duration, dict):
        return
    elapsed = units.Quantity(duration["value"], duration["units"]).to("seconds")
    recorded_start = state.starts.pop(identifier, None)
    started = recorded_start or timestamp - datetime.timedelta(
        seconds=float(elapsed.magnitude),
    )
    if elapsed.magnitude < 0 or not state.window.start <= timestamp <= state.window.end:
        return
    if recorded_start is None:
        state.missing_starts.append(started)
    state.runs.append(
        Run(
            identifier=identifier,
            started=started,
            finished=timestamp,
            duration=elapsed,
            geography=state.geography.get(identifier, state.geography.get(None)),
            produced_kmz=bool(writes),
        ),
    )


def collect(
    entries: typing.Iterable[dict[str, object]],
    window: Window,
    *,
    year: str | None = None,
) -> tuple[Evidence, datetime.datetime | None]:
    """Keep completed runs and independent successful-write consumption evidence.

    Args:
        entries: Chronological command and phase records, including required context.
        window: The interval in which completed command durations are retained.
        year: The retained year directory's calendar year, when known.

    Returns:
        Run, write, and snapshot evidence, plus an estimated start needing context.
    """
    state = Collection(window=window, year=year)
    for fields in entries:
        timestamp = peri_scribe.log_reading.timestamp(fields.get("timestamp"))
        if timestamp is None:
            continue
        identifier = str(fields.get("run_id", "legacy"))
        event = fields.get("event")
        if event == "Starting command":
            state.starts[identifier] = timestamp
            state.geography.pop(identifier, None)
            state.pending_writes.pop(identifier, None)
        elif event == "Starting phase" and fields.get("phase_path") == "geography":
            state.geography[identifier] = timestamp
        elif event == "Finished phase" and fields.get("status") == "completed":
            complete_phase(state, fields, timestamp, identifier)
        elif event == "Finished command" and fields.get("command") == "run":
            complete_command(state, fields, timestamp, identifier)
    return (
        Evidence(
            runs=tuple(state.runs),
            snapshots=state.snapshots,
            kmz_writes=tuple(state.kmz_writes),
        ),
        min(state.missing_starts, default=None),
    )


def read(directory: pathlib.Path, window: Window) -> Evidence:
    """Recover a crossing run's full input history before attributing publications.

    A completion without its command start requires an earlier seek, even when rounded
    elapsed time places its inferred start inside the window. The preceding two seconds
    cover whole-second log timestamps and rounded durations when locating that start.

    Args:
        directory: A year's diagnostic log directory.
        window: The requested inclusive interval.

    Returns:
        Runs ending in the window and their source-collection and KMZ evidence.
    """
    year = (
        directory.parent.name if re.fullmatch(r"\d{4}", directory.parent.name) else None
    )
    evidence, missing_start = collect(records(directory, window), window, year=year)
    if missing_start is None:
        return evidence
    context = Window(
        start=min(window.start, missing_start) - datetime.timedelta(seconds=2),
        end=window.end,
    )
    return collect(records(directory, context), window, year=year)[0]
