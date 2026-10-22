"""Retire geography process memory while preserving one continuous writer lease.

[Supervised stage processes](../../docs/algorithms/stage-processes.md).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime
import importlib
import os
import pathlib
import signal
import sys
import tempfile
import textwrap
import threading
import typing

import click
import pydantic
import structlog

import peri_scribe.cli_options
import peri_scribe.logging
import peri_scribe.pipeline_stages
import peri_scribe.pipeline_state
from measurement_units import units


logger = structlog.get_logger()
CHILD_EXIT_GRACE = 5 * units.seconds


class SegmentResult(pydantic.BaseModel):
    """Transfer continuation intent only after a complete successful stage segment."""

    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")
    next_stage: int | None = pydantic.Field(default=None, ge=0, le=4)
    publication_inputs: str | None = None


class Request(pydantic.BaseModel):
    """Serialize exact options and command identity across interpreter boundaries."""

    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")
    year_directory: pathlib.Path
    start: int = pydantic.Field(ge=0, le=4)
    end: int = pydantic.Field(ge=0, le=4)
    full_fetch_interval: datetime.timedelta | None = None
    area_square_meters: float | None = pydantic.Field(
        default=None,
        gt=0,
        allow_inf_nan=False,
    )
    publication_interval: datetime.timedelta | None = None
    unconditional: bool = False
    initialize: bool = True
    stop_after_geography: bool = False
    publication_inputs: str | None = None
    logging_levels: tuple[str, str]
    run_context: dict[str, object]

    @pydantic.model_validator(mode="after")
    def valid_selection(self) -> typing.Self:
        """Reject inconsistent serialized selections before starting stage work.

        Returns:
            The request when its paired threshold and stage range are valid.

        Raises:
            ValueError: If the range or threshold pair is inconsistent.
        """
        if (
            self.start > self.end
            or (
                (self.area_square_meters is None) != (self.publication_interval is None)
            )
            or (
                self.publication_interval is not None
                and self.publication_interval <= datetime.timedelta(0)
            )
        ):
            message = "Invalid stage range or publication threshold"
            raise ValueError(message)
        return self


def logging_levels() -> tuple[str, str]:
    """Read the already validated global severity options from the public command.

    Returns:
        Console and file severity levels in command-line order.
    """
    parameters = click.get_current_context().find_root().params
    return str(parameters["stderr_log_level"]), str(parameters["file_log_level"])


@click.command(
    help=textwrap.dedent(
        f"""\
        Run the PeriScribe pipeline.

        A full run goes through fetch, geography, score, kmz, and reports in that order.
        Fetch collects every configured fire feed and checks the external sources:
        buildings, evacuations, and Natural Earth places. It fetches the state boundary
        GeoPackage only when the stored file is missing or unusable. New fire snapshots
        or changed evacuations or place locations require the later stages to rebuild.
        An unchanged fetch can finish without rebuilding when no other work is pending.

        Incremental fetching uses the feeds' change information. Use
        --full-fetch-interval to also catch source edits that this can miss. The first
        invocation with the option fetches every fire feed in full, storing only new or
        changed features. Later invocations do so when the requested interval has passed
        since the last successful full fetch. Every scheduled full fetch requires a
        complete derived rebuild, even if no features changed. Without this option,
        every fire-feed fetch is incremental.

        Use --only for one stage, --from and --to for a range, or --list-stages to see
        the choices. --unconditional rebuilds the selected stages even without changed
        inputs and bypasses prior geography when that stage is selected. Static feeds
        such as buildings are still downloaded only when missing or unusable. An error
        stops the pipeline; later runs resume unfinished builds.

        --publish-threshold AREA TIME_DELTA lets runs collect small updates without
        rebuilding outputs each time. It saves fire geometry and checks evacuations and
        place locations before deciding whether to build. A mapped-area increase or
        decrease of at least AREA since the last published mapping triggers a build.
        Smaller unpublished changes wait until TIME_DELTA has passed since the last
        completed local KMZ. For example, --publish-threshold "25 acre" 5m uses a change
        of 25 acres or a five-minute interval. Evacuation or place-location changes,
        scheduled full fetches, unfinished builds, and --unconditional bypass this wait.
        {peri_scribe.cli_options.year_directory_default_help()}
        """,
    ),
)
@click.argument(
    "year_directory",
    callback=peri_scribe.cli_options.command_year_directory,
    type=click.Path(path_type=pathlib.Path, exists=True, file_okay=False),
    required=False,
)
@click.option(
    "--publish-threshold",
    type=(peri_scribe.cli_options.Area(), peri_scribe.cli_options.Duration()),
    callback=peri_scribe.cli_options.publication_threshold,
    metavar="AREA TIME_DELTA",
    help=textwrap.dedent(
        """\
        Publish when any mapped area changes by at least AREA in either direction,
        or unpublished data has waited until TIME_DELTA since the last KMZ.
        Use positive values, for example '25 acre' 5m.
        """,
    ),
)
@click.option(
    "--full-fetch-interval",
    type=peri_scribe.cli_options.Duration(),
    help=textwrap.dedent(
        """\
        Fetch every fire feed in full whenever the last successful full fetch is at
        least this old; for example 12h or 1d.
        """,
    ),
)
@click.option(
    "--unconditional",
    is_flag=True,
    help=textwrap.dedent(
        """\
        Rebuild selected stages without reusing prior geography, even when nothing
        changed.
        """,
    ),
)
@click.option(
    "--only",
    "only_stage",
    type=click.Choice(peri_scribe.cli_options.STAGE_NAMES, case_sensitive=False),
    help="Run only the named pipeline stage.",
)
@click.option(
    "--from",
    "from_stage",
    type=click.Choice(peri_scribe.cli_options.STAGE_NAMES, case_sensitive=False),
    help="Start the pipeline at the named stage (default: fetch).",
)
@click.option(
    "--to",
    "to_stage",
    type=click.Choice(peri_scribe.cli_options.STAGE_NAMES, case_sensitive=False),
    help="Stop the pipeline after the named stage (default: reports).",
)
@click.option(
    "--list-stages",
    is_flag=True,
    help="List the pipeline stages and their descriptions without running anything.",
)
@peri_scribe.logging.log_command
def run(
    year_directory: pathlib.Path,
    *,
    full_fetch_interval: datetime.timedelta | None = None,
    publish_threshold: peri_scribe.cli_options.PublicationThreshold | None = None,
    unconditional: bool = False,
    only_stage: str | None = None,
    from_stage: str | None = None,
    to_stage: str | None = None,
    list_stages: bool = False,
) -> None:
    """Run the selected pipeline stages.

    Args:
        year_directory: The resolved directory holding the pipeline data and logs.
        full_fetch_interval: How often to fetch every fire feed in full, or None to
            always fetch incrementally.
        publish_threshold: Defer publication until the area or time requirement is met.
        unconditional: Whether to run selected stages regardless of input changes and
            bypass history reuse when geography is selected.
        only_stage: A single stage to run, or None to use a stage range.
        from_stage: The first stage in the range, or None to start at fetch.
        to_stage: The last stage in the range, or None to finish at reports.
        list_stages: Whether to print stage descriptions without running the pipeline.

    Raises:
        click.UsageError: When the stage selection is invalid.
    """
    if list_stages:
        peri_scribe.cli_options.print_stages()
        return
    if only_stage is not None and (from_stage is not None or to_stage is not None):
        message = "--only cannot be combined with --from or --to"
        raise click.UsageError(message)
    start, end = peri_scribe.cli_options.selected_stage_range(
        only_stage,
        from_stage,
        to_stage,
    )
    request = Request(
        year_directory=year_directory,
        start=start,
        end=end,
        full_fetch_interval=full_fetch_interval,
        area_square_meters=(
            None
            if publish_threshold is None
            else publish_threshold.area.m_as("meters ** 2")
        ),
        publication_interval=(
            None if publish_threshold is None else publish_threshold.interval
        ),
        unconditional=unconditional,
        logging_levels=logging_levels(),
        run_context=dict(peri_scribe.logging.RUN_CONTEXT.get() or {}),
    )
    with peri_scribe.pipeline_state.run_lease(year_directory) as descriptor:
        if descriptor is None:
            logger.info(
                "Another run owns this year; skipping invocation",
                year=str(year_directory),
            )
            return
        geography = peri_scribe.cli_options.STAGE_INDEX[
            peri_scribe.pipeline_stages.Stage.GEOGRAPHY
        ]
        if start <= geography < end:
            supervise(request, descriptor)
        else:
            execute_request(request)


def execute_request(request: Request) -> SegmentResult:
    """Load heavy pipeline code only in the process that executes its stages.

    Args:
        request: Validated range, flags, frozen inputs and command identity.

    Returns:
        The stage loop's completed continuation state.
    """
    pipeline = importlib.import_module("peri_scribe.pipeline")
    publication = importlib.import_module("peri_scribe.publication")
    threshold = (
        None
        if request.area_square_meters is None
        else publication.Threshold(
            area=request.area_square_meters * units.Unit("meters ** 2"),
            interval=typing.cast("datetime.timedelta", request.publication_interval),
        )
    )
    inputs = (
        None
        if request.publication_inputs is None
        else publication.Collection.model_validate_json(request.publication_inputs)
    )
    if request.initialize:
        logger.info(
            "Planned phases",
            branches=importlib.import_module(
                "peri_scribe.sources.catalog",
            ).configured_phase_branches(),
            gated=threshold is not None,
            stages=tuple(
                stage.name
                for stage in peri_scribe.cli_options.PIPELINE_STAGES[
                    request.start : request.end + 1
                ]
            ),
        )
    return pipeline.run_selected_stages(
        request.year_directory,
        request.start,
        request.end,
        full_fetch_interval=request.full_fetch_interval,
        unconditional=request.unconditional,
        publish_threshold=threshold,
        initialize=request.initialize,
        stop_after_geography=request.stop_after_geography,
        publication_inputs=inputs,
    )


def child_command(
    descriptor: int,
    request_path: pathlib.Path,
    response_path: pathlib.Path,
) -> list[str]:
    """Use the current installation and interpreter for each isolated stage segment.

    Args:
        descriptor: The parent's inherited lease reference.
        request_path: Private serialized command input.
        response_path: Private destination for a successful segment response.

    Returns:
        Argument vector for a fresh Python interpreter without shell expansion.
    """
    return [
        sys.executable,
        "-m",
        "peri_scribe.supervision",
        str(descriptor),
        str(request_path),
        str(response_path),
    ]


def run_child(
    request: Request,
    descriptor: int,
    directory: pathlib.Path,
) -> SegmentResult:
    """Join a lease-holding child before accepting its complete continuation record.

    Args:
        request: Stage selection and options owned by this child.
        descriptor: Live parent lease that the child must inherit.
        directory: Private handoff files owned until all children settle.

    Returns:
        A complete validated response from a successful child.

    Raises:
        SystemExit: If the child exits unsuccessfully, preserving its numeric status.
    """
    request_path = directory / "request.json"
    response_path = directory / "response.json"
    response_path.unlink(missing_ok=True)
    request_path.write_text(request.model_dump_json())
    returncode = asyncio.run(
        child_status(
            child_command(descriptor, request_path, response_path),
            descriptor,
        ),
    )
    if returncode:
        raise SystemExit(returncode if returncode > 0 else 128 - returncode)
    return SegmentResult.model_validate_json(response_path.read_bytes())


async def child_status(command: list[str], descriptor: int) -> int:
    """Settle the active process before propagating any interruption to its owner.

    Args:
        command: Shell-free argument vector for the private child entrypoint.
        descriptor: The continuously held writer lease reference.

    Returns:
        The child's operating-system exit status.
    """
    launch = asyncio.create_task(
        asyncio.create_subprocess_exec(
            *command,
            pass_fds=(descriptor,),
            start_new_session=True,
        ),
    )
    try:
        process = await asyncio.shield(launch)
        return await process.wait()
    except BaseException:
        with deferred_interrupts():
            cleanup = asyncio.create_task(settle_launch(launch))
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    continue
            cleanup.result()
        raise


async def settle_launch(launch: asyncio.Task[asyncio.subprocess.Process]) -> None:
    """Retain ownership even when cancellation precedes the process handle.

    Args:
        launch: The shielded process creation operation owned by this invocation.
    """
    result = (await asyncio.gather(launch, return_exceptions=True))[0]
    if not isinstance(result, BaseException):
        await stop_child(result)


@contextlib.contextmanager
def deferred_interrupts() -> typing.Generator[None]:
    """Let the bounded termination path finish despite repeated terminal interrupts.

    Yields:
        Control with repeated interrupts deferred until the child has settled.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)


