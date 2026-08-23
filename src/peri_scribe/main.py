"""CLI entry point for peri_scribe — fetch and symbolize fire geography."""

from __future__ import annotations

import datetime
import pathlib

import click
import structlog

import peri_scribe.administrative_boundaries
import peri_scribe.feeds
import peri_scribe.fetching
import peri_scribe.fire_differential
import peri_scribe.fire_index
import peri_scribe.kml
import peri_scribe.kml_template
import peri_scribe.output
import peri_scribe.snapshots


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
def fetch() -> None:
    """Fetch each configured feed into a GeoPackage."""
    peri_scribe.fetching.fetch_all_feeds()


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


@cli.command()
def ensure_admin_boundaries() -> None:
    """Ensure needed administrative boundaries are available."""
    peri_scribe.administrative_boundaries.ensure_administrative_boundaries()


@cli.command(
    help=(
        "Derive the full and differential point and perimeter history for "
        "YEAR_DIRECTORY.\n\n"
        "Builds and writes both "
        "YEAR_DIRECTORY/derived/history_of_full_geography.gpkg and "
        "YEAR_DIRECTORY/derived/history_of_differential_geography.gpkg with a "
        "perimeter_history layer of per-perimeter growth and a point_history layer. "
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
        "fetch changed nothing; an error in any step stops the pipeline. "
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
def full_pipeline(
    year_directory: pathlib.Path | None = None,
    *,
    force: bool = False,
) -> None:
    """Check for new source data and use it to generate new maps."""
    if year_directory is None:
        year_directory = default_year_directory()
    result = peri_scribe.fetching.fetch_all_feeds()
    if not result.changed and not force:
        logger.info("Nothing changed; skipping remaining pipeline steps")
        return
    peri_scribe.administrative_boundaries.ensure_administrative_boundaries()
    peri_scribe.fire_differential.write_history_of_differential_geography(
        year_directory,
    )
    peri_scribe.kml.create_kmz(year_directory)
