"""Shared logging configuration and execution context for consistent diagnostics.

Algorithm reasoning and contracts:
[Log retention](../../docs/algorithms/log-retention.md)
[Update journal](../../docs/algorithms/update-journal.md)
[Monitor evidence](../../docs/algorithms/monitor-evidence.md)
"""

from __future__ import annotations

import collections.abc
import compression.zstd
import contextlib
import contextvars
import datetime
import fcntl
import functools
import hashlib
import importlib
import json
import logging
import os
import pathlib
import re
import shutil
import sys
import tempfile
import time
import types
import typing
import uuid

import peri_scribe.phases
import peri_scribe.pipeline_stages


if typing.TYPE_CHECKING:
    import click
    import structlog

    import peri_scribe.rotation_types as receipt_types

    RotationReceipt = receipt_types.RotationReceipt
    logger: structlog.typing.FilteringBoundLogger


MAXIMUM_LOG_SEGMENT_BYTES = 16 * 1024 * 1024
SEGMENT_PATTERN = re.compile(r"[0-9]{4}-(0[1-9]|1[0-2])\.[0-9]{12,}\.jsonl")
ROTATION_RECEIPT_PATTERN = re.compile(
    rb'\{"version":1,"source_checksum":"([0-9a-f]{64})",'
    rb'"archive_checksum":(?:null|"([0-9a-f]{64})"),'
    rb'"target_checksum":"([0-9a-f]{64})"\}',
)
PHASE_PATH: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar(
    "phase_path",
    default=(),
)
PHASE_INSTANCES: contextvars.ContextVar[peri_scribe.phases.Path] = (
    contextvars.ContextVar(
        "phase_instances",
        default=(),
    )
)
RUN_CONTEXT: contextvars.ContextVar[dict[str, object] | None] = contextvars.ContextVar(
    "run_context",
    default=None,
)


@functools.cache
def structured_logging() -> types.ModuleType:
    """Load rendering and diagnostic support when it is used.

    Returns:
        The structured logging library.
    """
    return importlib.import_module("structlog")


@functools.cache
def execution_logger() -> structlog.typing.FilteringBoundLogger:
    """Create the logger when an execution event needs it.

    Returns:
        The logger for command and phase events.
    """
    return structured_logging().get_logger()


def __getattr__(name: str) -> object:
    """Resolve the existing receipt model and logger on access.

    Args:
        name: Requested module attribute.

    Returns:
        The receipt model or execution logger.

    Raises:
        AttributeError: The module has no attribute by that name.
    """
    if name == "RotationReceipt":
        return importlib.import_module("peri_scribe.rotation_types").RotationReceipt
    if name == "logger":
        return execution_logger()
    raise AttributeError(name)


@functools.cache
def value_module() -> types.ModuleType:
    """Load quantity and coordinate formatting when rendering or timing needs it.

    Returns:
        The application value formatter and monotonic-clock adapter.
    """
    return importlib.import_module("peri_scribe.log_values")


def log_value(value: object) -> object:
    """Give console and JSON logs the same representations of application values.

    Args:
        value: A logged value, possibly inside a collection.

    Returns:
        The value with quantities, paths, coordinate systems, and dates normalized.
    """
    return value_module().log_value(value)


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
    context = dict(RUN_CONTEXT.get() or {})
    if PHASE_INSTANCES.get():
        context.update(
            phase_path=".".join(PHASE_PATH.get()),
            phase_segments=PHASE_INSTANCES.get(),
        )
    return {
        name: value if name == "exc_info" else log_value(value)
        for name, value in (context | dict(event_dict)).items()
    }


def batch_identifier(line: bytes) -> str | None:
    """Identify journaled records while preserving ordinary diagnostic log content.

    Args:
        line: One retained log line, including any unstructured legacy content.

    Returns:
        The batch identity, or None for records without a journal identity.
    """
    with contextlib.suppress(json.JSONDecodeError):
        record = json.loads(line)
        if isinstance(record, dict) and isinstance(record.get("batch_id"), str):
            return record["batch_id"]
    return None


