"""Shared filesystem locations keep readers independent of output generation."""

import pathlib


DATA_DIRECTORY = pathlib.Path("data")


def year_directory_path(base_dir: pathlib.Path, year: int) -> pathlib.Path:
    """Return the directory that holds *year*'s data under *base_dir*.

    Args:
        base_dir: The base directory that holds the ``data`` directory.
        year: The year whose data directory is returned.

    Returns:
        The path to the year's data directory.

    Examples:
        >>> year_directory_path(pathlib.Path("project"), 2025)
        PosixPath('project/data/2025')
    """
    return base_dir / DATA_DIRECTORY / str(year)


def year_for_year_directory(year_directory: pathlib.Path) -> int:
    """Return the year number that *year_directory* holds data for.

    Args:
        year_directory: The year directory, named for the year it holds data for.

    Returns:
        The year number.
    """
    return int(year_directory.name)


MAPS_DIRECTORY_NAME = "maps"


def kmz_filename(year: int) -> str:
    """Return the KMZ filename for *year*.

    Args:
        year: The year the output describes.

    Returns:
        The filename.

    Examples:
        >>> kmz_filename(2025)
        'PeriScribe Fires 2025.kmz'
    """
    return f"PeriScribe Fires {year}.kmz"


def kmz_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Return the path of the KMZ output for *year_directory*.

    Args:
        year_directory: The year directory that holds the ``maps`` directory.

    Returns:
        The output KMZ path.

    Examples:
        >>> kmz_path(pathlib.Path("data/2025"))
        PosixPath('data/2025/maps/PeriScribe Fires 2025.kmz')
    """
    year = year_for_year_directory(year_directory)
    return year_directory / MAPS_DIRECTORY_NAME / kmz_filename(year)


REPORTS_DIRECTORY_NAME = "reports"


def markdown_report_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Return the Markdown report path for *year_directory*.

    Args:
        year_directory: The year directory, whose name is the year.

    Returns:
        The report's output path.

    Examples:
        >>> markdown_report_path(pathlib.Path("data/2026"))
        PosixPath('data/2026/reports/PeriScribe Fires 2026.md')
    """
    year = year_for_year_directory(year_directory)
    return year_directory / REPORTS_DIRECTORY_NAME / f"PeriScribe Fires {year}.md"
