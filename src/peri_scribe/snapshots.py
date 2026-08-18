"""Naming and locating GeoPackage snapshots and the directories that hold them."""

from __future__ import annotations

import pathlib
import typing

import peri_scribe.output


SOURCES_DIRECTORY_NAME = "sources"
FIRE_INDEX_FILENAME = "fires.json"


def geopackage_filename(serial_number: int, watermark: str) -> pathlib.Path:
    """Return the filename for a snapshot with *serial_number* and *watermark*.

    Args:
        serial_number: The zero-padded serial number of the snapshot.
        watermark: The watermark observed for the snapshot.

    Returns:
        The snapshot's GeoPackage filename.
    """
    return pathlib.Path(f"{serial_number:06d},{watermark}.gpkg")


def parse_geopackage_filename(filename: pathlib.Path) -> tuple[int, str]:
    """Return the serial number and watermark encoded in *filename*.

    The watermark may itself contain commas, so only the first comma separates the
    serial number from the watermark.

    Args:
        filename: The GeoPackage filename to parse.

    Returns:
        The serial number and watermark encoded in *filename*.
    """
    serial_text, watermark = filename.stem.split(",", 1)
    return int(serial_text), watermark


def next_serial_number(
    existing_filenames: typing.Iterable[pathlib.Path],
    watermark: str,
) -> int:
    """Return the serial number to use for a snapshot named *watermark*.

    The serial number reuses the number of an existing snapshot for the same watermark,
    and otherwise is one greater than the largest serial number among
    *existing_filenames*, so the first snapshot for a source is numbered 0.

    Args:
        existing_filenames: The names of the source's existing GeoPackage files.
        watermark: The watermark to name the new snapshot with.

    Returns:
        The serial number for the new snapshot.
    """
    serial_numbers: list[int] = []
    matching_serial_numbers: list[int] = []
    for filename in existing_filenames:
        try:
            serial_number, existing_watermark = parse_geopackage_filename(filename)
        except ValueError:
            continue
        serial_numbers.append(serial_number)
        if existing_watermark == watermark:
            matching_serial_numbers.append(serial_number)
    if matching_serial_numbers:
        return max(matching_serial_numbers)
    return max(serial_numbers, default=-1) + 1


def existing_geopackage_filenames(directory: pathlib.Path) -> list[pathlib.Path]:
    """Return the names of the GeoPackage files in *directory*.

    Args:
        directory: The directory to list GeoPackage files from.

    Returns:
        The GeoPackage filenames, or an empty list when the directory is missing.
    """
    if not directory.is_dir():
        return []
    return sorted(
        pathlib.Path(path.name)
        for path in directory.iterdir()
        if path.suffix == ".gpkg"
    )


def geo_package_files(directory: pathlib.Path) -> list[pathlib.Path]:
    """Return the GeoPackage files under *directory*, in sorted order.

    The directory tree is searched recursively, so snapshots stored under
    ``sources/{feed}/{serial}.gpkg`` are all found. Sorting makes the order
    deterministic: feed directories by name, then snapshots by serial number.

    Args:
        directory: The directory tree to search.

    Returns:
        The GeoPackage file paths, in sorted order, or an empty list when *directory*
        does not exist.

    Raises:
        SystemExit: If the directory tree cannot be read.
    """
    if not directory.is_dir():
        return []
    try:
        return sorted(directory.rglob("*.gpkg"))
    except OSError as error:
        message = f"Failed to read {directory}: {error}"
        raise SystemExit(message) from error


def snapshot_path_for_watermark(
    directory: pathlib.Path,
    watermark: str,
) -> pathlib.Path | None:
    """Return the path of the existing snapshot named *watermark* in *directory*.

    Args:
        directory: The directory holding the source's GeoPackage files.
        watermark: The watermark to look for.

    Returns:
        The path of the snapshot whose filename encodes *watermark*, or None when
        *directory* has no such snapshot. Malformed filenames are ignored.
    """
    for filename in existing_geopackage_filenames(directory):
        try:
            _, filename_watermark = parse_geopackage_filename(filename)
        except ValueError:
            continue
        if filename_watermark == watermark:
            return directory / filename
    return None


def source_geopackage_path(
    base_dir: pathlib.Path,
    year: int,
    source_name: str,
    serial_number: int,
    watermark: str,
) -> pathlib.Path:
    """Return the path where *source_name*'s snapshot is stored.

    Snapshots are stored under
    ``base_dir/data/{year}/sources/{source_name}/{serial},{watermark}.gpkg``.

    Args:
        base_dir: The base directory that holds the ``data`` directory.
        year: The year the snapshot belongs to.
        source_name: The name of the source the snapshot came from.
        serial_number: The serial number of the snapshot.
        watermark: The watermark that names the snapshot.

    Returns:
        The path to the snapshot's GeoPackage file.
    """
    return (
        sources_directory_path(year_directory_path(base_dir, year))
        / source_name
        / geopackage_filename(serial_number, watermark)
    )


def year_directory_path(base_dir: pathlib.Path, year: int) -> pathlib.Path:
    """Return the directory that holds *year*'s data under *base_dir*.

    Args:
        base_dir: The base directory that holds the ``data`` directory.
        year: The year whose data directory is returned.

    Returns:
        The path to the year's data directory.
    """
    return base_dir / peri_scribe.output.DATA_DIRECTORY / str(year)


def sources_directory_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Return the sources directory inside *year_directory*.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The path to the year's sources directory.
    """
    return year_directory / SOURCES_DIRECTORY_NAME


def fire_index_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Return the path of the fire index for *year_directory*.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The path to the year's fire index file.
    """
    return sources_directory_path(year_directory) / FIRE_INDEX_FILENAME
