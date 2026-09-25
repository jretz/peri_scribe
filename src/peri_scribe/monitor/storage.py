"""Read-only file adapters keep tailing and report refresh outside the UI model."""

import collections
import compression.zstd
import contextlib
import dataclasses
import datetime
import os
import pathlib
import typing

import peri_scribe.log_reading
import peri_scribe.monitor.events


MAXIMUM_READ_BYTES = 4 * 1024 * 1024
MAXIMUM_ARCHIVE_EVENTS = 10000


@dataclasses.dataclass(frozen=True, kw_only=True)
class Cursor:
    """An open file survives rotation until its last complete record is consumed."""

    stream: typing.BinaryIO
    partial: bytes = b""


@dataclasses.dataclass(frozen=True, kw_only=True)
class Batch:
    """A poll delivers records and diagnostics without writing to the watched logs."""

    records: tuple[dict[str, object], ...] = ()
    errors: tuple[str, ...] = ()
    archives: tuple[pathlib.Path, ...] = ()
    caught_up: bool = True


@dataclasses.dataclass(frozen=True, kw_only=True)
class Report:
    """A stable report snapshot carries the filesystem's actual modification time."""

    content: str = ""
    modified: datetime.datetime | None = None
    signature: tuple[int, int, int, int] | None = None
    error: str = ""


def read_cursor(
    cursor: Cursor,
    *,
    since: datetime.datetime | None = None,
) -> tuple[Cursor, tuple[dict[str, object], ...]]:
    """Buffer incomplete records and restart after truncation without merging writes.

    Args:
        cursor: A retained binary stream and its unfinished final record.
        since: The timestamp cutoff to restore if the writer truncates the log.

    Returns:
        An updated cursor and newly completed structured records.
    """
    if os.fstat(cursor.stream.fileno()).st_size < cursor.stream.tell():
        cursor.stream.seek(0)
        if since is not None:
            seek_since(cursor.stream, since)
        cursor = dataclasses.replace(cursor, partial=b"")
    lines = (cursor.partial + cursor.stream.read(MAXIMUM_READ_BYTES)).split(b"\n")
    return dataclasses.replace(cursor, partial=lines[-1]), tuple(
        peri_scribe.monitor.events.parse_record(line.decode("utf-8", errors="replace"))
        for line in lines[:-1]
        if line.strip()
    )


seek_since = peri_scribe.log_reading.seek_since


def open_cursor(
    path: pathlib.Path,
    *,
    tail: bool,
    since: datetime.datetime | None = None,
) -> tuple[tuple[int, int], Cursor]:
    """Limit startup reads while keeping new monthly logs complete.

    Args:
        path: A discovered monthly log.
        tail: Whether this is the initial scan of existing history.
        since: An inclusive timestamp cutoff taking precedence over the byte limit.

    Returns:
        The opened file's identity and its cursor.
    """
    with contextlib.ExitStack() as stack:
        stream = stack.enter_context(path.open("rb"))
        metadata = os.fstat(stream.fileno())
        if since is not None:
            seek_since(stream, since)
        elif tail and metadata.st_size > MAXIMUM_READ_BYTES:
            stream.seek(metadata.st_size - MAXIMUM_READ_BYTES)
            stream.readline()
        stack.pop_all()
    return (metadata.st_dev, metadata.st_ino), Cursor(stream=stream)


class Follower:
    """Own file handles at the I/O boundary while consumers receive plain batches."""

    def __init__(self, directory: pathlib.Path, *, tail: bool = True) -> None:
        """Keep watching independent of whether the logging directory exists yet.

        Args:
            directory: The year directory's monthly log folder.
            tail: Whether startup may omit older records from uncompressed logs.
        """
        self.directory = directory
        self.cursors: dict[tuple[int, int], Cursor] = {}
        self.started = False
        self.tail = tail

    def discover(
        self,
        path: pathlib.Path,
        since: datetime.datetime | None,
    ) -> tuple[int, int]:
        """Reuse known cursors so refreshes do not repeat the initial search.

        Args:
            path: A discovered monthly log.
            since: The earliest timestamp to seek in an unfamiliar file.

        Returns:
            The identity of the watched file.
        """
        metadata = path.stat()
        identity = metadata.st_dev, metadata.st_ino
        if identity not in self.cursors:
            identity, opened = open_cursor(
                path,
                tail=self.tail and not self.started,
                since=since,
            )
            self.cursors[identity] = opened
        return identity

    def poll(self, *, since: datetime.datetime | None = None) -> Batch:
        """Drain retained handles and discover newly published monthly logs.

        Args:
            since: The earliest timestamp to seek when opening a new log.

        Returns:
            Complete records, readable diagnostics, and available archived months.
        """
        current: set[tuple[int, int]] = set()
        errors: list[str] = []
        records: list[dict[str, object]] = []
        caught_up = True
        for path in sorted(self.directory.glob("????-??.jsonl")):
            try:
                current.add(self.discover(path, since))
            except OSError as error:
                errors.append(f"{path.name}: {error}")
        for identity, cursor in tuple(self.cursors.items()):
            try:
                updated, entries = read_cursor(cursor, since=since)
                exhausted = (
                    cursor.stream.tell() >= os.fstat(cursor.stream.fileno()).st_size
                )
            except OSError as error:
                errors.append(str(error))
            else:
                records.extend(entries)
                caught_up = caught_up and exhausted
                self.cursors[identity] = updated
                if identity not in current and exhausted:
                    cursor.stream.close()
                    del self.cursors[identity]
        self.started = True
        return Batch(
            records=tuple(records),
            errors=tuple(errors),
            archives=tuple(
                sorted(self.directory.glob("????-??.jsonl.zst"), reverse=True),
            ),
            caught_up=caught_up,
        )

    def close(self) -> None:
        """Release every retained descriptor when the observer exits."""
        for cursor in self.cursors.values():
            cursor.stream.close()
        self.cursors.clear()


def read_archive(path: pathlib.Path) -> Batch:
    """Load bounded historical context only when the observer requests an older month.

    Args:
        path: A compressed monthly log.

    Returns:
        The archive's most recent records or a diagnostic when it cannot be read.
    """
    try:
        with compression.zstd.open(
            path,
            "rt",
            encoding="utf-8",
            errors="replace",
        ) as stream:
            lines = collections.deque(stream, maxlen=MAXIMUM_ARCHIVE_EVENTS)
        return Batch(
            records=tuple(
                peri_scribe.monitor.events.parse_record(line)
                for line in lines
                if line.strip()
            ),
        )
    except (OSError, EOFError, compression.zstd.ZstdError) as error:
        return Batch(errors=(f"{path.name}: {error}",))


def read_report(path: pathlib.Path, previous: Report) -> Report:
    """Publish complete report replacements while retaining the current reading state.

    Args:
        path: The generated Markdown report.
        previous: The last published snapshot, used when a write is still in progress.

    Returns:
        The current content and file modification time, or a readable error state.
    """
    try:
        return stable_report(path, previous)
    except (OSError, UnicodeError) as error:
        return Report(error=f"Report unavailable: {error}")


def stable_report(path: pathlib.Path, previous: Report) -> Report:
    """Retain the previous snapshot if a report changes while it is being read.

    Args:
        path: The generated report file.
        previous: The last published snapshot.

    Returns:
        A complete report with its file metadata, or the previous stable snapshot.
    """
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        signature = before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns
        if signature == previous.signature:
            return previous
        content = stream.read().decode("utf-8")
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        return previous
    return Report(
        content=content,
        modified=datetime.datetime.fromtimestamp(after.st_mtime).astimezone(),
        signature=signature,
    )