def rotation_checksums(raw: bytes) -> tuple[str, str | None, str]:
    """Read the checksums written by rotation and validate alternate receipts.

    Args:
        raw: The complete stored receipt.

    Returns:
        The source, previous archive, and target archive checksums.
    """
    match = ROTATION_RECEIPT_PATTERN.fullmatch(raw)
    if match is None:
        model = importlib.import_module("peri_scribe.rotation_types").RotationReceipt
        receipt = model.model_validate_json(raw)
        return (
            receipt.source_checksum,
            receipt.archive_checksum,
            receipt.target_checksum,
        )
    source, archive, target = match.groups()
    return (
        source.decode(),
        None if archive is None else archive.decode(),
        target.decode(),
    )


def rotation_receipt_path(path: pathlib.Path) -> pathlib.Path:
    """Keep the rotation receipt available after its plain source log is removed.

    Args:
        path: The plain monthly log.

    Returns:
        Its persistent rotation receipt path.
    """
    return path.with_name(path.name + ".rotation.json")


def file_checksum(path: pathlib.Path) -> str | None:
    """Checksum the stored bytes without loading the complete log into memory.

    Args:
        path: A plain log or compressed archive.

    Returns:
        Its SHA-256 checksum, or None when absent.
    """
    try:
        return required_file_checksum(path)
    except FileNotFoundError:
        return None


