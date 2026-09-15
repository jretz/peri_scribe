"""Shared logging configuration and execution context for consistent diagnostics."""

import collections.abc
import compression.zstd
import contextlib
import dataclasses
import datetime
import enum
import fcntl
import functools
import json
import logging
import pathlib
import re
import shutil
import sys
import tempfile
import time
import typing

import click
import pint
import pyproj
import structlog

from peri_scribe.units import units


logger = structlog.get_logger()


def log_value(value: object) -> object:
    """Give console and JSON logs the same representations of application values.

    Args:
        value: A logged value, possibly inside a collection.

    Returns:
        The value with quantities, paths, coordinate systems, and dates normalized.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        value = {
            field.name: getattr(value, field.name)
            for field in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {name: log_value(item) for name, item in value.items()}
    if isinstance(value, (set, frozenset)):
        # A canonical baseline keeps incomparable or partially ordered values stable.
        value = sorted(
            value,
            key=lambda item: json.dumps(log_value(item), sort_keys=True, default=repr),
        )
        with contextlib.suppress(TypeError):
            value = sorted(value)
    if isinstance(value, (list, tuple)):
        return [log_value(item) for item in value]
    if isinstance(value, datetime.timedelta):
        value = value.total_seconds() * units.seconds
    if isinstance(value, pint.Quantity):
        unit_name = str(value.units)
        return {"value": float(value.magnitude), "units": unit_name}
    if isinstance(value, (enum.StrEnum, pathlib.PurePath, pyproj.CRS)):
        return str(value)
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    return value


def serialize_log_values(
    _logger: object,
    _method_name: str,
    event_dict: collections.abc.Mapping[str, object],
) -> dict[str, object]:
    """Normalize application fields before either console or JSON rendering.

    Args:
        _logger: The wrapped logger, required by structlog's processor interface.
        _method_name: The log method, required by structlog's processor interface.
        event_dict: The event and its structured fields.

    Returns:
        The event with serializable application fields and native exception metadata.
    """
    return {
        name: value if name == "exc_info" else log_value(value)
        for name, value in event_dict.items()
    }


def compress_log(path: pathlib.Path) -> None:
    """Publish a complete archive before removing its original log.

    Args:
        path: The closed monthly log, protected by the log directory's writer lock.
    """
    archive = path.with_suffix(".jsonl.zst")
    with tempfile.TemporaryDirectory(dir=path.parent) as directory:
        temporary = pathlib.Path(directory) / archive.name
        if archive.exists():
            shutil.copyfile(archive, temporary)
        with (
            path.open("rb") as source,
            compression.zstd.open(temporary, "ab", level=19) as destination,
        ):
            shutil.copyfileobj(source, destination)
        temporary.replace(archive)
    path.unlink()


def append_monthly_log(directory: pathlib.Path, entry: str) -> None:
    """Serialize writes and rotation across commands sharing a year directory.

    Args:
        directory: The directory holding monthly logs and their archives.
        entry: A rendered JSON event without its trailing newline.
    """
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".rotation.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        filename = datetime.datetime.now().astimezone().strftime("%Y-%m.jsonl")
        for path in sorted(directory.glob("*.jsonl")):
            if (
                re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])\.jsonl", path.name)
                and path.name < filename
            ):
                compress_log(path)
        with (directory / filename).open("a", encoding="utf-8") as stream:
            stream.write(entry + "\n")


def route_log_event(
    wrapped_logger: object,
    method_name: str,
    event_dict: collections.abc.Mapping[str, object],
    *,
    stderr_level: int,
    file_level: int,
    directory: pathlib.Path | None,
) -> collections.abc.Mapping[str, object]:
    """Render file events independently so stderr retains native exception formatting.

    Args:
        wrapped_logger: The wrapped logger passed through by structlog.
        method_name: The log method passed through by structlog.
        event_dict: The normalized event and its structured fields.
        stderr_level: The minimum numeric severity for stderr.
        file_level: The minimum numeric severity for the JSON log.
        directory: The monthly log directory, or None for stderr alone.

    Returns:
        The event for console rendering.

    Raises:
        structlog.DropEvent: When the event is below stderr's threshold.
    """
    level = logging.getLevelNamesMapping()[str(event_dict["level"]).upper()]
    if directory is not None and level >= file_level:
        file_event = structlog.processors.format_exc_info(
            wrapped_logger,
            method_name,
            dict(event_dict),
        )
        rendered = structlog.processors.JSONRenderer(allow_nan=False)(
            wrapped_logger,
            method_name,
            file_event,
        )
        append_monthly_log(directory, typing.cast("str", rendered))
    if level < stderr_level:
        raise structlog.DropEvent
    return event_dict


def configure_logging(
    stderr_log_level: str = "debug",
    file_log_level: str = "debug",
    *,
    year_directory: pathlib.Path | None = None,
) -> None:
    """Keep console diagnostics readable and retain structured records with the data.

    Args:
        stderr_log_level: The minimum severity for formatted stderr output.
        file_log_level: The minimum severity for monthly JSON files.
        year_directory: The command's data directory, or None to disable file logging.
    """
    stderr_level = logging.getLevelNamesMapping()[stderr_log_level.upper()]
    file_level = logging.getLevelNamesMapping()[file_log_level.upper()]
    directory = year_directory / "logs" if year_directory is not None else None
    structlog.configure(
        processors=[
            serialize_log_values,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%dT%H:%M:%S%z", utc=False),
            functools.partial(
                route_log_event,
                stderr_level=stderr_level,
                file_level=file_level,
                directory=directory,
            ),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            min(stderr_level, file_level) if directory is not None else stderr_level,
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )


@contextlib.contextmanager
def command_file_logging(context: click.Context) -> typing.Generator[None]:
    """Keep year-specific logs scoped to the command that owns that directory.

    Args:
        context: The command's parsed Click context, including its resolved directory.

    Yields:
        Control with file logging enabled when the command accepts a year directory.
    """
    configuration = structlog.get_config()
    year_directory = context.params.get("year_directory")
    try:
        if isinstance(year_directory, pathlib.Path):
            options = context.find_root().params
            configure_logging(
                options["stderr_log_level"],
                options["file_log_level"],
                year_directory=year_directory,
            )
        yield
    finally:
        structlog.configure(**configuration)


@contextlib.contextmanager
def log_execution(
    kind: typing.Literal["command", "phase"],
    name: str,
    **kwargs: object,
) -> typing.Generator[None]:
    """Make execution boundaries and elapsed time visible, including failed work.

    Args:
        kind: Whether the operation is a CLI command or a pipeline phase.
        name: The operation's CLI or phase name.
        kwargs: Additional context to include in the start log entry.

    Yields:
        Control to the operation being timed.
    """
    started_at = time.perf_counter() * units.seconds
    context = {kind: name}
    logger.info("Starting %s", kind, **context, **kwargs)
    status = "failed"
    try:
        yield
        status = "completed"
    finally:
        elapsed = time.perf_counter() * units.seconds - started_at
        logger.log(
            logging.ERROR if status == "failed" else logging.INFO,
            "Finished %s",
            kind,
            **context,
            duration=round(elapsed, 2),
            status=status,
        )


def command_line_parameters(context: click.Context) -> dict[str, object]:
    """Preserve explicitly supplied command and parent-group parameters in logs.

    Args:
        context: The invoked command's parsed Click context.

    Returns:
        The supplied parameter names and their parsed values.
    """
    parameters: dict[str, object] = {}
    current: click.Context | None = context
    while current is not None:
        for name, value in current.params.items():
            if (
                current.get_parameter_source(name)
                is click.core.ParameterSource.COMMANDLINE
            ):
                parameters.setdefault(name, value)
        current = current.parent
    return parameters


def log_command[**Parameters, Result](
    callback: typing.Callable[Parameters, Result],
) -> typing.Callable[Parameters, Result]:
    """Include the entire command callback in its execution logs.

    Args:
        callback: The command callback whose Click metadata must be preserved.

    Returns:
        The callback wrapped with command execution logging.
    """

    @functools.wraps(callback)
    def invoke(*args: Parameters.args, **kwargs: Parameters.kwargs) -> Result:
        """Keep command logs outside any nested pipeline phase logs.

        Args:
            args: Positional arguments forwarded to the wrapped command callback.
            kwargs: Keyword arguments forwarded to the wrapped command callback.

        Returns:
            The command callback's result.
        """
        context = click.get_current_context()
        with (
            command_file_logging(context),
            log_execution(
                "command",
                invoke.__name__.replace("_", "-"),
                parameters=command_line_parameters(context),
            ),
        ):
            return callback(*args, **kwargs)

    return invoke
