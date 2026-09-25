"""Shared, bounded readers for chronological plain and Zstandard diagnostic logs."""

import compression.zstd
import datetime
import os
import pathlib
import re
import typing


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
        stream: A chronological, uncompressed log.
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
    """Binary search chronological logs without parsing their entire old prefix.

    Undated records after the last older timestamp remain available for diagnostics,
    and an unfinished final line remains available when its writer completes it.

    Args:
        stream: A seekable, uncompressed log with ordered timestamps.
        since: The inclusive timestamp cutoff.
    """
    # The writer timestamps under its lock; backward system-clock moves are an
    # acceptable ordering risk for this monitor's recent-history search.
    lower = 0
    end = upper = stream.seek(0, os.SEEK_END)
    while lower < upper:
        middle = (lower + upper) // 2
        timestamp = timestamp_after(stream, middle, end)
        if timestamp is not None and timestamp < since:
            lower = stream.tell()
        else:
            upper = middle
    stream.seek(lower)


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
        path.name.removesuffix(".zst"): path
        for path in directory.glob("????-??.jsonl.zst")
    }
    paths.update({path.name: path for path in directory.glob("????-??.jsonl")})
    first_month = since.astimezone().strftime("%Y-%m") if since else ""
    return tuple(paths[name] for name in sorted(paths) if name >= first_month)


def complete_lines(
    path: pathlib.Path,
    *,
    since: datetime.datetime | None = None,
    until: datetime.datetime | None = None,
    include: typing.Callable[[bytes], bool] | None = None,
) -> typing.Generator[bytes]:
    """Seek plain files and skim decompressed lines before decoding eligible JSON.

    Archives are read incrementally, including concatenated Zstandard frames. An
    active file's incomplete last record is left for its writer to finish.

    Args:
        path: A plain or compressed monthly log.
        since: Inclusive lower bound; undated lines remain available to diagnostics.
        until: Inclusive upper bound in a chronologically ordered file.
        include: Optional inexpensive filter before timestamp extraction. Reading
            stops at the first included, dated record beyond the upper bound.

    Yields:
        Complete, nonempty lines inside the requested bounds and undated lines.

    Raises:
        FileNotFoundError: Neither the requested log nor its rotated copy exists.
    """
    compressed = path.suffix == ".zst"
    try:
        stream = compression.zstd.open(path, "rb") if compressed else path.open("rb")
    except FileNotFoundError:
        if compressed:
            raise
        stream = compression.zstd.open(path.with_suffix(path.suffix + ".zst"), "rb")
        compressed = True
    with stream:
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
                    break
                if since is not None and time < since:
                    continue
            yield line