def required_file_checksum(path: pathlib.Path) -> str:
    """Keep a missing required input distinct from an intentionally absent archive.

    Args:
        path: A file required by the current publication step.

    Returns:
        Its SHA-256 checksum.
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def rotation_committed(path: pathlib.Path) -> bool:
    """Check whether the archive contains the source recorded in the rotation receipt.

    The checksums must match before the source can be removed. This check only reads the
    retained files; it does not finish an interrupted rotation.

    Args:
        path: The monthly source protected by the directory's shared or writer lock.

    Returns:
        Whether the published archive already contains the receipted source.

    Raises:
        ValueError: A malformed receipt or changed file prevents safe recovery.
    """
    receipt_path = rotation_receipt_path(path)
    if not receipt_path.exists():
        return False
    source, previous, target = rotation_checksums(receipt_path.read_bytes())
    archive_checksum = file_checksum(path.with_suffix(".jsonl.zst"))
    source_checksum = file_checksum(path)
    if archive_checksum == target:
        if source_checksum is not None and source_checksum != source:
            message = f"Rotation source changed before retirement: {path}"
            raise ValueError(message)
        return True
    if archive_checksum != previous or source_checksum != source:
        message = f"Rotation receipt does not authenticate retained files: {path}"
        raise ValueError(message)
    return False


def recover_rotation(path: pathlib.Path) -> bool:
    """Remove a source log only when the archive checksum confirms its rotation.

    Args:
        path: The monthly source protected by the directory's writer lock.

    Returns:
        Whether a previously published archive completed source retirement.
    """
    if not rotation_committed(path):
        return False
    path.unlink(missing_ok=True)
    rotation_receipt_path(path).unlink()
    return True


def compress_log(path: pathlib.Path, *, level: int = 19) -> None:
    """Publish a complete archive before removing its original log.

    Args:
        path: The closed monthly log, protected by the log directory's writer lock.
        level: Zstandard effort for this closed component.
    """
    if recover_rotation(path):
        return
    archive = path.with_suffix(".jsonl.zst")
    source_checksum = required_file_checksum(path)
    with tempfile.TemporaryDirectory(dir=path.parent) as directory:
        temporary = pathlib.Path(directory) / archive.name
        archived_batches = set()
        if archive.exists():
            shutil.copyfile(archive, temporary)
            with compression.zstd.open(archive, "rb") as retained:
                archived_batches = {
                    identifier
                    for line in retained
                    if (identifier := batch_identifier(line)) is not None
                }
        with (
            path.open("rb") as source,
            compression.zstd.open(temporary, "ab", level=level) as destination,
        ):
            if archived_batches:
                for line in source:
                    if batch_identifier(line) not in archived_batches:
                        destination.write(line)
            else:
                shutil.copyfileobj(source, destination)
        target_checksum = required_file_checksum(temporary)
        receipt = json.dumps(
            {
                "version": 1,
                "source_checksum": source_checksum,
                "archive_checksum": file_checksum(archive),
                "target_checksum": target_checksum,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        temporary_receipt = pathlib.Path(directory) / "rotation.json"
        temporary_receipt.write_text(receipt, encoding="utf-8")
        temporary_receipt.replace(rotation_receipt_path(path))
        temporary.replace(archive)
    path.unlink()
    rotation_receipt_path(path).unlink()


def segment_paths(path: pathlib.Path) -> tuple[pathlib.Path, ...]:
    """Discover numbered components without treating an archive as another segment.

    Args:
        path: The active plain monthly general log.

    Returns:
        Plain segment names in original publication order, including archived sources.
    """
    names = {
        candidate.name.removesuffix(".rotation.json").removesuffix(".zst")
        for candidate in path.parent.glob(path.stem + ".*.jsonl*")
    }
    return tuple(
        sorted(
            (path.with_name(name) for name in names if SEGMENT_PATTERN.fullmatch(name)),
            key=lambda component: int(component.stem.rsplit(".", 1)[1]),
        ),
    )


def seal_log(path: pathlib.Path, *, force: bool = False) -> None:
    """Move a complete active tail into an immutable independently compressed segment.

    Atomic rename publishes all source bytes before compression. Readers can therefore
    use a plain segment after interruption, and the existing rotation receipt protects
    its later archive publication and source retirement.

    Args:
        path: The active general log protected by its directory's writer lock.
        force: Seal a closed month's remaining tail even below the size threshold.
    """
    if not path.exists() or (
        not force and path.stat().st_size < MAXIMUM_LOG_SEGMENT_BYTES
    ):
        return
    with path.open("rb") as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            return
        stream.seek(-1, os.SEEK_END)
        if stream.read(1) != b"\n":
            return
    previous = segment_paths(path)
    number = int(previous[-1].stem.rsplit(".", 1)[1]) + 1 if previous else 1
    destination = path.with_name(f"{path.stem}.{number:012d}.jsonl")
    path.replace(destination)
    compress_log(destination, level=3)


def rotation_paths(
    directory: pathlib.Path,
    suffix: str,
    timestamp: datetime.datetime,
) -> tuple[pathlib.Path, ...]:
    """Recover pending work before a writer can append to a recreated monthly source.

    Args:
        directory: The log directory protected by its writer lock.
        suffix: The series whose rotation and receipts this writer owns.
        timestamp: The current local time selecting closed months.

    Returns:
        Every pending source and every source old enough to compress, in name order.
    """
    pattern = r"[0-9]{4}-(0[1-9]|1[0-2])" + re.escape(suffix) + r"\.jsonl"
    pending = {
        path.with_name(path.name.removesuffix(".rotation.json"))
        for path in directory.glob("*.jsonl.rotation.json")
        if re.fullmatch(pattern, path.name.removesuffix(".rotation.json"))
        or (
            not suffix
            and SEGMENT_PATTERN.fullmatch(path.name.removesuffix(".rotation.json"))
        )
    }
    eligible = {
        path
        for path in directory.glob("*.jsonl")
        if (
            re.fullmatch(pattern, path.name)
            and path.name[:7] < compression_month(timestamp)
        )
        or (not suffix and SEGMENT_PATTERN.fullmatch(path.name))
    }
    return tuple(sorted(pending | eligible))


def append_monthly_log(
    directory: pathlib.Path,
    event_dict: collections.abc.Mapping[str, object],
) -> None:
    """Keep timestamps and monthly rotation consistent across concurrent commands.

    Args:
        directory: The directory holding monthly logs and their archives.
        event_dict: A normalized event with formatted exception details.
    """
    append_monthly_records(directory, (event_dict,))


def compression_month(timestamp: datetime.datetime) -> str:
    """Keep each closed month readable for seven complete calendar days.

    Args:
        timestamp: The local time of the rotation check.

    Returns:
        The earliest month that must remain uncompressed.
    """
    return (timestamp.date() - datetime.timedelta(days=7)).strftime("%Y-%m")


def contains_batch(path: pathlib.Path, batch_id: str) -> bool:
    """Find an already appended batch even if saving its checkpoint was interrupted.

    Args:
        path: The destination monthly log, possibly already archived.
        batch_id: The journal's stable identifier for the complete atomic append.

    Returns:
        Whether either retained representation contains the batch.
    """
    for component in (path, *segment_paths(path)):
        if contains_component_batch(component, batch_id):
            return True
    return False


def contains_component_batch(path: pathlib.Path, batch_id: str) -> bool:
    """Search a plain/archive pair for a journal's explicit identity.

    Args:
        path: A logical component protected by its directory's writer lock.
        batch_id: The journal's stable identifier.

    Returns:
        Whether either retained physical representation contains the batch.
    """
    for candidate in (path, path.with_suffix(".jsonl.zst")):
        opener = compression.zstd.open if candidate.suffix == ".zst" else open
        with (
            contextlib.suppress(FileNotFoundError),
            opener(candidate, "rt", encoding="utf-8") as stream,
        ):
            if any(
                json.loads(line).get("batch_id") == batch_id
                for line in stream
                if line.strip()
            ):
                return True
    return False


def append_atomic(path: pathlib.Path, content: str) -> None:
    """Publish all records of a recoverable batch together, or leave the log intact.

    Args:
        path: The monthly log protected by its directory's writer lock.
        content: Complete serialized lines to append.
    """
    with tempfile.TemporaryDirectory(dir=path.parent) as directory:
        temporary = pathlib.Path(directory) / path.name
        if path.exists():
            shutil.copyfile(path, temporary)
        with temporary.open("a", encoding="utf-8") as stream:
            stream.write(content)
        temporary.replace(path)


@functools.cache
def json_value_handler() -> collections.abc.Callable[[object], object]:
    """Obtain Structlog's JSON fallback through its public serializer hook.

    Returns:
        The renderer's handler for values outside JSON's built-in types.
    """
    handlers: list[collections.abc.Callable[[object], object]] = []

    def receive_default(
        _event: object,
        *,
        default: collections.abc.Callable[[object], object],
    ) -> str:
        """Capture the handler supplied to the renderer's serializer.

        Args:
            _event: The empty event used to obtain the handler.
            default: The renderer's custom-value conversion.

        Returns:
            An empty rendering for the initialization event.
        """
        handlers.append(default)
        return ""

    structured_logging().processors.JSONRenderer(serializer=receive_default)(
        None,
        "",
        {},
    )
    return handlers[0]


def render_json_value(value: object) -> object:
    """Load custom-value support when the JSON encoder needs it.

    Args:
        value: A value outside the JSON encoder's built-in types.

    Returns:
        The value produced by Structlog's JSON fallback.
    """
    return json_value_handler()(value)


def append_monthly_records(
    directory: pathlib.Path,
    records: collections.abc.Iterable[collections.abc.Mapping[str, object]],
    *,
    suffix: str = "",
    timestamp: datetime.datetime | None = None,
    batch_id: str | None = None,
) -> None:
    """Give one batch a shared timestamp and rotate only its monthly log series.

    Args:
        directory: The directory holding monthly logs and their archives.
        records: Normalized records to append together, possibly empty.
        suffix: The filename suffix between the month and ``.jsonl``.
        timestamp: A journal's original completion time, or the current local time.
        batch_id: A journal identifier enabling atomic, idempotent batch retries.
    """
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".rotation.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        now = datetime.datetime.now().astimezone()
        timestamp = timestamp or now
        filename = timestamp.strftime("%Y-%m") + suffix + ".jsonl"
        for path in rotation_paths(directory, suffix, now):
            if SEGMENT_PATTERN.fullmatch(path.name):
                compress_log(path, level=3)
            elif not suffix and segment_paths(path):
                seal_log(path, force=True)
            else:
                compress_log(path)
        path = directory / filename
        if not suffix:
            seal_log(path)
        if batch_id is not None and contains_batch(path, batch_id):
            return
        entries = tuple(
            json.dumps(
                {
                    **record,
                    **({"batch_id": batch_id} if batch_id is not None else {}),
                    "timestamp": timestamp.strftime("%Y-%m-%dT%H:%M:%S%z"),
                },
                allow_nan=False,
                default=render_json_value,
            )
            for record in records
        )
        if entries:
            content = "".join(entry + "\n" for entry in entries)
            if batch_id is not None:
                append_atomic(path, content)
            else:
                with path.open("a", encoding="utf-8") as stream:
                    stream.write(content)


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

    Events below stderr's threshold are dropped after any file output.
    """
    structlog = structured_logging()
    level = logging.getLevelNamesMapping()[str(event_dict["level"]).upper()]
    if directory is not None and level >= file_level:
        file_event = structlog.processors.format_exc_info(
            wrapped_logger,
            method_name,
            dict(event_dict),
        )
        append_monthly_log(directory, file_event)
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
    structlog = structured_logging()
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
    structlog = structured_logging()
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
    """Make nested execution boundaries and elapsed time visible, including failures.

    Args:
        kind: Whether the operation is a CLI command or a pipeline phase.
        name: The operation's CLI or phase name.
        kwargs: Additional context for the start entry and, for phases, the finish.

    Yields:
        Control to the operation being timed.
    """
    phase_path = (*PHASE_PATH.get(), name) if kind == "phase" else ()
    instances = (
        (
            *PHASE_INSTANCES.get(),
            peri_scribe.phases.Segment(
                phase=name,
                branch=peri_scribe.phases.branch_name(name, kwargs),
            ),
        )
        if kind == "phase"
        else ()
    )
    run_context = (
        {"run_id": str(uuid.uuid4()), "process_id": os.getpid()}
        if kind == "command"
        else RUN_CONTEXT.get() or {}
    )
    with (
        PHASE_PATH.set(phase_path),
        PHASE_INSTANCES.set(instances),
        RUN_CONTEXT.set(run_context),
    ):
        seconds = value_module().seconds
        started_at = time.perf_counter()
        context: dict[str, object] = run_context | {kind: name}
        if kind == "phase":
            context["phase_path"] = ".".join(phase_path)
            context["phase_segments"] = instances
        log = execution_logger()
        log.info("Starting %s", kind, **context, **kwargs)
        status = "failed"
        try:
            yield
            status = "completed"
        finally:
            elapsed = time.perf_counter() - started_at
            log.log(
                logging.ERROR if status == "failed" else logging.INFO,
                "Finished %s",
                kind,
                **context,
                **(kwargs if kind == "phase" else {}),
                duration=seconds(round(elapsed, 2)),
                status=status,
                exc_info=status == "failed",
            )


