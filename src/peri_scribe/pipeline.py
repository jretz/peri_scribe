"""Pipeline commands load their generation dependencies only when selected.

Algorithm reasoning and contracts:
[Pipeline publication](../../docs/algorithms/pipeline-publication.md)
[Supervised stage processes](../../docs/algorithms/stage-processes.md)
"""

from __future__ import annotations

import datetime
import pathlib
import textwrap

import click
import structlog

import peri_scribe.cli_options
import peri_scribe.execution
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
import peri_scribe.preparation
import peri_scribe.publication
import peri_scribe.report.gathering
import peri_scribe.report.markdown
import peri_scribe.sources.administrative_boundaries
import peri_scribe.sources.catalog
import peri_scribe.sources.cities
import peri_scribe.sources.digests
import peri_scribe.sources.external_data
import peri_scribe.sources.external_sources
import peri_scribe.sources.feeds
import peri_scribe.sources.fetching
import peri_scribe.sources.full_fetch_state
import peri_scribe.sources.snapshots
import peri_scribe.sources.validation
import peri_scribe.supervision


logger = structlog.get_logger()


Duration = peri_scribe.cli_options.Duration
Area = peri_scribe.cli_options.Area
publication_threshold = peri_scribe.cli_options.publication_threshold


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


@click.command(
    help=textwrap.dedent(
        """\
        Preview the progression-ring colors in a truecolor terminal.

        The strip shows all 256 Turbo colors. Labels on the left identify every 16th
        color, and a marker on the right shows the range used for progression rings,
        with labels at both endpoints. This lets you compare the chosen range with the
        excluded colors. Use --trim-start and --trim-end to preview different endpoints.
        """,
    ),
)
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
    """Preview the progression-ring colors in a truecolor terminal.

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

    Its fetch replaces the stored GeoPackage only when the layer's features changed,
    so comparing the digest before and after the fetch reports content changes.

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

    Ungated collection records the work needed for recovery before changing source data.
    A later fetch failure can therefore leave that work pending. The prior requirements
    can be restored only after a successful, unchanged incremental fetch with no
    deferred inputs.

    Args:
        year_directory: The directory holding the year's sources and outputs.
        full_fetch_interval: How often to force full collection, or None.
        unconditional: Bypass change-based skipping.
        publish_threshold: Area and time requirements for deferred publication.

    Returns:
        Whether the selected downstream stages should run.
    """
    if publish_threshold is not None:
        return run_gated_fetch_stage(
            year_directory,
            full_fetch_interval=full_fetch_interval,
            unconditional=unconditional,
            threshold=publish_threshold,
        )
    previous = peri_scribe.pipeline_state.read_state(year_directory)
    deferred = peri_scribe.pipeline_state.deferred_inputs_path(year_directory).exists()
    peri_scribe.pipeline_state.require_stages(
        year_directory,
        peri_scribe.pipeline_state.DERIVED_STAGES,
    )
    peri_scribe.pipeline_state.clear_deferred_inputs(year_directory)
    result, full = fetch_fire_sources(
        year_directory,
        full_fetch_interval=full_fetch_interval,
    )
    external_changed = refresh_external_sources(year_directory)
    if not (result.changed or external_changed or full or deferred):
        peri_scribe.pipeline_state.write_state(year_directory, previous)
    return (
        result.changed
        or external_changed
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
    """Check live reference data and retained geometry before deciding to publish.

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
    peri_scribe.pipeline_state.defer_inputs(year_directory)
    _result, full = fetch_fire_sources(
        year_directory,
        full_fetch_interval=full_fetch_interval,
        defer_index=True,
    )
    try:
        for phase, source in (
            (
                peri_scribe.phases.Phase.EVACUATION_CHECK,
                peri_scribe.sources.catalog.EVACUATIONS_SOURCE,
            ),
            (
                peri_scribe.phases.Phase.CITY_CHECK,
                peri_scribe.sources.catalog.CITIES_SOURCE,
            ),
        ):
            with peri_scribe.logging.log_phase(phase):
                fetch_external_source(source, year_directory)
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
        if decision.reason == peri_scribe.publication.Reason.NO_CHANGES:
            peri_scribe.pipeline_state.clear_deferred_inputs(year_directory)
        peri_scribe.logging.skip_phases(
            (peri_scribe.phases.Phase.DEFERRED_FETCH,),
            decision.reason,
        )
        return False
    peri_scribe.pipeline_state.require_stages(
        year_directory,
        peri_scribe.pipeline_state.DERIVED_STAGES,
    )
    peri_scribe.pipeline_state.clear_deferred_inputs(year_directory)
    with peri_scribe.logging.log_phase(peri_scribe.phases.Phase.DEFERRED_FETCH):
        prepare_administrative_boundaries(year_directory)
        peri_scribe.fires.index.index_fire_sources(year_directory)
        if full:
            peri_scribe.sources.full_fetch_state.write_state(
                peri_scribe.sources.full_fetch_state.state_path(year_directory),
                last_full_fetch=datetime.datetime.now(datetime.UTC),
            )
        refresh_external_sources(
            year_directory,
            include_evacuations=False,
            include_cities=False,
        )
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
    include_cities: bool = True,
) -> bool:
    """Observe reference-data changes independently of fire-feed completion.

    Args:
        year_directory: The year directory holding the external source data.
        include_evacuations: Fetch evacuations here when they were not checked before
            the publication gate.
        include_cities: Fetch cities here when they were not checked before the gate.

    Returns:
        Whether evacuation geography or city locations changed.
    """
    with peri_scribe.logging.log_phase(
        peri_scribe.phases.Phase.EXTERNAL_SOURCE_REFRESH,
    ):
        evacuations_digest_before = (
            stored_evacuations_digest(year_directory) if include_evacuations else None
        )
        cities_digest_before = (
            peri_scribe.sources.cities.database_digest(year_directory)
            if include_cities
            else None
        )
        for source in peri_scribe.sources.catalog.EXTERNAL_SOURCES:
            if (
                not include_evacuations
                and source is peri_scribe.sources.catalog.EVACUATIONS_SOURCE
            ):
                continue
            if (
                not include_cities
                and source is peri_scribe.sources.catalog.CITIES_SOURCE
            ):
                continue
            fetch_external_source(source, year_directory)
        return (
            include_evacuations
            and stored_evacuations_digest(year_directory) != evacuations_digest_before
        ) or (
            include_cities
            and peri_scribe.sources.cities.database_digest(year_directory)
            != cities_digest_before
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
    for group in (
        peri_scribe.execution.Group.DERIVED,
        peri_scribe.execution.Group.HISTORIES,
        peri_scribe.execution.Group.PRESENTATION,
    ):
        peri_scribe.execution.clear(group)
    try:
        peri_scribe.fires.differential.write_history_of_differential_geography(
            year_directory,
            unconditional=unconditional,
        )
    finally:
        peri_scribe.execution.clear(peri_scribe.execution.Group.SOURCES)


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


PipelineStage = peri_scribe.cli_options.PipelineStage
PIPELINE_STAGES = peri_scribe.cli_options.PIPELINE_STAGES
STAGE_NAMES = peri_scribe.cli_options.STAGE_NAMES
STAGE_INDEX = peri_scribe.cli_options.STAGE_INDEX


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


print_stages = peri_scribe.cli_options.print_stages
selected_stage_range = peri_scribe.cli_options.selected_stage_range


run = peri_scribe.supervision.run


@peri_scribe.preparation.cached_year
def run_selected_stages(
    year_directory: pathlib.Path,
    start: int,
    end: int,
    *,
    full_fetch_interval: datetime.timedelta | None,
    unconditional: bool,
    publish_threshold: peri_scribe.publication.Threshold | None = None,
    initialize: bool = True,
    stop_after_geography: bool = False,
    publication_inputs: peri_scribe.publication.Collection | None = None,
) -> peri_scribe.supervision.SegmentResult:
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
        initialize: Record selected work once at the beginning of the logical run.
        stop_after_geography: Return a continuation after successful geography.
        publication_inputs: Exact frozen inputs handed off by the geography process.

    Returns:
        Continuation state only after a completed segment or an unchanged fetch.
    """
    selected = tuple(
        stage.name
        for stage in PIPELINE_STAGES[start : end + 1]
        if stage.name != peri_scribe.pipeline_stages.Stage.FETCH
    )
    if initialize and selected and (unconditional or start > 0):
        peri_scribe.pipeline_state.require_stages(
            year_directory,
            selected,
            unconditional=unconditional,
        )
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
                    "No fire, evacuation, or city data changed",
                )
            break
        if (
            stage.name == peri_scribe.pipeline_stages.Stage.GEOGRAPHY
            and publish_threshold is not None
        ):
            publication_inputs = peri_scribe.publication.collect(year_directory)
        peri_scribe.pipeline_state.complete_stage(year_directory, stage.name)
        if (
            stop_after_geography
            and stage.name == peri_scribe.pipeline_stages.Stage.GEOGRAPHY
        ):
            return peri_scribe.supervision.SegmentResult(
                next_stage=STAGE_INDEX[stage.name] + 1,
                publication_inputs=(
                    None
                    if publication_inputs is None
                    else publication_inputs.model_dump_json()
                ),
            )
    return peri_scribe.supervision.SegmentResult()


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
    with peri_scribe.pipeline_state.run_lock(year_directory) as acquired:
        if not acquired:
            logger.info(
                "Another writer owns this year; skipping validation",
                year=str(year_directory),
            )
            return
        validate_locked_sources(year_directory)


def validate_locked_sources(year_directory: pathlib.Path) -> None:
    """Retain rebuild intent when validation's incremental fetch changes source data.

    Args:
        year_directory: The year whose exclusive writer lock is held by the caller.
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
    previous = peri_scribe.pipeline_state.read_state(year_directory)
    peri_scribe.pipeline_state.require_stages(
        year_directory,
        peri_scribe.pipeline_state.DERIVED_STAGES,
    )
    collected = peri_scribe.sources.fetching.fetch_all_feeds(base_directory, year=year)
    if not collected.changed:
        peri_scribe.pipeline_state.write_state(year_directory, previous)
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
            duplicate_complete_object_ids=sorted(result.duplicate_complete_object_ids),
            duplicate_stored_object_ids=sorted(result.duplicate_stored_object_ids),
            coordinate_reference_mismatch=result.coordinate_reference_mismatch,
        )
    logger.error(
        "Feeds with validation problems: %d of %d",
        len(problem_results),
        len(results),
    )
