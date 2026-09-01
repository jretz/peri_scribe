"""Naming and locating GeoPackage snapshots and the directories that hold them."""

from __future__ import annotations

import dataclasses
import pathlib
import typing

import peri_scribe.output


SOURCES_DIRECTORY_NAME = "sources"
VALIDATION_DIRECTORY_NAME = "validation"
FIRE_INDEX_FILENAME = "fires.json"

# The name of each feed's record-cache database, stored as a single file inside the
# feed's snapshot directory.
RECORD_CACHE_FILENAME = "record_cache.db"

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

        Examples:
            >>> SourceFile(
            ...     serial_number=1234,
            ...     last_edit_timestamp=1700000000000,
            ... ).relative_path
            PosixPath('001___/001234,lastEdit=1700000000000.gpkg')
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

        Examples:
            >>> SourceFile.from_path(pathlib.Path("000012,lastEdit=1700000000000.gpkg"))
            SourceFile(serial_number=12, last_edit_timestamp=1700000000000)
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
    *,
    reuse_same_timestamp: bool = True,
) -> int:
    """Return the serial number to use for a snapshot named *last_edit_timestamp*.

    The serial number reuses the number of an existing snapshot for the same timestamp,
    and otherwise is one greater than the largest serial number among *existing*, so the
    first snapshot for a source is numbered 0.

    A full fetch writes a new snapshot even when the observed timestamp is unchanged,
    so its caller passes *reuse_same_timestamp* as false to keep the new snapshot from
    overwriting the existing snapshot for the same timestamp.

    Args:
        existing: The source's existing source files.
        last_edit_timestamp: The last-edit timestamp to name the new snapshot with.
        reuse_same_timestamp: Whether to reuse the serial number of an existing
            snapshot for the same timestamp.

    Returns:
        The serial number for the new snapshot.

    Examples:
        >>> next_serial_number([], 1700000000000)
        0

        >>> next_serial_number([SourceFile(serial_number=2, last_edit_timestamp=1)], 2)
        3
    """
    source_files = list(existing)
    if reuse_same_timestamp:
        matching_serial_numbers = [
            source_file.serial_number
            for source_file in source_files
            if source_file.last_edit_timestamp == last_edit_timestamp
        ]
        if matching_serial_numbers:
            return max(matching_serial_numbers)
    serial_numbers = [source_file.serial_number for source_file in source_files]
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
    """Return the fire-source GeoPackage files under *directory*, in sorted order.

    The directory tree is searched recursively, so snapshots stored under
    ``sources/{feed}/{serial}.gpkg`` are all found. Files whose names do not encode a
    snapshot serial number and last-edit timestamp (the retrieved external datasets, the
    computed California border, and each feed's maintained current-state file) are not
    fire-source snapshots and are skipped. Sorting makes the order deterministic: feed
    directories by name, then snapshots by serial number.

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
        paths = sorted(directory.rglob("*.gpkg"))
    except OSError as error:
        message = f"Failed to read {directory}: {error}"
        raise SystemExit(message) from error
    return [path for path in paths if is_snapshot_filename(path.name)]


def is_snapshot_filename(filename: str) -> bool:
    """Return whether *filename* encodes a snapshot serial and timestamp.

    Args:
        filename: The filename to inspect.

    Returns:
        True when the filename parses as a fire-source snapshot name.

    Examples:
        >>> is_snapshot_filename("000012,lastEdit=1700000000000.gpkg")
        True

        >>> is_snapshot_filename("state-12.gpkg")
        False
    """
    try:
        SourceFile.from_path(pathlib.Path(filename))
    except ValueError:
        return False
    return True


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


def current_state_path(
    source_directory: pathlib.Path,
    serial_number: int,
) -> pathlib.Path:
    """Return the path of the current-state file covering snapshot *serial_number*.

    The current-state file is a single file inside the feed's snapshot directory, named
    for the serial number of the newest snapshot the state covers, so a state file's
    freshness can be checked without opening it.

    Args:
        source_directory: The feed's snapshot directory.
        serial_number: The serial number of the newest snapshot the state covers.

    Returns:
        The path of the state file.
    """
    return source_directory / f"state-{serial_number}.gpkg"


def current_state_file_paths(
    source_directory: pathlib.Path,
) -> list[tuple[int, pathlib.Path]]:
    """Return the feed's current-state files, sorted by covered serial number.

    Args:
        source_directory: The feed's snapshot directory.

    Returns:
        The (covered serial number, path) pairs in covered-serial order, or an empty
        list when the feed has no state files. Malformed filenames are ignored.
    """
    if not source_directory.is_dir():
        return []
    prefix = "state-"
    state_files: list[tuple[int, pathlib.Path]] = []
    for path in source_directory.glob(f"{prefix}*.gpkg"):
        serial_text = path.stem[len(prefix) :]
        try:
            serial_number = int(serial_text)
        except ValueError:
            continue
        state_files.append((serial_number, path))
    return sorted(state_files)


def record_cache_database_path(
    source_directory: pathlib.Path,
) -> pathlib.Path:
    """Return the record cache database path for *source_directory*'s feed.

    One SQLite database holds every snapshot's parsed records for a feed, so the cache
    is a single file stored inside the feed's snapshot directory:
    ``sources/{feed}/record_cache.db``.

    Args:
        source_directory: The feed's snapshot directory, under ``sources``.

    Returns:
        The path of the feed's record cache database.
    """
    return source_directory / RECORD_CACHE_FILENAME


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

    Examples:
        >>> source_name_from_snapshot_path(
        ...     pathlib.Path(
        ...         "data/2025/sources/incidents/000___/000012,lastEdit=1.gpkg",
        ...     ),
        ... )
        'incidents'
    """
    return path.parent.parent.name


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
    return base_dir / peri_scribe.output.DATA_DIRECTORY / str(year)


