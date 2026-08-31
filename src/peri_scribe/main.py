"""CLI entry point for peri_scribe — fetch and symbolize fire geography."""

from __future__ import annotations

import base64
import datetime
import pathlib

import click
import structlog

import peri_scribe.fires.differential
import peri_scribe.fires.scores
import peri_scribe.kml.builder
import peri_scribe.kml.colormap
import peri_scribe.kml.template
import peri_scribe.output
import peri_scribe.sources.administrative_boundaries
import peri_scribe.sources.digests
import peri_scribe.sources.external_sources
import peri_scribe.sources.feeds
import peri_scribe.sources.fetching
import peri_scribe.sources.snapshots
import peri_scribe.sources.validation


logger = structlog.get_logger()


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


@cli.command(
    help=(
        "Ensure the California administrative boundary is available.\n\n"
        "Writes or reuses the boundary GeoPackage at "
        "YEAR_DIRECTORY/sources/CA_border_with_AZ_NV_and_OR.gpkg. "
        f"{year_directory_default_help()}"
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
def ensure_admin_boundaries(year_directory: pathlib.Path | None = None) -> None:
    """Ensure needed administrative boundaries are available."""
    if year_directory is None:
        year_directory = default_year_directory()
    peri_scribe.sources.administrative_boundaries.ensure_administrative_boundaries(
        year_directory,
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


@cli.command(
    help=(
        "Fetch building centroids into YEAR_DIRECTORY.\n\n"
        "Reads the per-state download links from the Microsoft USBuildingFootprints "
        "repository page, downloads every US state's building-footprint archive, "
        "converts each footprint to its centroid point, and combines all of the "
        "points into a single GeoPackage at "
        "YEAR_DIRECTORY/sources/buildings.gpkg. An existing combined "
        "GeoPackage is left in place, and then neither the repository page nor any "
        "archive is downloaded. "
        f"{year_directory_default_help()}"
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
def fetch_buildings(year_directory: pathlib.Path | None = None) -> None:
    """Fetch building footprints for the year directory."""
    fetch_external_source(
        peri_scribe.sources.external_sources.BUILDINGS_SOURCE,
        year_directory,
    )


@cli.command(
    help=(
        "Fetch California evacuation zones into YEAR_DIRECTORY.\n\n"
        "Queries the Cal OES evacuation aggregation layer and keeps the latest "
        "version at YEAR_DIRECTORY/sources/evacuations.gpkg, "
        "replacing it whenever the layer's data changes. A fetch that fails "
        "logs a warning and keeps the stored version. "
        f"{year_directory_default_help()}"
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
def fetch_evacuations(year_directory: pathlib.Path | None = None) -> None:
    """Fetch evacuation zones for the year directory."""
    fetch_external_source(
        peri_scribe.sources.external_sources.EVACUATIONS_SOURCE,
        year_directory,
    )


@cli.command()
@click.option(
    "--force",
    is_flag=True,
    help="Write the KML template, even if it already exists.",
)
def create_kml_template(*, force: bool) -> None:
    """Generate the KML template used to specify symbolization."""
    output_path = peri_scribe.kml.template.create_template(force=force)
    if output_path is None:
        return
    logger.info("Wrote KML template", path=output_path)


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
def show_turbo_colormap(
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


@cli.command(
    help=(
        "Fetch all feeds and rebuild the KMZ for YEAR_DIRECTORY.\n\n"
        "The fetch step fetches every configured fire feed and the external "
        "sources (buildings, evacuations). When the fetch wrote a new fire "
        "snapshot or replaced the stored evacuations, the administrative "
        "boundaries are ensured and the full and differential geography "
        "history, fire scores, and KML for YEAR_DIRECTORY are built. --force "
        "fetches every "
        "incremental feed in full (storing only new or changed features), "
        "catching source edits the incremental fetch would miss, and runs the "
        "later steps even when nothing changed; static feeds such as buildings "
        "are downloaded only when missing, whether or not --force is given. "
        f"An error in any step stops the pipeline. {year_directory_default_help()}"
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
    "--force",
    is_flag=True,
    help=(
        "Fetch every incremental feed in full and run the later steps even "
        "when the fetch changed nothing."
    ),
)
def update_kmz(
    year_directory: pathlib.Path | None = None,
    *,
    force: bool = False,
) -> None:
    """Fetch new source data, score fires, and rebuild the KMZ."""
    if year_directory is None:
        year_directory = default_year_directory()
    result = peri_scribe.sources.fetching.fetch_all_feeds(
        peri_scribe.sources.snapshots.base_directory_for_year_directory(year_directory),
        year=peri_scribe.sources.snapshots.year_for_year_directory(year_directory),
        full=force,
    )
    evacuations_digest_before = stored_evacuations_digest(year_directory)
    for source in peri_scribe.sources.external_sources.EXTERNAL_SOURCES:
        fetch_external_source(source, year_directory)
    evacuations_changed = (
        stored_evacuations_digest(year_directory) != evacuations_digest_before
    )
    if not result.changed and not evacuations_changed and not force:
        logger.debug("Nothing changed; skipping remaining pipeline steps")
        return
    peri_scribe.sources.administrative_boundaries.ensure_administrative_boundaries(
        year_directory,
    )
    peri_scribe.fires.differential.write_history_of_differential_geography(
        year_directory,
    )
    peri_scribe.fires.scores.score_fires(year_directory)
    peri_scribe.kml.builder.create_kmz(year_directory)


@cli.command(
    help=(
        "Validate that YEAR_DIRECTORY/sources covers a complete snapshot of every "
        "feed.\n\n"
        "Fetches every feed in full into YEAR_DIRECTORY/validation, then runs "
        "the incremental fetch so the stored sources reflect the same state, and "
        "compares the two. Problems are logged in a summary and the command still "
        "exits successfully, leaving validation in place for inspection; when "
        "no problems are found the directory is removed. "
        f"{year_directory_default_help()}"
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
