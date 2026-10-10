"""Shared, bounded readers preserve diagnostic occurrences through clock changes.

Algorithm reasoning and contracts:
[Log retention](../../docs/algorithms/log-retention.md)
"""

import compression.zstd
import contextlib
import datetime
import fcntl
import os
import pathlib
import re
import typing

import peri_scribe.logging


JSON_TOKENS = re.compile(rb'"(?:[^"\\]|\\.)*"|[{}\[\]]')


def timestamp(value: object) -> datetime.datetime | None:
    """Normalize timestamps so mixed timezone records can share a run timeline.

    Args:
        value: A possibly absent or damaged timestamp field.

    Returns:
        An aware timestamp, or None when no reliable timestamp is available.
    """
    try:
        parsed = datetime.datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed.replace(tzinfo=datetime.UTC) if parsed.tzinfo is None else parsed


def line_timestamp(line: bytes) -> datetime.datetime | None:
    """Find the root timestamp without deserializing a record's other fields.

    String tokens protect escaped quotes and braces in messages; nesting depth keeps
    source metadata and exception timestamps from moving the search boundary.

    Args:
        line: One JSON log record, possibly malformed.

    Returns:
        Its root timestamp, or None if unavailable.
    """
    depth = 0
    for token in JSON_TOKENS.finditer(line):
        value = token.group()
        if value in {b"{", b"["}:
            depth += 1
        elif value in {b"}", b"]"}:
            depth -= 1
        elif depth == 1 and value == b'"timestamp"':
            match = re.match(rb'\s*:\s*"([^"\\]*)"', line[token.end() :])
            if match:
                return timestamp(match[1].decode("ascii", errors="replace"))
    return None


def timestamp_after(
    stream: typing.BinaryIO,
    offset: int,
    end: int,
) -> datetime.datetime | None:
    """Probe complete records so byte offsets cannot split UTF-8 or JSON values.

    Args:
        stream: An uncompressed log whose records retain their original timestamps.
        offset: The binary search probe's byte offset.
        end: The file size observed before searching.

    Returns:
        The next usable timestamp, leaving the stream just after its record.
    """
    stream.seek(max(0, offset - 1))
    if offset:
        stream.readline(end - stream.tell())
    while stream.tell() < end:
        line = stream.readline(end - stream.tell())
        if not line.endswith(b"\n"):
            return None
        timestamp = line_timestamp(line)
        if timestamp is not None:
            return timestamp
    return None


def seek_since(stream: typing.BinaryIO, since: datetime.datetime) -> None:
    """Retire only an older prefix, preserving later records through clock rollback.

    Undated records after the prefix's last older timestamp remain available for
    diagnostics. An unfinished final line remains available for its writer to finish.

    Args:
        stream: A seekable, uncompressed log with arbitrary timestamp order.
        since: The inclusive timestamp cutoff.
    """
    lower = 0
    end = stream.seek(0, os.SEEK_END)
    stream.seek(0)
    while (time := timestamp_after(stream, stream.tell(), end)) is not None:
        if time >= since:
            break
        lower = stream.tell()
    stream.seek(lower)


def log_paths(
    directory: pathlib.Path,
    *,
    since: datetime.datetime | None = None,
) -> tuple[pathlib.Path, ...]:
    """Choose one representative for each month, including its retained archive.

    Args:
        directory: The watched log directory.
        since: Exclude months ending before this timestamp in the writer's timezone.

    Returns:
        Monthly logs in chronological filename order without duplicate months.
    """
    paths = {
        path.name.removesuffix(".zst"): path
        for path in directory.glob("????-??.jsonl.zst")
    }
    paths.update({path.name: path for path in directory.glob("????-??.jsonl")})
    first_month = since.astimezone().strftime("%Y-%m") if since else ""
    return tuple(paths[name] for name in sorted(paths) if name >= first_month)


@contextlib.contextmanager
def read_lock(directory: pathlib.Path) -> typing.Generator[None]:
    """Share the writer's lock without creating files in a watched directory.

    Args:
        directory: A log directory with a stable writer lock, or an inactive copy.

    Yields:
        A read interval excluding cooperating appenders and rotators.
    """
    with contextlib.ExitStack() as stack:
        try:
            lock = stack.enter_context((directory / ".rotation.lock").open("rb"))
        except FileNotFoundError:
            pass
        else:
            fcntl.flock(lock, fcntl.LOCK_SH)
        yield


def log_components(path: pathlib.Path) -> tuple[pathlib.Path, ...]:
    """Select the complete monthly history while its shared lock is held.

    A committed receipt identifies physical source copies already present in the
    archive. Without that receipt, plain records are distinct later occurrences.

    Args:
        path: Either representation of one monthly log.

    Returns:
        Ordered, nonoverlapping representations of the month's retained records.

    Raises:
        OSError: A receipt does not authenticate the retained files.
        FileNotFoundError: Neither representation of the month exists.
    """
    plain = path.with_suffix("") if path.suffix == ".zst" else path
    archive = plain.with_suffix(plain.suffix + ".zst")
    try:
        committed = peri_scribe.logging.rotation_committed(plain)
    except ValueError as error:
        raise OSError(str(error)) from error
    candidates = (archive,) if committed else (archive, plain)
    retained = tuple(candidate for candidate in candidates if candidate.exists())
    if not retained:
        raise FileNotFoundError(path)
    return retained


def complete_lines(
    path: pathlib.Path,
    *,
    since: datetime.datetime | None = None,
    until: datetime.datetime | None = None,
    include: typing.Callable[[bytes], bool] | None = None,
) -> typing.Generator[bytes]:
    """Read one coherent month across archived records and later plain appends.

    The shared lock spans iteration so publication cannot move occurrences between
    the two representations during a read. Close abandoned iterators promptly.

    Args:
        path: A representative plain or compressed monthly log.
        since: Inclusive lower bound; undated lines remain available to diagnostics.
        until: Inclusive upper bound applied independently to each dated occurrence.
        include: Optional inexpensive filter before timestamp extraction.

    Yields:
        Complete, nonempty lines inside the requested bounds and undated lines.
    """
    with read_lock(path.parent):
        for component in log_components(path):
            yield from component_lines(
                component,
                since=since,
                until=until,
                include=include,
            )


def component_lines(
    path: pathlib.Path,
    *,
    since: datetime.datetime | None = None,
    until: datetime.datetime | None = None,
    include: typing.Callable[[bytes], bool] | None = None,
) -> typing.Generator[bytes]:
    """Stream one selected representation without materializing its complete archive.

    Args:
        path: A component selected while the log directory's shared lock is held.
        since: Inclusive lower bound; undated lines remain available to diagnostics.
        until: Inclusive upper bound applied independently to each dated occurrence.
        include: Optional inexpensive filter before timestamp extraction.

    Yields:
        Complete, nonempty lines inside the requested bounds and undated lines.
    """
    compressed = path.suffix == ".zst"
    with compression.zstd.open(path, "rb") if compressed else path.open("rb") as stream:
        if since is not None and not compressed:
            seek_since(typing.cast("typing.BinaryIO", stream), since)
        for line in stream:
            if not line.endswith(b"\n") or not line.strip():
                continue
            if include is not None and not include(line):
                continue
            time = (
                line_timestamp(line) if since is not None or until is not None else None
            )
            if time is not None:
                if until is not None and time > until:
                    continue
                if since is not None and time < since:
                    continue
            yield line
