"""Shared command paths keep monitoring and pipeline arguments consistent."""

import datetime
import pathlib
import typing

import peri_scribe.paths


if typing.TYPE_CHECKING:
    import click


def default_year_directory() -> pathlib.Path:
    """Return the current year's data directory under the working directory.

    Returns:
        The path to ``data/<current year>`` under the current working directory.
    """
    return peri_scribe.paths.year_directory_path(
        pathlib.Path.cwd(),
        datetime.date.today().year,
    )


def command_year_directory(
    _context: click.Context,
    _parameter: click.Parameter,
    value: pathlib.Path | None,
) -> pathlib.Path:
    """Resolve the command's directory before its first log entry.

    Args:
        _context: The command's Click context.
        _parameter: The year-directory argument being parsed.
        value: The explicitly supplied directory, or None to use the current year.

    Returns:
        The directory shared by pipeline data and command logs.
    """
    return value if value is not None else default_year_directory()


def year_directory_default_help() -> str:
    """Return the help sentence naming the default year directory.

    The default moves forward each new year, so the sentence names the current year.

    Returns:
        The sentence naming the default year directory.
    """
    return (
        f"YEAR_DIRECTORY defaults to "
        f"{peri_scribe.paths.DATA_DIRECTORY}/"
        f"{datetime.date.today().year}."
    )
