"""Naming and locating GeoPackage snapshots and the directories that hold them."""

from __future__ import annotations

import dataclasses
import pathlib
import typing

import peri_scribe.output


SOURCES_DIRECTORY_NAME = "sources"
FIRE_INDEX_FILENAME = "fires.json"

# The prefix that turns a source layer's ``editingInfo.lastEditDate`` value into the
# timestamp stored in a snapshot filename.
LAST_EDIT_TIMESTAMP_PREFIX = "lastEdit="


@dataclasses.dataclass(frozen=True, kw_only=True)
class SourceFile:
    """One source snapshot, identified by serial number and last-edit timestamp.

    A source file is stored under its source directory in a bucket subdirectory named
    for the serial number's thousands, so a directory never grows past roughly a
    thousand entries.
    """

    serial_number: int
    # The source layer's ``lastEditDate`` value, in epoch milliseconds.
    last_edit_timestamp: int

    @property
    def relative_path(self) -> pathlib.Path:
        """Return the file's path relative to its source directory.

        Returns:
            The bucket subdirectory and filename, relative to the source directory.
        """
        bucket = f"{(self.serial_number // 1000):03d}___"
        filename = (
            f"{self.serial_number:06d},"
            f"{LAST_EDIT_TIMESTAMP_PREFIX}{self.last_edit_timestamp}.gpkg"
        )
        return pathlib.Path(bucket) / filename

    @classmethod
    def from_path(cls, path: pathlib.Path) -> SourceFile:
        """Return the source file described by *path*.

        Only the path's filename is parsed, so the directory components are ignored.

        Args:
            path: The GeoPackage path to parse.

        Returns:
            The source file whose serial number and last-edit timestamp are encoded in
            the filename.

        Raises:
            ValueError: If the filename does not encode a serial number and timestamp.
        """
        serial_text, separator, timestamp_text = path.stem.partition(",")
        if not separator or not timestamp_text.startswith(LAST_EDIT_TIMESTAMP_PREFIX):
            message = f"Unrecognized snapshot filename {path.name!r}"
            raise ValueError(message)
        return cls(
            serial_number=int(serial_text),
            last_edit_timestamp=int(timestamp_text[len(LAST_EDIT_TIMESTAMP_PREFIX) :]),
        )


def next_serial_number(
    existing: typing.Iterable[SourceFile],
    last_edit_timestamp: int,
) -> int:
    """Return the serial number to use for a snapshot named *last_edit_timestamp*.

    The serial number reuses the number of an existing snapshot for the same timestamp,
    and otherwise is one greater than the largest serial number among *existing*, so the
    first snapshot for a source is numbered 0.

    Args:
        existing: The source's existing source files.
        last_edit_timestamp: The last-edit timestamp to name the new snapshot with.

    Returns:
        The serial number for the new snapshot.
    """
    serial_numbers = [source_file.serial_number for source_file in existing]
    matching_serial_numbers = [
        source_file.serial_number
        for source_file in existing
        if source_file.last_edit_timestamp == last_edit_timestamp
    ]
    if matching_serial_numbers:
        return max(matching_serial_numbers)
    return max(serial_numbers, default=-1) + 1


def existing_source_files(directory: pathlib.Path) -> list[SourceFile]:
    """Return the source files in *directory*, sorted by serial number.

    The directory tree is searched recursively, so snapshots stored under
    ``sources/{feed}/{serial//1000:03d}___/{serial}.gpkg`` are all found.

    Args:
        directory: The directory to list source files from.

    Returns:
        The source files, in serial order, or an empty list when the directory is
        missing. Malformed filenames are ignored.
    """
    if not directory.is_dir():
        return []
    source_files: list[SourceFile] = []
    for path in directory.rglob("*.gpkg"):
        try:
            source_files.append(SourceFile.from_path(path))
        except ValueError:
            continue
    return sorted(source_files, key=lambda source_file: source_file.serial_number)


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


def snapshot_path_for_last_edit_timestamp(
    directory: pathlib.Path,
    last_edit_timestamp: int,
) -> pathlib.Path | None:
    """Return the path of the existing snapshot for *last_edit_timestamp*.

    Args:
        directory: The directory holding the source's GeoPackage files.
        last_edit_timestamp: The last-edit timestamp to look for.

    Returns:
        The path of the snapshot whose filename encodes *last_edit_timestamp*, or None
        when *directory* has no such snapshot.
    """
    for source_file in existing_source_files(directory):
        if source_file.last_edit_timestamp == last_edit_timestamp:
            return directory / source_file.relative_path
    return None


def source_directory_path(
    base_dir: pathlib.Path,
    year: int,
    source_name: str,
) -> pathlib.Path:
    """Return the directory that holds *source_name*'s snapshots.

    Args:
        base_dir: The base directory that holds the ``data`` directory.
        year: The year the snapshots belong to.
        source_name: The name of the source the snapshots came from.

    Returns:
        The path to the source's directory.
    """
    return sources_directory_path(year_directory_path(base_dir, year)) / source_name


def source_geopackage_path(
    base_dir: pathlib.Path,
    year: int,
    source_name: str,
    source_file: SourceFile,
) -> pathlib.Path:
    """Return the path where *source_name*'s snapshot is stored.

    Snapshots are stored under
    ``base_dir/data/{year}/sources/{source_name}/{serial//1000:03d}___/{serial},lastEdit={timestamp}.gpkg``.

    Args:
        base_dir: The base directory that holds the ``data`` directory.
        year: The year the snapshot belongs to.
        source_name: The name of the source the snapshot came from.
        source_file: The snapshot to locate.

    Returns:
        The path to the snapshot's GeoPackage file.
    """
    return (
        source_directory_path(base_dir, year, source_name) / source_file.relative_path
    )


def source_name_from_snapshot_path(path: pathlib.Path) -> str:
    """Return the source directory name encoded in a snapshot *path*.

    The snapshot's filename sits one level below its source directory, under a bucket
    subdirectory, so the source name is the directory two levels above the file.

    Args:
        path: A GeoPackage snapshot path.

    Returns:
        The source (feed) directory name.
    """
    return path.parent.parent.name


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
