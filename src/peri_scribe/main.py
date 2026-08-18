"""CLI entry point for peri_scribe — fetch and symbolize fire geography."""

from __future__ import annotations

import datetime
import pathlib

import click
import structlog

import peri_scribe.administrative_boundaries
import peri_scribe.models
import peri_scribe.operations
import peri_scribe.output


logger = structlog.get_logger()


def default_year_directory() -> pathlib.Path:
    """Return the current year's data directory under the working directory.

    Returns:
        The path to ``data/<current year>`` under the current working directory.
    """
    return peri_scribe.operations.year_directory_path(
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
    peri_scribe.operations.fetch_all_feeds()


@cli.command()
def feed_config() -> None:
    """Log the configured feeds."""
    for i, feed in enumerate(peri_scribe.models.FEEDS):
        logger.info(
            "Feed %d",
            i + 1,
            feed_type=type(feed).__name__,
            name=feed.name,
            url=feed.url,
        )


@cli.command()
def current_watermarks() -> None:
    """Log the current watermark for each configured feed."""
    for index, feed in enumerate(peri_scribe.models.FEEDS, start=1):
        logger.info(
            "Feed %d",
            index,
            name=feed.name,
            url=feed.url,
            watermark=feed.current_watermark,
        )


def year_directory_default_help() -> str:
    """Return the help sentence naming the default year directory.

    The default moves forward each new year, so the sentence names the current year.

    Returns:
        The sentence naming the default year directory.
    """
    return (
        f"YEAR_DIRECTORY defaults to "
        f"{peri_scribe.operations.DATA_DIRECTORY_NAME}/"
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
        peri_scribe.operations.load_fire_index(year_directory).fires,
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
    peri_scribe.operations.index_fire_sources(year_directory)


@cli.command()
def ensure_admin_boundaries() -> None:
    """Ensure needed administrative boundaries are available."""
    peri_scribe.administrative_boundaries.ensure_administrative_boundaries()


if __name__ == "__main__":
    cli()