async def stop_child(process: asyncio.subprocess.Process) -> None:
    """Finish cancellation before temporary files or the writer lease can leave scope.

    Args:
        process: The active child and leader of its private process group.
    """
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        async with asyncio.timeout(CHILD_EXIT_GRACE.m_as("seconds")):
            await process.wait()
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)


@contextlib.contextmanager
def termination_cleanup() -> typing.Generator[None]:
    """Give main-thread CLI termination the same cleanup path as interruption.

    Yields:
        Control with termination routed through ordinary exception unwinding.

    Raises:
        SystemExit: If termination requested a signal-derived exit status.
        KeyboardInterrupt: If an ordinary interrupt requested cancellation.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    received: list[int] = []

    def interrupt(signum: int, _frame: object) -> None:
        """Use the runner's cancellation path before translating termination status.

        Args:
            signum: The termination signal whose exit status must survive cleanup.
            _frame: Interrupted frame supplied by Python's signal dispatch.
        """
        received.append(signum)
        signal.raise_signal(signal.SIGINT)

    previous = signal.signal(signal.SIGTERM, interrupt)
    try:
        yield
    except KeyboardInterrupt:
        if received:
            raise SystemExit(128 + received[-1]) from None
        raise
    finally:
        signal.signal(signal.SIGTERM, previous)


def supervise(request: Request, descriptor: int) -> None:
    """Cross geography once, retaining the parent lease across the child-free handoff.

    Args:
        request: The original selected range spanning geography and later work.
        descriptor: Continuously held parent writer lease.

    Raises:
        ValueError: If a child returns an unexpected continuation position.
    """
    with (
        termination_cleanup(),
        tempfile.TemporaryDirectory(prefix="peri-scribe-stages-") as temporary,
    ):
        directory = pathlib.Path(temporary)
        first = request.model_copy(update={"stop_after_geography": True})
        result = run_child(first, descriptor, directory)
        if result.next_stage is None:
            return
        score = peri_scribe.cli_options.STAGE_INDEX[
            peri_scribe.pipeline_stages.Stage.SCORE
        ]
        if result.next_stage != score:
            message = "Stage child returned an unexpected continuation"
            raise ValueError(message)
        second = request.model_copy(
            update={
                "start": score,
                "initialize": False,
                "publication_inputs": result.publication_inputs,
            },
        )
        if run_child(second, descriptor, directory).next_stage is not None:
            message = "Final stage child requested an unexpected continuation"
            raise ValueError(message)


def worker_main(arguments: list[str] | None = None) -> None:
    """Run one private segment without another command boundary or writer-lock gap.

    Args:
        arguments: Private inherited descriptor and handoff paths, or the process args.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("descriptor", type=int)
    parser.add_argument("request", type=pathlib.Path)
    parser.add_argument("response", type=pathlib.Path)
    options = parser.parse_args(arguments)
    request = Request.model_validate_json(options.request.read_bytes())
    with (
        peri_scribe.pipeline_state.inherited_lease(
            request.year_directory,
            options.descriptor,
        ),
        peri_scribe.logging.RUN_CONTEXT.set(request.run_context),
    ):
        peri_scribe.logging.configure_logging(
            *request.logging_levels,
            year_directory=request.year_directory,
        )
        result = execute_request(request)
        options.response.write_text(result.model_dump_json())


if __name__ == "__main__":
    worker_main()
