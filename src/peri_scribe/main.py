"""CLI entry point for peri_scribe — fetch and symbolize fire geography."""

from __future__ import annotations

import datetime
import pathlib

import click
import structlog

import peri_scribe.administrative_boundaries
import peri_scribe.external_sources
import peri_scribe.feeds
import peri_scribe.fetching
import peri_scribe.fire_differential
import peri_scribe.fire_index
import peri_scribe.fire_scores
import peri_scribe.kml
import peri_scribe.kml_template
import peri_scribe.output
import peri_scribe.snapshots
import peri_scribe.source_validation


logger = structlog.get_logger()


def default_year_directory() -> pathlib.Path:
    """Return the current year's data directory under the working directory.

    Returns:
        The path to ``data/<current year>`` under the current working directory.
    """
    return peri_scribe.snapshots.year_directory_path(
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


@cli.command()
@click.option(
    "--full",
    is_flag=True,
    help=(
        "Fetch every feed in full, storing only features that are new or changed "
        "since the stored snapshots."
    ),
)
def fetch(*, full: bool) -> None:
    """Fetch each configured feed into a GeoPackage."""
    peri_scribe.fetching.fetch_all_feeds(full=full)


@cli.command()
def current_timestamps() -> None:
    """Log the current last-edit timestamp for each configured feed."""
    for index, feed in enumerate(peri_scribe.feeds.FEEDS, start=1):
        logger.info(
            "Feed %d",
            index,
            name=feed.name,
            url=feed.url,
            last_edit_timestamp=feed.current_last_edit_timestamp,
        )


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
        "Log the name, status, and identifier of each fire.\n\n"
        "Reads YEAR_DIRECTORY/sources/fires.json, building it from the GeoPackage "
        f"files first when it is missing. {year_directory_default_help()}"
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
def list_fires(year_directory: pathlib.Path | None = None) -> None:
    if year_directory is None:
        year_directory = default_year_directory()
    for index, fire in enumerate(
        peri_scribe.fire_index.load_fire_index(year_directory).fires,
        start=1,
    ):
        logger.info(
            "Fire %d",
            index,
            name=fire.name,
            status=fire.status,
            identifier=fire.identifier,
        )


@cli.command(
    help=(
        "Build the fire source index for YEAR_DIRECTORY.\n\n"
        "The index is written to YEAR_DIRECTORY/sources/fires.json. "
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
def index_fire_sources(year_directory: pathlib.Path | None = None) -> None:
    if year_directory is None:
        year_directory = default_year_directory()
    peri_scribe.fire_index.index_fire_sources(year_directory)


@cli.command(
    help=(
        "Ensure the California administrative boundary is available.\n\n"
        "Writes or reuses the boundary GeoPackage under "
        "YEAR_DIRECTORY/sources/administrative_boundaries. "
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
    peri_scribe.administrative_boundaries.ensure_administrative_boundaries(
        year_directory,
    )


def fetch_external_source(
    source: peri_scribe.external_sources.ExternalSource,
    year_directory: pathlib.Path | None,
) -> None:
    """Fetch *source* into *year_directory*, resolving the default directory."""
    if year_directory is None:
        year_directory = default_year_directory()
    paths = peri_scribe.external_sources.fetch_external_source(
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
        "YEAR_DIRECTORY/sources/buildings/buildings.gpkg. An existing combined "
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
        peri_scribe.external_sources.BUILDINGS_SOURCE,
        year_directory,
    )


@cli.command(
    help=(
        "Fetch California evacuation zones into YEAR_DIRECTORY.\n\n"
        "Queries the Cal OES evacuation aggregation layer and stores a snapshot "
        "under YEAR_DIRECTORY/sources/evacuations whenever the layer's data "
        "changes, keeping the season's history. "
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
        peri_scribe.external_sources.EVACUATIONS_SOURCE,
        year_directory,
    )


@cli.command(
    help=(
        "Fetch NWS Red Flag Warnings into YEAR_DIRECTORY.\n\n"
        "Queries the NWS watches-and-warnings layer for Red Flag Warnings and Fire "
        "Weather Watches and stores a snapshot under "
        "YEAR_DIRECTORY/sources/red_flag_warnings whenever the layer's data "
        "changes, keeping the season's history. "
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
def fetch_red_flag_warnings(year_directory: pathlib.Path | None = None) -> None:
    """Fetch Red Flag Warnings for the year directory."""
    fetch_external_source(
        peri_scribe.external_sources.RED_FLAG_WARNINGS_SOURCE,
        year_directory,
    )


@cli.command(
    help=(
        "Fetch the wildland-urban interface (WUI) data into YEAR_DIRECTORY.\n\n"
        "Downloads the conterminous-US WUI file geodatabase archive, extracts "
        "it, and converts it to a GeoPackage under YEAR_DIRECTORY/sources/wui. "
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
def fetch_wui(year_directory: pathlib.Path | None = None) -> None:
    """Fetch wildland-urban interface data for the year directory."""
    fetch_external_source(
        peri_scribe.external_sources.WUI_SOURCE,
        year_directory,
    )


@cli.command(
    help=(
        "Derive the full and differential point and perimeter history for "
        "YEAR_DIRECTORY, then score each fire.\n\n"
        "Builds and writes both "
        "YEAR_DIRECTORY/derived/history_of_full_geography.gpkg and "
        "YEAR_DIRECTORY/derived/history_of_differential_geography.gpkg with a "
        "perimeter_history layer of per-perimeter growth and a point_history layer, "
        "then writes each fire's score to "
        "YEAR_DIRECTORY/derived/fire_scores.json. "
        f" {year_directory_default_help()}"
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
def derive_geo_history(year_directory: pathlib.Path | None = None) -> None:
    if year_directory is None:
        year_directory = default_year_directory()
    output_path = peri_scribe.fire_differential.write_history_of_differential_geography(
        year_directory,
    )
    logger.info("Wrote differential history", path=output_path)
    scores_path = peri_scribe.fire_scores.score_fires(year_directory)
    logger.info("Wrote fire scores", path=scores_path)


@cli.command()
@click.option(
    "--force",
    is_flag=True,
    help="Write the KML template, even if it already exists.",
)
def create_kml_template(*, force: bool) -> None:
    """Generate the KML template used to specify symbolization."""
    output_path = peri_scribe.kml_template.create_template(force=force)
    if output_path is None:
        return
    logger.info("Wrote KML template", path=output_path)


@cli.command(
    help=(
        "Build the KML output for YEAR_DIRECTORY.\n\n"
        "Reads YEAR_DIRECTORY/derived/history_of_full_geography.gpkg and writes a "
        "compressed KMZ file to YEAR_DIRECTORY/maps. "
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
def create_kml(year_directory: pathlib.Path | None = None) -> None:
    if year_directory is None:
        year_directory = default_year_directory()
    output_path = peri_scribe.kml.create_kmz(year_directory)
    logger.info("Wrote KMZ", path=output_path)


@cli.command(
    help=(
        "Fetch feeds, then derive and symbolize fire geography for "
        "YEAR_DIRECTORY.\n\n"
        "Runs the fetch step first and exits when it wrote no new snapshot. "
        "When the fetch changed something, the administrative boundaries are "
        "ensured and the full and differential geography history and KML for "
        "YEAR_DIRECTORY are built. --force runs the later steps even when the "
        "fetch changed nothing; --full fetches every feed in full (storing only "
        "new or changed features), catching source edits the incremental fetch "
        "would miss; an error in any step stops the pipeline. "
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
@click.option(
    "--force",
    is_flag=True,
    help="Run the later steps even when the fetch changed nothing.",
)
@click.option(
    "--full",
    is_flag=True,
    help="Fetch every feed in full instead of only changed features.",
)
def full_pipeline(
    year_directory: pathlib.Path | None = None,
    *,
    force: bool = False,
    full: bool = False,
) -> None:
    """Check for new source data and use it to generate new maps."""
    if year_directory is None:
        year_directory = default_year_directory()
    result = peri_scribe.fetching.fetch_all_feeds(
        peri_scribe.snapshots.base_directory_for_year_directory(year_directory),
        year=peri_scribe.snapshots.year_for_year_directory(year_directory),
        full=full,
    )
    if not result.changed and not force:
        logger.debug("Nothing changed; skipping remaining pipeline steps")
        return
    peri_scribe.administrative_boundaries.ensure_administrative_boundaries(
        year_directory,
    )
    peri_scribe.fire_differential.write_history_of_differential_geography(
        year_directory,
    )
    peri_scribe.kml.create_kmz(year_directory)


@cli.command(
    help=(
        "Validate that YEAR_DIRECTORY/sources covers a complete snapshot of every "
        "feed.\n\n"
        "Fetches every feed in full into YEAR_DIRECTORY/sources-complete, then runs "
        "the incremental fetch so the stored sources reflect the same state, and "
        "compares the two. Problems are logged in a summary and the command still "
        "exits successfully, leaving sources-complete in place for inspection; when "
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
    base_directory = peri_scribe.snapshots.base_directory_for_year_directory(
        year_directory,
    )
    year = peri_scribe.snapshots.year_for_year_directory(year_directory)
    complete_directory = peri_scribe.snapshots.sources_complete_directory_path(
        year_directory,
    )
    peri_scribe.output.remove_directory_tree(complete_directory)
    peri_scribe.fetching.fetch_all_feeds_complete(base_directory, year=year)
    peri_scribe.fetching.fetch_all_feeds(base_directory, year=year)
    results = peri_scribe.source_validation.validate_complete_sources(
        year_directory,
        peri_scribe.feeds.FEEDS,
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
