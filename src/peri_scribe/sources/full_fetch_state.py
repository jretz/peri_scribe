"""The recorded cadence of full fire-feed fetches for the run command."""

from __future__ import annotations

import dataclasses
import datetime
import json
import pathlib
import typing

import structlog

import peri_scribe.sources.snapshots


logger = structlog.get_logger()

STATE_FILENAME = "fetch_state.json"
STATE_VERSION = "2026-09-06"


@dataclasses.dataclass(frozen=True, kw_only=True)
class FullFetchState:
    """The completion time of the last successful full fire-feed fetch."""

    last_full_fetch: datetime.datetime


def state_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Return the path of the fetch state file for *year_directory*.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The path to the year's fetch state file.

    Examples:
        >>> state_path(pathlib.Path("data/2026"))
        PosixPath('data/2026/sources/fetch_state.json')
    """
    return (
        peri_scribe.sources.snapshots.sources_directory_path(year_directory)
        / STATE_FILENAME
    )


def full_fetch_is_due(
    *,
    interval: datetime.timedelta,
    current_time: datetime.datetime,
    last_full_fetch: datetime.datetime | None,
) -> bool:
    """Return whether a full fetch is due at *current_time*.

    A zero interval makes a full fetch due on every invocation, and no recorded full
    fetch makes one due, so both short-circuit the age comparison.

    Args:
        interval: The full fetch interval, a whole number of hours or days.
        current_time: The current time.
        last_full_fetch: The completion time of the last full fetch, or None when none
            is recorded.

    Returns:
        True when a full fetch is due.

    Examples:
        >>> from datetime import datetime, timedelta, timezone
        >>> full_fetch_is_due(
        ...     interval=timedelta(hours=12),
        ...     current_time=datetime(2026, 9, 6, tzinfo=timezone.utc),
        ...     last_full_fetch=datetime(2026, 9, 5, tzinfo=timezone.utc),
        ... )
        True
    """
    if interval == datetime.timedelta(0):
        return True
    if last_full_fetch is None:
        return True
    return current_time - last_full_fetch >= interval


def read_state(path: pathlib.Path) -> FullFetchState | None:
    """Read the stored fetch state, or None when no state is stored.

    A missing state file returns None, which the caller treats as a due full fetch.
    Content that cannot be read as valid fetch state is an error, so the operator sees
    the problem instead of it being silently discarded.

    Args:
        path: The fetch state file.

    Returns:
        The stored fetch state, or None when the file does not exist.
    """
    if not path.exists():
        return None
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return malformed_state_error(path, error)
    if not isinstance(content, dict):
        return malformed_state_error(
            path,
            ValueError(f"state must be a JSON object, not {type(content).__name__}"),
        )
    if content.get("version") != STATE_VERSION:
        return malformed_state_error(
            path,
            ValueError(f"unrecognized version {content.get('version')!r}"),
        )
    try:
        timestamp = parsed_timestamp(content.get("last_full_fetch"))
    except (TypeError, ValueError) as error:
        return malformed_state_error(path, error)
    return FullFetchState(last_full_fetch=timestamp)


def parsed_timestamp(value: object) -> datetime.datetime:
    """Return *value* parsed as an ISO 8601 timestamp with a timezone.

    Args:
        value: The decoded ``last_full_fetch`` value.

    Returns:
        The parsed timestamp.

    Raises:
        TypeError: When *value* is not a string.
        ValueError: When *value* is not an ISO 8601 timestamp with a timezone.
    """
    if not isinstance(value, str):
        message = (
            "last_full_fetch must be an ISO 8601 timestamp string, "
            f"not {type(value).__name__}"
        )
        raise TypeError(message)
    try:
        timestamp = datetime.datetime.fromisoformat(value)
    except ValueError as error:
        message = f"last_full_fetch {value!r} is not an ISO 8601 timestamp"
        raise ValueError(message) from error
    if timestamp.tzinfo is None:
        message = f"last_full_fetch {value!r} has no timezone"
        raise ValueError(message)
    return timestamp


def malformed_state_error(path: pathlib.Path, error: Exception) -> typing.Never:
    """Log and raise an error for state that cannot be used.

    Args:
        path: The fetch state file.
        error: The underlying error describing the unusable state.

    Raises:
        ValueError: Always, with a message describing the unusable state.
    """
    message = f"Malformed fetch state at {path}: {error}"
    logger.error("Malformed fetch state", path=path, error=str(error))
    raise ValueError(message) from error


def write_state(
    path: pathlib.Path,
    *,
    last_full_fetch: datetime.datetime,
) -> None:
    """Atomically store *last_full_fetch* as the fetch state at *path*.

    The JSON is written to a temporary file next to *path* and moved into place, so an
    interrupted write leaves the stored state untouched. Any needed parent directories
    are created.

    Args:
        path: The fetch state file.
        last_full_fetch: The completion time of the last successful full fetch.

    Raises:
        ValueError: When *last_full_fetch* has no timezone.
    """
    if last_full_fetch.tzinfo is None:
        message = "last_full_fetch must be a timezone-aware timestamp"
        raise ValueError(message)
    content = {
        "version": STATE_VERSION,
        "last_full_fetch": utc_timestamp_text(last_full_fetch),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(json.dumps(content), encoding="utf-8")
    temporary_path.replace(path)


def utc_timestamp_text(timestamp: datetime.datetime) -> str:
    """Return *timestamp* rendered as an ISO 8601 UTC timestamp ending in Z.

    The state stores UTC, so an aware timestamp in another timezone is converted.

    Args:
        timestamp: The timestamp to render.

    Returns:
        The ISO 8601 UTC rendering.
    """
    return timestamp.astimezone(datetime.UTC).isoformat().replace("+00:00", "Z")
