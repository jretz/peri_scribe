"""CLI entry point for peri_scribe — fetch and symbolize fire geography."""

from __future__ import annotations

import base64
import dataclasses
import datetime
import importlib.metadata
import pathlib
import re
import textwrap

import click
import structlog

import peri_scribe.fires.differential
import peri_scribe.fires.scores
import peri_scribe.kml.builder
import peri_scribe.kml.colormap
import peri_scribe.output
import peri_scribe.report.gathering
import peri_scribe.report.markdown
import peri_scribe.sources.administrative_boundaries
import peri_scribe.sources.digests
import peri_scribe.sources.external_sources
import peri_scribe.sources.feeds
import peri_scribe.sources.fetching
import peri_scribe.sources.full_fetch_state
import peri_scribe.sources.snapshots
import peri_scribe.sources.validation


logger = structlog.get_logger()


class Duration(click.ParamType):
    """A duration of whole hours or days.

    Values are given as a non-negative whole number followed by ``h`` for hours or ``d``
    for days, for example ``12h`` or ``1d``, and convert to a ``datetime.timedelta``.
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
            f"{value!r} is not a duration of whole hours or days such as '12h' or '1d'"
        )
        if not isinstance(value, str):
            self.fail(message, param, ctx)
        duration_match = re.fullmatch(r"([0-9]+)([hd])", value)
        if duration_match is None:
            self.fail(message, param, ctx)
        count = int(duration_match.group(1))
        try:
            if duration_match.group(2) == "h":
                return datetime.timedelta(hours=count)
            return datetime.timedelta(days=count)
        except OverflowError:
            self.fail(f"{value!r} is too large to be a duration", param, ctx)


def default_year_directory() -> pathlib.Path:
    """Return the current year's data directory under the working directory.

    Returns:
        The path to ``data/<current year>`` under the current working directory.
    """
    return peri_scribe.sources.snapshots.year_directory_path(
        pathlib.Path.cwd(),
        datetime.date.today().year,
    )


@click.group()
@click.option(
    "--log-level",
    type=click.Choice(
        ["debug", "info", "warning", "error", "critical"],
        case_sensitive=False,
    ),
    default="info",
    show_default=True,
    help="Logging level.",
)
def cli(log_level: str) -> None:
    """
    A tool for systematic gathering and symbolization of fire geography, for use in fire
    behavior analysis and presentation.
    """
    peri_scribe.output.configure_logging(log_level)


def year_directory_default_help() -> str:
    """Return the help sentence naming the default year directory.

    The default moves forward each new year, so the sentence names the current year.

    Returns:
        The sentence naming the default year directory.
    """
    return (
        f"YEAR_DIRECTORY defaults to "
        f"{peri_scribe.output.DATA_DIRECTORY}/"
        f"{datetime.date.today().year}."
    )


def fetch_external_source(
    source: peri_scribe.sources.external_sources.ExternalSource,
    year_directory: pathlib.Path | None,
) -> None:
    """Fetch *source* into *year_directory*, resolving the default directory."""
    if year_directory is None:
        year_directory = default_year_directory()
    paths = peri_scribe.sources.external_sources.fetch_external_source(
        source,
        year_directory,
    )
    logger.info(
        "Fetched external source",
        source=source.name,
        paths=paths,
    )


@cli.command()
@click.option(
    "--trim-start",
    type=int,
    default=0,
    show_default=True,
    help="Colors to exclude from the start of the colormap.",
)
@click.option(
    "--trim-end",
    type=int,
    default=0,
    show_default=True,
    help="Colors to exclude from the end of the colormap.",
)
@click.option(
    "--output",
    type=click.Path(
        path_type=pathlib.Path,
        dir_okay=False,
        writable=True,
    ),
    help="Write the strip to this PNG file instead of printing it to the terminal.",
)
def show_colormap(
    *,
    trim_start: int,
    trim_end: int,
    output: pathlib.Path | None,
) -> None:
    """Print a Turbo colormap strip to the terminal as an inline image.

    The strip renders in memory and prints as an iTerm2 inline-image escape sequence
    (OSC 1337), which terminals including iTerm2 and WezTerm display directly in the
    terminal. The full 256-color colormap is shown unless --trim-start or --trim-end
    remove colors from the corresponding ends. With --output the strip is written to
    that file as a plain PNG instead.
    """
    png = peri_scribe.kml.colormap.turbo_colormap_png(
        trim_start=trim_start,
        trim_end=trim_end,
    )
    if output is None:
        encoded = base64.b64encode(png).decode("ascii")
        # The width parameter scales the inline image to the full terminal width;
        # without it iTerm2 sizes the image from its DPI metadata, which renders the
        # strip narrower than the window.
        click.echo(f"\x1b]1337;File=inline=1;width=100%:{encoded}\a")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(png)
        logger.info("Wrote Turbo colormap strip", path=output)


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
    source = peri_scribe.sources.external_sources.EVACUATIONS_SOURCE
    return peri_scribe.sources.digests.stored_geopackage_digest(
        peri_scribe.sources.external_sources.output_path(year_directory, source),
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


def run_fetch_stage(
    year_directory: pathlib.Path,
    *,
    full_fetch_interval: datetime.timedelta | None,
    unconditional: bool,
) -> bool:
    """Fetch fire feeds and external sources; return whether to keep going.

    The fetch stage always fetches every configured fire feed and the external sources
    (buildings, evacuations, and major cities). A full fire-feed fetch is run when
    *full_fetch_interval* is given and the last recorded full fetch, stored at
    ``YEAR_DIRECTORY/sources/fetch_state.json``, is at least that old; without an
    interval every fire-feed fetch is incremental. A completed full fetch records its
    completion time in the state file. The stage returns True when the fetch wrote a new
    fire snapshot or replaced the stored evacuations, or when *unconditional* is set,
    signalling that the remaining stages should run.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.
        full_fetch_interval: How often to fetch every fire feed in full, or None to
            always fetch incrementally.
        unconditional: Whether to run the later stages even when the fetch changed
            nothing.

    Returns:
        True when the remaining stages should run.
    """
    base_directory = peri_scribe.sources.snapshots.base_directory_for_year_directory(
        year_directory,
    )
    year = peri_scribe.sources.snapshots.year_for_year_directory(year_directory)
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
    result = peri_scribe.sources.fetching.fetch_all_feeds(
        base_directory,
        year=year,
        full=full,
    )
    if full:
        peri_scribe.sources.full_fetch_state.write_state(
            state_file,
            last_full_fetch=datetime.datetime.now(datetime.UTC),
        )
    evacuations_digest_before = stored_evacuations_digest(year_directory)
    for source in peri_scribe.sources.external_sources.EXTERNAL_SOURCES:
        fetch_external_source(source, year_directory)
    evacuations_changed = (
        stored_evacuations_digest(year_directory) != evacuations_digest_before
    )
    return result.changed or evacuations_changed or unconditional


def run_geography_stage(year_directory: pathlib.Path) -> None:
    """Ensure administrative boundaries and derive fire geography histories."""
    peri_scribe.sources.administrative_boundaries.ensure_administrative_boundaries(
        year_directory,
    )
    peri_scribe.fires.differential.write_history_of_differential_geography(
        year_directory,
    )


def run_score_stage(year_directory: pathlib.Path) -> None:
    """Score fires from the derived geography."""
    peri_scribe.fires.scores.score_fires(year_directory)


def run_kmz_stage(year_directory: pathlib.Path) -> None:
    """Build the symbolized KMZ for Google Earth."""
    peri_scribe.kml.builder.create_kmz(year_directory)


def run_reports_stage(year_directory: pathlib.Path) -> None:
    """Write fire reports from the derived outputs."""
    write_reports(year_directory)


@dataclasses.dataclass(frozen=True, kw_only=True)
class PipelineStage:
    """A named pipeline stage and its description."""

    name: str
    description: str


PIPELINE_STAGES: tuple[PipelineStage, ...] = (
    PipelineStage(
        name="fetch",
        description=(
            "Fetch fire feeds and external sources (buildings, evacuations, and "
            "major cities)."
        ),
    ),
    PipelineStage(
        name="geography",
        description=(
            "Ensure administrative boundaries and derive fire geography histories."
        ),
    ),
    PipelineStage(
        name="score",
        description="Score fires from the derived geography.",
    ),
    PipelineStage(
        name="kmz",
        description="Build the symbolized KMZ for Google Earth.",
    ),
    PipelineStage(
        name="reports",
        description="Write fire reports from the derived outputs.",
    ),
)

STAGE_NAMES = tuple(stage.name for stage in PIPELINE_STAGES)
STAGE_INDEX = {stage.name: index for index, stage in enumerate(PIPELINE_STAGES)}


def run_pipeline_stage(
    stage: PipelineStage,
    year_directory: pathlib.Path,
    *,
    full_fetch_interval: datetime.timedelta | None,
    unconditional: bool,
) -> bool:
    """Run *stage* and return whether the next stage should run.

    Args:
        stage: The pipeline stage to run.
        year_directory: The year directory that holds the pipeline data.
        full_fetch_interval: How often the fetch stage fetches every feed in full, or
            None to always fetch incrementally.
        unconditional: Whether the fetch stage should run the later stages even when
            nothing changed.

    Returns:
        True when the next stage should run.
    """
    match stage.name:
        case "fetch":
            return run_fetch_stage(
                year_directory,
                full_fetch_interval=full_fetch_interval,
                unconditional=unconditional,
            )
        case "geography":
            run_geography_stage(year_directory)
        case "score":
            run_score_stage(year_directory)
        case "kmz":
            run_kmz_stage(year_directory)
        case "reports":
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
        index = STAGE_INDEX[only_stage]
        return index, index
    start = STAGE_INDEX[from_stage] if from_stage is not None else 0
    end = STAGE_INDEX[to_stage] if to_stage is not None else len(PIPELINE_STAGES) - 1
    if start > end:
        message = (
            f"--from {from_stage or PIPELINE_STAGES[0].name} cannot follow "
            f"--to {to_stage or PIPELINE_STAGES[-1].name}"
        )
        raise click.UsageError(message)
    return start, end


@cli.command(
    help=textwrap.dedent(
        f"""\
        Run the PeriScribe pipeline.

        The pipeline is fetch, geography, score, kmz, reports, run in order. By default
        the full pipeline runs. The fetch stage fetches every configured fire feed and
        the external sources (buildings, evacuations, and major cities). When the fetch
        wrote a new fire snapshot or replaced the stored evacuations, the remaining
        stages run; otherwise the pipeline ends after fetch. --full-fetch-interval
        schedules a full fetch of every fire feed (storing only new or changed
        features), catching source edits the incremental fetch would miss: the first run
        with the option fetches in full, and a later run fetches in full whenever the
        last successful full fetch is at least that long ago. Without the option every
        fire-feed fetch is incremental. --unconditional runs the remaining stages even
        when nothing changed; static feeds such as buildings are downloaded only when
        missing, whether or not --unconditional is given.

        Select a single stage with --only, a range with --from and --to, or list the
        stages with --list-stages. An error in any step stops the pipeline.
        {year_directory_default_help()}
        """,
    ),
)
@click.argument(
    "year_directory",
    type=click.Path(
        path_type=pathlib.Path,
        exists=True,
        file_okay=False,
    ),
    required=False,
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
    help="Run the later stages even when the fetch changed nothing.",
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
def run(
    year_directory: pathlib.Path | None = None,
    *,
    full_fetch_interval: datetime.timedelta | None = None,
    unconditional: bool = False,
    only_stage: str | None = None,
    from_stage: str | None = None,
    to_stage: str | None = None,
    list_stages: bool = False,
) -> None:
    """Run the selected pipeline stages.

    Raises:
        click.UsageError: When the stage selection is invalid.
    """
    if list_stages:
        print_stages()
        return
    if year_directory is None:
        year_directory = default_year_directory()
    if only_stage is not None and (from_stage is not None or to_stage is not None):
        message = "--only cannot be combined with --from or --to"
        raise click.UsageError(message)
    start, end = selected_stage_range(only_stage, from_stage, to_stage)
    for stage in PIPELINE_STAGES[start : end + 1]:
        should_continue = run_pipeline_stage(
            stage,
            year_directory,
            full_fetch_interval=full_fetch_interval,
            unconditional=unconditional,
        )
        if not should_continue and stage is not PIPELINE_STAGES[end]:
            logger.debug("Nothing changed; skipping remaining pipeline steps")
            break


@cli.command(
    help=textwrap.dedent(
        f"""\
        Validate that YEAR_DIRECTORY/sources covers a complete snapshot of every feed.

        Fetches every feed in full into YEAR_DIRECTORY/validation, then runs the
        incremental fetch so the stored sources reflect the same state, and compares the
        two. Problems are logged in a summary and the command still exits successfully,
        leaving validation in place for inspection; when no problems are found the
        directory is removed. {year_directory_default_help()}
        """,
    ),
)
@click.argument(
    "year_directory",
    type=click.Path(
        path_type=pathlib.Path,
        exists=True,
        file_okay=False,
    ),
    required=False,
)
def validate_sources(year_directory: pathlib.Path | None = None) -> None:
    """Check that the stored sources cover a complete snapshot of every feed."""
    if year_directory is None:
        year_directory = default_year_directory()
    base_directory = peri_scribe.sources.snapshots.base_directory_for_year_directory(
        year_directory,
    )
    year = peri_scribe.sources.snapshots.year_for_year_directory(year_directory)
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


def distribution_version() -> str:
    """Return the installed peri_scribe distribution's version.

    ``__package__`` names the package this module belongs to, and the distribution is
    installed under that same name, so it supplies the metadata lookup name without
    repeating it in source here. The version comes from the installed distribution's
    metadata rather than from source, so it cannot drift from the released version.

    Returns:
        The installed distribution's version string.

    Raises:
        RuntimeError: If the module was not imported as part of its package, so the
            distribution name is unknown.
    """
    if __package__ is None:
        message = (
            "the installed distribution name is unknown because this module was "
            "not imported as part of its package"
        )
        raise RuntimeError(message)
    version = importlib.metadata.version(__package__)
    return f"{__package__} v{version}"


@cli.command()
def version() -> None:
    """Print the installed peri_scribe version."""
    click.echo(distribution_version())