@contextlib.contextmanager
def log_phase(
    identifier: peri_scribe.phases.Identifier,
    **kwargs: object,
) -> typing.Generator[None]:
    """Require registered phases and valid parentage at every execution boundary.

    Args:
        identifier: The shared catalogue's identifier for this operation.
        kwargs: Structured feed, source, or other diagnostic context.

    Yields:
        Control while the phase is active.

    Raises:
        TypeError: If the phase is not a registered enum member.
        ValueError: If the phase is invalid in its enclosing context.
    """
    if not isinstance(
        identifier,
        (peri_scribe.phases.Phase, peri_scribe.pipeline_stages.Stage),
    ):
        message = f"Undeclared phase: {identifier!r}"
        raise TypeError(message)
    parent = PHASE_PATH.get()
    if parent and identifier not in peri_scribe.phases.CHILDREN.get(parent[-1], ()):
        message = f"Phase {identifier} is not a child of {parent[-1]}"
        raise ValueError(message)
    with log_execution("phase", identifier, **kwargs):
        yield


def skip_phases(
    identifiers: tuple[peri_scribe.phases.Identifier, ...],
    reason: str,
) -> None:
    """Record why planned branches were skipped so the monitor can explain omissions.

    Args:
        identifiers: Sibling phases that will not run in the enclosing context.
        reason: The execution decision responsible for skipping this work.
    """
    execution_logger().info("Skipped phases", phases=identifiers, reason=reason)


def command_line_parameters(context: click.Context) -> dict[str, object]:
    """Preserve explicitly supplied command and parent-group parameters in logs.

    Args:
        context: The invoked command's parsed Click context.

    Returns:
        The supplied parameter names and their parsed values.
    """
    click = importlib.import_module("click")
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
        context = importlib.import_module("click").get_current_context()
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
