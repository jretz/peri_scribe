"""Pipeline commands load their generation dependencies only when selected."""

from __future__ import annotations

import dataclasses
import datetime
import math
import pathlib
import re
import textwrap
import typing

import click
import pint
import structlog

import peri_scribe.cli_options
import peri_scribe.fires.differential
import peri_scribe.fires.index
import peri_scribe.fires.scores
import peri_scribe.kml.builder
import peri_scribe.kml.colormap
import peri_scribe.logging
import peri_scribe.output
import peri_scribe.paths
import peri_scribe.phases
import peri_scribe.pipeline_stages
import peri_scribe.pipeline_state
import peri_scribe.publication
import peri_scribe.report.gathering
import peri_scribe.report.markdown
import peri_scribe.sources.administrative_boundaries
import peri_scribe.sources.catalog
import peri_scribe.sources.digests
import peri_scribe.sources.external_data
import peri_scribe.sources.external_sources
import peri_scribe.sources.feeds
import peri_scribe.sources.fetching
import peri_scribe.sources.full_fetch_state
import peri_scribe.sources.snapshots
import peri_scribe.sources.validation
from measurement_units import units


logger = structlog.get_logger()


class Duration(click.ParamType):
    """A duration of whole minutes, hours or days.

    Values are a non-negative whole number followed by ``m``, ``h`` or ``d``, for
    example ``5m``, ``12h`` or ``1d``, and convert to a ``datetime.timedelta``.
    """

    name = "duration"

    def convert(
        self,
        value: object,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> datetime.timedelta:
        """Return *value* converted to a ``datetime.timedelta``.

        An already-converted ``datetime.timedelta`` passes through unchanged, so the
        type works with timedelta defaults. Anything else is rejected.

        Args:
            value: The option value to convert.
            param: The parameter the value came from.
            ctx: The click context.

        Returns:
            The parsed duration.
        """
        if isinstance(value, datetime.timedelta):
            return value
        message = (
            f"{value!r} is not a duration of whole minutes, hours or days "
            "such as '5m', '12h' or '1d'"
        )
        if not isinstance(value, str):
            self.fail(message, param, ctx)
        duration_match = re.fullmatch(r"([0-9]+)([mhd])", value)
        if duration_match is None:
            self.fail(message, param, ctx)
        count = int(duration_match.group(1))
        try:
            if duration_match.group(2) == "m":
                return datetime.timedelta(minutes=count)
            if duration_match.group(2) == "h":
                return datetime.timedelta(hours=count)
            return datetime.timedelta(days=count)
        except OverflowError:
            self.fail(f"{value!r} is too large to be a duration", param, ctx)


class Area(click.ParamType):
    """Require a positive finite area with explicit physical units."""

    name = "area"

    def convert(
        self,
        value: object,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> pint.Quantity[float]:
        """Reject unitless and non-area values before the pipeline can write data.

        Args:
            value: The command-line area value, including its physical units.
            param: The Click parameter used to report validation errors, if available.
            ctx: The Click invocation context, if available.

        Returns:
            The positive area converted to square meters.
        """
        message = f"{value!r} is not a positive area such as '25 acre'"
        if not isinstance(value, (str, pint.Quantity)):
            self.fail(message, param, ctx)
        try:
            area = units.Quantity(value).to("meters ** 2")
        except pint.errors.PintError, TypeError, ValueError:
            self.fail(message, param, ctx)
        if not math.isfinite(area.magnitude) or area.magnitude <= 0:
            self.fail(message, param, ctx)
        return typing.cast("pint.Quantity[float]", area)


def publication_threshold(
    _context: click.Context,
    _parameter: click.Parameter,
    value: tuple[pint.Quantity[float], datetime.timedelta] | None,
) -> peri_scribe.publication.Threshold | None:
    """Validate the area and time settings as one publication policy.

    Args:
        _context: The invocation context supplied by Click; unused by this callback.
        _parameter: The option supplied by Click; unused by this callback.
        value: The parsed area and duration, or None when the option was omitted.

    Returns:
        The configured policy, or None when the option was omitted.

    Raises:
        click.BadParameter: If the publication interval is not positive.
    """
    if value is None:
        return None
    area, interval = value
    if interval <= datetime.timedelta(0):
        message = "The publication interval must be positive"
        raise click.BadParameter(message)
    return peri_scribe.publication.Threshold(area=area, interval=interval)


def fetch_external_source(
    source: peri_scribe.sources.external_data.ExternalSource,
    year_directory: pathlib.Path | None,
) -> None:
    """Fetch *source* into *year_directory*, resolving the default directory.

    Args:
        source: External source selected for collection.
        year_directory: Destination year directory, or None to use the current year's
            directory.
    """
    if year_directory is None:
        year_directory = peri_scribe.cli_options.default_year_directory()
    with peri_scribe.logging.log_phase(
        peri_scribe.phases.Phase.COLLECT_EXTERNAL_SOURCE,
        source=source.name,
    ):
        paths = peri_scribe.sources.external_sources.fetch_external_source(
            source,
            year_directory,
        )
        logger.info("Fetched external source", source=source.name, paths=paths)


@click.command()
@click.option(
    "--trim-start",
    type=int,
    default=peri_scribe.kml.colormap.TURBO_TRIM_FROM_START,
    show_default=True,
    help="Colors to exclude from the start of the used range.",
)
@click.option(
    "--trim-end",
    type=int,
    default=peri_scribe.kml.colormap.TURBO_TRIM_FROM_END,
    show_default=True,
    help="Colors to exclude from the end of the used range.",
)
def show_colormap(*, trim_start: int, trim_end: int) -> None:
    """Print a Turbo colormap strip to the terminal as ANSI truecolor.

    The strip is one colored cell per color of the full 256-color colormap. A tick label
    left of the color bar names the original Turbo index every 16 colors, and a label
    right of the marker line names the first and last color the progression rings use;
    the marker itself is drawn beside every color in that range. The marked range
    defaults to the ramp the rings sample, so --trim-start and --trim-end preview a ramp
    with different endpoints.

    Args:
        trim_start: Number of colors excluded from the cool end of the Turbo ramp.
        trim_end: Number of colors excluded from the hot end of the Turbo ramp.
    """
    strip = peri_scribe.kml.colormap.turbo_colormap_ansi(
        trim_start=trim_start,
        trim_end=trim_end,
    )
    click.echo(strip)


def stored_evacuations_digest(year_directory: pathlib.Path) -> str | None:
    """Return the stored evacuations GeoPackage's content digest, or None.

    The evacuation layer is the only external source that changes in place: its fetch
    replaces the stored GeoPackage only when the layer's features changed, so comparing
    the digest before and after the fetch reports whether the fetch found changes.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The digest of the stored evacuations contents, or None when no version is
        stored.
    """
    source = peri_scribe.sources.catalog.EVACUATIONS_SOURCE
    return peri_scribe.sources.digests.stored_geopackage_digest(
        peri_scribe.sources.external_data.output_path(year_directory, source),
        source.layer_name or source.name,
    )


def write_reports(year_directory: pathlib.Path) -> pathlib.Path:
    """Gather and render fire reports for *year_directory*.

    Reports are gathered from the stored derived outputs and rendered as Markdown, so
    they can be produced on their own or as the final step of the pipeline.

    Args:
        year_directory: The year directory that holds the ``derived`` directory.

    Returns:
        The path of the written reports.
    """
    report = peri_scribe.report.gathering.gather_report(year_directory)
    return peri_scribe.report.markdown.render_markdown_report(report, year_directory)


def prepare_administrative_boundaries(year_directory: pathlib.Path) -> None:
    """Make the boundary data available before source indexing classifies fires.

    Args:
        year_directory: The year directory holding the administrative boundary data.
    """
    with peri_scribe.logging.log_phase(
        peri_scribe.phases.Phase.ADMINISTRATIVE_BOUNDARIES,
    ):
        peri_scribe.sources.administrative_boundaries.ensure_administrative_boundaries(
            year_directory,
        )


def fetch_fire_sources(
    year_directory: pathlib.Path,
    *,
    full_fetch_interval: datetime.timedelta | None,
    defer_index: bool = False,
) -> tuple[peri_scribe.sources.fetching.FetchResult, bool]:
    """Preserve full-fetch and failure requirements across publication decisions.

    Args:
        year_directory: The directory holding this year's sources and recovery state.
        full_fetch_interval: How often to force a full fetch, or None.
        defer_index: Build the index only after the publication gate accepts updates.

    Returns:
        The collected snapshots and whether a scheduled full fetch was performed.

    Raises:
        SystemExit: If collection fails; the required rebuild remains pending.
    """
    base_directory = peri_scribe.sources.snapshots.base_directory_for_year_directory(
        year_directory,
    )
    year = peri_scribe.paths.year_for_year_directory(year_directory)
    state_file = peri_scribe.sources.full_fetch_state.state_path(year_directory)
    full = False
    if full_fetch_interval is not None:
        stored_state = peri_scribe.sources.full_fetch_state.read_state(state_file)
        current_time = datetime.datetime.now(datetime.UTC)
        last_full_fetch = (
            stored_state.last_full_fetch if stored_state is not None else None
        )
        full = peri_scribe.sources.full_fetch_state.full_fetch_is_due(
            interval=full_fetch_interval,
            current_time=current_time,
            last_full_fetch=last_full_fetch,
        )
    if full:
        peri_scribe.pipeline_state.require_stages(
            year_directory,
            peri_scribe.pipeline_state.DERIVED_STAGES,
            unconditional=True,
        )
    try:
        if defer_index:
            result = peri_scribe.sources.fetching.fetch_all_feeds(
                base_directory,
                year=year,
                full=full,
                build_index=False,
            )
        else:
            prepare_administrative_boundaries(year_directory)
            result = peri_scribe.sources.fetching.fetch_all_feeds(
                base_directory,
                year=year,
                full=full,
            )
    except Exception, SystemExit:
        # A failed feed can follow successful snapshot writes from other feeds.
        peri_scribe.pipeline_state.require_stages(
            year_directory,
            peri_scribe.pipeline_state.DERIVED_STAGES,
        )
        raise
    if full and not defer_index:
        peri_scribe.sources.full_fetch_state.write_state(
            state_file,
            last_full_fetch=datetime.datetime.now(datetime.UTC),
        )
    return result, full


def run_fetch_stage(
    year_directory: pathlib.Path,
    *,
    full_fetch_interval: datetime.timedelta | None,
    unconditional: bool,
    publish_threshold: peri_scribe.publication.Threshold | None = None,
) -> bool:
    """Run required output work when the publication policy permits it.

    Args:
        year_directory: The directory holding the year's sources and outputs.
        full_fetch_interval: How often to force full collection, or None.
        unconditional: Bypass change-based skipping.
        publish_threshold: Area and time requirements for deferred publication.

    Returns:
        Whether the selected downstream stages should run.

    Raises:
        SystemExit: If fetching fails; the required rebuild remains pending.
    """
    if publish_threshold is not None:
        return run_gated_fetch_stage(
            year_directory,
            full_fetch_interval=full_fetch_interval,
            unconditional=unconditional,
            threshold=publish_threshold,
        )
    result, _full = fetch_fire_sources(
        year_directory,
        full_fetch_interval=full_fetch_interval,
    )
    if result.changed:
        peri_scribe.pipeline_state.require_stages(
            year_directory,
            peri_scribe.pipeline_state.DERIVED_STAGES,
        )
    try:
        evacuations_changed = refresh_external_sources(year_directory)
    except Exception, SystemExit:
        peri_scribe.pipeline_state.require_stages(
            year_directory,
            peri_scribe.pipeline_state.DERIVED_STAGES,
        )
        raise
    if evacuations_changed:
        peri_scribe.pipeline_state.require_stages(
            year_directory,
            peri_scribe.pipeline_state.DERIVED_STAGES,
        )
    return (
        result.changed
        or evacuations_changed
        or unconditional
        or bool(peri_scribe.pipeline_state.read_state(year_directory).remaining)
    )


def run_gated_fetch_stage(
    year_directory: pathlib.Path,
    *,
    full_fetch_interval: datetime.timedelta | None,
    unconditional: bool,
    threshold: peri_scribe.publication.Threshold,
) -> bool:
    """Retain geometry and check evacuations before deciding to build outputs.

    Args:
        year_directory: The directory holding the year's sources and outputs.
        full_fetch_interval: How often to force full collection, or None.
        unconditional: Force the selected downstream work.
        threshold: The configured mapped-area change and publication interval.

    Returns:
        Whether to continue past collection.

    Raises:
        SystemExit: If fetching or evaluating saved inputs fails.
    """
    _result, full = fetch_fire_sources(
        year_directory,
        full_fetch_interval=full_fetch_interval,
        defer_index=True,
    )
    try:
        with peri_scribe.logging.log_phase(peri_scribe.phases.Phase.EVACUATION_CHECK):
            fetch_external_source(
                peri_scribe.sources.catalog.EVACUATIONS_SOURCE,
                year_directory,
            )
        with peri_scribe.logging.log_phase(peri_scribe.phases.Phase.PUBLICATION_GATE):
            decision = publication_decision(year_directory, threshold)
    except Exception, SystemExit:
        peri_scribe.pipeline_state.require_stages(
            year_directory,
            peri_scribe.pipeline_state.DERIVED_STAGES,
        )
        raise
    pending = bool(peri_scribe.pipeline_state.read_state(year_directory).remaining)
    proceed = full or unconditional or pending or decision.proceed
    logger.info(
        "Publication gate accepted" if proceed else "Publication gate skipped",
        reason="required rebuild"
        if full or unconditional or pending
        else decision.reason,
        fire=decision.fire,
        mapped_change=decision.change.to("acres"),
        threshold=threshold.area.to("acres"),
    )
    if not proceed:
        peri_scribe.logging.skip_phases(
            (peri_scribe.phases.Phase.DEFERRED_FETCH,),
            decision.reason,
        )
        return False
    peri_scribe.pipeline_state.require_stages(
        year_directory,
        peri_scribe.pipeline_state.DERIVED_STAGES,
    )
    with peri_scribe.logging.log_phase(peri_scribe.phases.Phase.DEFERRED_FETCH):
        prepare_administrative_boundaries(year_directory)
        peri_scribe.fires.index.index_fire_sources(year_directory)
        if full:
            peri_scribe.sources.full_fetch_state.write_state(
                peri_scribe.sources.full_fetch_state.state_path(year_directory),
                last_full_fetch=datetime.datetime.now(datetime.UTC),
            )
        refresh_external_sources(year_directory, include_evacuations=False)
    return True


def publication_decision(
    year_directory: pathlib.Path,
    threshold: peri_scribe.publication.Threshold,
) -> peri_scribe.publication.Decision:
    """Compare the saved inventory with the checkpoint belonging to the current KMZ.

    Args:
        year_directory: The year directory containing saved sources and the current KMZ.
        threshold: The mapped-area change and elapsed-time publication requirements.

    Returns:
        The publication decision for the current time and saved inputs.
    """
    collection = peri_scribe.publication.collect(year_directory)
    published = peri_scribe.publication.read_publication(
        year_directory,
        peri_scribe.paths.kmz_path(year_directory),
    )
    return peri_scribe.publication.decide(
        collection,
        published,
        threshold,
        datetime.datetime.now(datetime.UTC),
    )


def refresh_external_sources(
    year_directory: pathlib.Path,
    *,
    include_evacuations: bool = True,
) -> bool:
    """Observe evacuation changes separately from fire-feed completion.

    Args:
        year_directory: The year directory holding the external source data.
        include_evacuations: Fetch evacuations here when they were not checked before
            the publication gate.

    Returns:
        Whether evacuation geography changed.
    """
    with peri_scribe.logging.log_phase(
        peri_scribe.phases.Phase.EXTERNAL_SOURCE_REFRESH,
    ):
        evacuations_digest_before = (
            stored_evacuations_digest(year_directory) if include_evacuations else None
        )
        for source in peri_scribe.sources.catalog.EXTERNAL_SOURCES:
            if (
                not include_evacuations
                and source is peri_scribe.sources.catalog.EVACUATIONS_SOURCE
            ):
                continue
            fetch_external_source(source, year_directory)
        return (
            include_evacuations
            and stored_evacuations_digest(year_directory) != evacuations_digest_before
        )


def run_geography_stage(
    year_directory: pathlib.Path,
    *,
    unconditional: bool = False,
) -> None:
    """Derive fire geography histories from the fetched sources.

    Args:
        year_directory: The year directory holding the source snapshots and outputs.
        unconditional: Whether to bypass prior full and differential histories and
            refresh the fire index.
    """
    peri_scribe.fires.differential.write_history_of_differential_geography(
        year_directory,
        unconditional=unconditional,
    )


def run_score_stage(year_directory: pathlib.Path) -> None:
    """Score fires from the derived geography.

    Args:
        year_directory: Directory containing the year's source snapshots and derived
            outputs.
    """
    peri_scribe.fires.scores.score_fires(year_directory)


def run_kmz_stage(
    year_directory: pathlib.Path,
    *,
    publication_inputs: peri_scribe.publication.Collection | None = None,
) -> None:
    """Build the symbolized KMZ for Google Earth.

    Args:
        year_directory: The year directory containing derived geography and scores.
        publication_inputs: Frozen source inputs to acknowledge after KMZ completion, or
            None when no publication checkpoint is requested.
    """
    if publication_inputs is None:
        peri_scribe.kml.builder.create_kmz(year_directory)
    else:
        peri_scribe.kml.builder.create_kmz(
            year_directory,
            publication_inputs=publication_inputs,
        )


def run_reports_stage(year_directory: pathlib.Path) -> None:
    """Write fire reports from the derived outputs.

    Args:
        year_directory: Directory containing the year's source snapshots and derived
            outputs.
    """
    write_reports(year_directory)


@dataclasses.dataclass(frozen=True, kw_only=True)
class PipelineStage:
    """A named pipeline stage and its description."""

    name: peri_scribe.pipeline_stages.Stage
    description: str


PIPELINE_STAGES: tuple[PipelineStage, ...] = (
    PipelineStage(
        name=peri_scribe.pipeline_stages.Stage.FETCH,
        description=(
            "Fetch fire feeds, external sources (buildings, evacuations, and "
            "major cities), and the administrative-boundary GeoPackage."
        ),
    ),
    PipelineStage(
        name=peri_scribe.pipeline_stages.Stage.GEOGRAPHY,
        description="Derive fire geography histories from the fetched sources.",
    ),
    PipelineStage(
        name=peri_scribe.pipeline_stages.Stage.SCORE,
        description="Score fires from the derived geography.",
    ),
    PipelineStage(
        name=peri_scribe.pipeline_stages.Stage.KMZ,
        description="Build the symbolized KMZ for Google Earth.",
    ),
    PipelineStage(
        name=peri_scribe.pipeline_stages.Stage.REPORTS,
        description="Write fire reports from the derived outputs.",
    ),
)


STAGE_NAMES = tuple(stage.name.value for stage in PIPELINE_STAGES)


STAGE_INDEX = {stage.name: index for index, stage in enumerate(PIPELINE_STAGES)}


def run_pipeline_stage(
    stage: PipelineStage,
    year_directory: pathlib.Path,
    *,
    full_fetch_interval: datetime.timedelta | None,
    unconditional: bool,
    publish_threshold: peri_scribe.publication.Threshold | None = None,
    publication_inputs: peri_scribe.publication.Collection | None = None,
) -> bool:
    """Run *stage* and return whether the next stage should run.

    Args:
        stage: The pipeline stage to run.
        year_directory: The year directory that holds the pipeline data.
        full_fetch_interval: How often the fetch stage fetches every feed in full, or
            None to always fetch incrementally.
        unconditional: Whether to continue after an unchanged fetch and bypass prior
            history reuse in the geography stage.
        publish_threshold: The optional area and elapsed-time publication gate.
        publication_inputs: Source inventory frozen after this run's geography stage.

    Returns:
        True when the next stage should run.
    """
    with peri_scribe.logging.log_phase(stage.name):
        match stage.name:
            case peri_scribe.pipeline_stages.Stage.FETCH:
                return run_fetch_stage(
                    year_directory,
                    full_fetch_interval=full_fetch_interval,
                    unconditional=unconditional,
                    publish_threshold=publish_threshold,
                )
            case peri_scribe.pipeline_stages.Stage.GEOGRAPHY:
                run_geography_stage(year_directory, unconditional=unconditional)
            case peri_scribe.pipeline_stages.Stage.SCORE:
                run_score_stage(year_directory)
            case peri_scribe.pipeline_stages.Stage.KMZ:
                run_kmz_stage(year_directory, publication_inputs=publication_inputs)
                if publish_threshold is not None and publication_inputs is None:
                    peri_scribe.publication.publication_path(year_directory).unlink(
                        missing_ok=True,
                    )
                    logger.info(
                        "KMZ created without fresh geography; "
                        "publication checkpoint requires rebuild",
                    )
            case _:
                run_reports_stage(year_directory)
    return True


def print_stages() -> None:
    """Print the pipeline stages and their descriptions."""
    width = max(len(stage.name) for stage in PIPELINE_STAGES)
    for stage in PIPELINE_STAGES:
        click.echo(f"{stage.name:<{width}}  {stage.description}")


def selected_stage_range(
    only_stage: str | None,
    from_stage: str | None,
    to_stage: str | None,
) -> tuple[int, int]:
    """Return the inclusive indexes of the pipeline stages to run.

    Args:
        only_stage: The single stage to run, or None to use ``from_stage``/``to_stage``.
        from_stage: The first stage to run, or None for the first pipeline stage.
        to_stage: The last stage to run, or None for the last pipeline stage.

    Returns:
        A ``(start, end)`` pair of inclusive indexes into ``PIPELINE_STAGES``.

    Raises:
        click.UsageError: When ``from_stage`` comes after ``to_stage``.
    """
    if only_stage is not None:
        index = STAGE_INDEX[peri_scribe.pipeline_stages.Stage(only_stage)]
        return index, index
    start = (
        STAGE_INDEX[peri_scribe.pipeline_stages.Stage(from_stage)]
        if from_stage is not None
        else 0
    )
    end = (
        STAGE_INDEX[peri_scribe.pipeline_stages.Stage(to_stage)]
        if to_stage is not None
        else len(PIPELINE_STAGES) - 1
    )
    if start > end:
        message = (
            f"--from {from_stage or PIPELINE_STAGES[0].name} cannot follow "
            f"--to {to_stage or PIPELINE_STAGES[-1].name}"
        )
        raise click.UsageError(message)
    return start, end


@click.command(
    help=textwrap.dedent(
        f"""\
        Run the PeriScribe pipeline.

        The pipeline is fetch, geography, score, kmz, reports, run in order. By default
        the full pipeline runs. The fetch stage fetches every configured fire feed, the
        external sources (buildings, evacuations, and major cities), and the
        administrative-boundary GeoPackage, which is downloaded only when it is missing
        or unusable. When the fetch wrote a new fire snapshot or replaced the stored
        evacuations, the remaining stages run; otherwise the pipeline ends after fetch.
        --full-fetch-interval schedules a full fetch of every fire feed (storing only
        new or changed features), catching source edits the incremental fetch would
        miss: the first run with the option fetches in full, and a later run fetches in
        full whenever the last successful full fetch is at least that long ago. Without
        the option every fire-feed fetch is incremental. A scheduled full fetch forces a
        complete derived rebuild even when no features changed. Failed builds resume on
        subsequent runs. --unconditional rebuilds the selected stages without reusing
        prior geography; static feeds such as buildings are downloaded only when
        missing, whether or not --unconditional is given.

        Select a single stage with --only, a range with --from and --to, or list the
        stages with --list-stages. An error in any step stops the pipeline.
        --publish-threshold AREA TIME_DELTA saves fire geometry and checks evacuations
        before deciding whether to build outputs. A mapped-area increase or decrease of
        at least AREA since the last published mapping triggers a build. Otherwise,
        unpublished changes wait until TIME_DELTA since the last completed local KMZ.
        Evacuation changes, scheduled full fetches, failed builds, and --unconditional
        bypass the gate. For example: --publish-threshold "25 acre" 5m.
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
    type=(Area(), Duration()),
    callback=publication_threshold,
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
    type=Duration(),
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
    type=click.Choice(STAGE_NAMES, case_sensitive=False),
    help="Run only the named pipeline stage.",
)
@click.option(
    "--from",
    "from_stage",
    type=click.Choice(STAGE_NAMES, case_sensitive=False),
    help="Start the pipeline at the named stage (default: fetch).",
)
@click.option(
    "--to",
    "to_stage",
    type=click.Choice(STAGE_NAMES, case_sensitive=False),
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
    publish_threshold: peri_scribe.publication.Threshold | None = None,
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
        print_stages()
        return
    if only_stage is not None and (from_stage is not None or to_stage is not None):
        message = "--only cannot be combined with --from or --to"
        raise click.UsageError(message)
    start, end = selected_stage_range(only_stage, from_stage, to_stage)
    with peri_scribe.pipeline_state.run_lock(year_directory) as acquired:
        if not acquired:
            logger.info(
                "Another run owns this year; skipping invocation",
                year=str(year_directory),
            )
            return
        logger.info(
            "Planned phases",
            branches=peri_scribe.sources.catalog.configured_phase_branches(),
            gated=publish_threshold is not None,
            stages=tuple(stage.name for stage in PIPELINE_STAGES[start : end + 1]),
        )
        run_selected_stages(
            year_directory,
            start,
            end,
            full_fetch_interval=full_fetch_interval,
            unconditional=unconditional,
            publish_threshold=publish_threshold,
        )


def run_selected_stages(
    year_directory: pathlib.Path,
    start: int,
    end: int,
    *,
    full_fetch_interval: datetime.timedelta | None,
    unconditional: bool,
    publish_threshold: peri_scribe.publication.Threshold | None = None,
) -> None:
    """Keep recovery state until the required outputs have successfully completed.

    Args:
        year_directory: The year directory holding the pipeline data and run state.
        start: The inclusive zero-based index of the first selected pipeline stage.
        end: The inclusive zero-based index of the last selected pipeline stage.
        full_fetch_interval: How often to fetch every fire feed in full, or None to
            always fetch incrementally.
        unconditional: Whether to force the selected stages to rebuild, in addition to
            any unconditional requirement already recorded in recovery state.
        publish_threshold: The optional mapped-area and elapsed-time gate.
    """
    selected = tuple(
        stage.name
        for stage in PIPELINE_STAGES[start : end + 1]
        if stage.name != peri_scribe.pipeline_stages.Stage.FETCH
    )
    if selected and (unconditional or start > 0):
        peri_scribe.pipeline_state.require_stages(
            year_directory,
            selected,
            unconditional=unconditional,
        )
    publication_inputs = None
    for stage in PIPELINE_STAGES[start : end + 1]:
        pending = peri_scribe.pipeline_state.read_state(year_directory)
        should_continue = run_pipeline_stage(
            stage,
            year_directory,
            full_fetch_interval=full_fetch_interval,
            unconditional=(
                unconditional
                or (pending.unconditional and stage.name in pending.remaining)
            ),
            publish_threshold=publish_threshold,
            publication_inputs=publication_inputs,
        )
        if not should_continue and stage is not PIPELINE_STAGES[end]:
            if publish_threshold is None:
                logger.debug("Nothing changed; skipping remaining pipeline steps")
                peri_scribe.logging.skip_phases(
                    tuple(
                        item.name
                        for item in PIPELINE_STAGES[
                            STAGE_INDEX[stage.name] + 1 : end + 1
                        ]
                    ),
                    "No fire or evacuation data changed",
                )
            break
        if (
            stage.name == peri_scribe.pipeline_stages.Stage.GEOGRAPHY
            and publish_threshold is not None
        ):
            publication_inputs = peri_scribe.publication.collect(year_directory)
        peri_scribe.pipeline_state.complete_stage(year_directory, stage.name)


@click.command(
    help=textwrap.dedent(
        f"""\
        Validate that YEAR_DIRECTORY/sources covers a complete snapshot of every feed.

        Fetches every feed in full into YEAR_DIRECTORY/validation, then runs the
        incremental fetch so the stored sources reflect the same state, and compares the
        two. Problems are logged in a summary and the command still exits successfully,
        leaving validation in place for inspection; when no problems are found the
        directory is removed. {peri_scribe.cli_options.year_directory_default_help()}
        """,
    ),
)
@click.argument(
    "year_directory",
    callback=peri_scribe.cli_options.command_year_directory,
    type=click.Path(path_type=pathlib.Path, exists=True, file_okay=False),
    required=False,
)
@peri_scribe.logging.log_command
def validate_sources(year_directory: pathlib.Path) -> None:
    """Check that the stored sources cover a complete snapshot of every feed.

    Args:
        year_directory: Directory containing the year's source snapshots and derived
            outputs.
    """
    base_directory = peri_scribe.sources.snapshots.base_directory_for_year_directory(
        year_directory,
    )
    year = peri_scribe.paths.year_for_year_directory(year_directory)
    complete_directory = peri_scribe.sources.snapshots.validation_directory_path(
        year_directory,
    )
    peri_scribe.output.remove_directory_tree(complete_directory)
    peri_scribe.sources.fetching.fetch_all_feeds_complete(base_directory, year=year)
    peri_scribe.sources.fetching.fetch_all_feeds(base_directory, year=year)
    results = peri_scribe.sources.validation.validate_complete_sources(
        year_directory,
        peri_scribe.sources.feeds.FEEDS,
    )
    problem_results = [result for result in results if result.has_problems]
    if not problem_results:
        peri_scribe.output.remove_directory_tree(complete_directory)
        logger.info("Validated sources; no problems found")
        return
    for result in problem_results:
        logger.error(
            "Validation problems",
            feed=result.feed_name,
            complete_features=result.complete_feature_count,
            missing_features=len(result.missing_object_ids),
            mismatched_features=len(result.mismatched_object_ids),
            columns_missing_from_stored=sorted(result.columns_missing_from_stored),
        )
    logger.error(
        "Validation found problems in %d of %d feeds",
        len(problem_results),
        len(results),
    )