def year_for_year_directory(year_directory: pathlib.Path) -> int:
    """Return the year number that *year_directory* holds data for.

    Args:
        year_directory: The year directory, named for the year it holds data for.

    Returns:
        The year number.
    """
    return int(year_directory.name)


def base_directory_for_year_directory(
    year_directory: pathlib.Path,
) -> pathlib.Path:
    """Return the base directory that *year_directory* sits under.

    A year directory is stored as ``base_directory/data/{year}``, so the base
    directory is two levels above it.

    Args:
        year_directory: The year directory.

    Returns:
        The base directory.

    Examples:
        >>> base_directory_for_year_directory(pathlib.Path("project/data/2025"))
        PosixPath('project')
    """
    return year_directory.parent.parent


def sources_directory_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Return the sources directory inside *year_directory*.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The path to the year's sources directory.

    Examples:
        >>> sources_directory_path(pathlib.Path("data/2025"))
        PosixPath('data/2025/sources')
    """
    return year_directory / SOURCES_DIRECTORY_NAME


def validation_directory_path(
    year_directory: pathlib.Path,
) -> pathlib.Path:
    """Return the validation directory inside *year_directory*.

    The directory holds one full snapshot per source, fetched fresh for validation
    against the incremental snapshots in the sources directory.

    Args:
        year_directory: The year directory that holds the ``validation`` directory.

    Returns:
        The path to the year's validation directory.

    Examples:
        >>> validation_directory_path(pathlib.Path("data/2025"))
        PosixPath('data/2025/validation')
    """
    return year_directory / VALIDATION_DIRECTORY_NAME


def validation_geopackage_path(
    year_directory: pathlib.Path,
    source_name: str,
) -> pathlib.Path:
    """Return the path where *source_name*'s complete snapshot is stored.

    Args:
        year_directory: The year directory that holds the ``validation`` directory.
        source_name: The name of the source the snapshot came from.

    Returns:
        The path to the source's complete GeoPackage file.
    """
    return validation_directory_path(year_directory) / f"{source_name}.gpkg"


def fire_index_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Return the path of the fire index for *year_directory*.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The path to the year's fire index file.

    Examples:
        >>> fire_index_path(pathlib.Path("data/2025"))
        PosixPath('data/2025/sources/fires.json')
    """
    return sources_directory_path(year_directory) / FIRE_INDEX_FILENAME
