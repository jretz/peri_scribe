"""Replace package dependencies with controlled test doubles."""

from __future__ import annotations

import pathlib
import sqlite3
import typing

import pandas as pd

import peri_scribe.sources.snapshots


def stub_single_layer(
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
    layer_name: str,
    geometry_type: str,
    dataframe: pd.DataFrame,
) -> None:
    """Point the GeoPackage reader at a single layer.

    Args:
        stub_geo_package: The fixture installing in-memory GeoPackage reads.
        layer_name: The layer's name, matching a configured feed.
        geometry_type: The layer's reported geometry type.
        dataframe: The layer's rows.
    """
    stub_geo_package(
        pd.DataFrame({"name": [layer_name], "geometry_type": [geometry_type]}),
        {layer_name: dataframe},
    )


def make_source_directory_stat_failure(
    *,
    source_directory: pathlib.Path,
    original_stat: typing.Callable[..., object],
) -> typing.Callable[..., object]:
    """Create a callback with controlled dependencies.

    Simulate an unreadable source directory during cache validation.

    Args:
        source_directory: Source directory whose metadata lookup should fail.
        original_stat: Original metadata lookup used for unaffected paths.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def failing_stat(self: pathlib.Path) -> object:
        """Simulate an unreadable source directory during cache validation.

        Returns:
            The original file metadata for other paths.

        Raises:
            OSError: If the path is the source directory.
        """
        if self == source_directory:
            message = "no such directory"
            raise OSError(message)
        return original_stat(self)

    return failing_stat


def make_bucket_directory_stat_failure(
    *,
    bucket_directory: pathlib.Path,
    original_stat: typing.Callable[..., object],
) -> typing.Callable[..., object]:
    """Create a callback with controlled dependencies.

    Simulate an unreadable snapshot bucket during cache validation.

    Args:
        bucket_directory: Snapshot bucket whose metadata lookup should fail.
        original_stat: Original metadata lookup used for unaffected paths.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def failing_stat(self: pathlib.Path) -> object:
        """Simulate an unreadable snapshot bucket during cache validation.

        Returns:
            The original file metadata for other paths.

        Raises:
            OSError: If the path is the snapshot bucket directory.
        """
        if self == bucket_directory:
            message = "no such directory"
            raise OSError(message)
        return original_stat(self)

    return failing_stat


def fail_cache_synchronization(*args: object, **kwargs: object) -> None:
    """Simulate an unusable cache during synchronization.

    Args:
        args: Positional arguments accepted by the substituted dependency.
        kwargs: Keyword arguments accepted by the substituted dependency.

    Raises:
        sqlite3.OperationalError: Always, to exercise direct GeoPackage reading.
    """
    message = "boom"
    raise sqlite3.OperationalError(message)


def make_snapshot_stat_failure(
    *,
    path: pathlib.Path,
    original_stat: typing.Callable[..., object],
) -> typing.Callable[..., object]:
    """Create a callback with controlled dependencies.

    Simulate unavailable file metadata for the requested snapshot.

    Args:
        path: Snapshot or output path selected for the controlled failure.
        original_stat: Original metadata lookup used for unaffected paths.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def failing_stat(self: pathlib.Path) -> object:
        """Simulate unavailable file metadata for the requested snapshot.

        Returns:
            The original file metadata for other paths.

        Raises:
            OSError: If the path is the selected snapshot.
        """
        if self == path:
            message = "no such file"
            raise OSError(message)
        return original_stat(self)

    return failing_stat


def fail_cache_read(*args: object, **kwargs: object) -> object:
    """Simulate a cache read failure after synchronization succeeds.

    Args:
        args: Positional arguments accepted by the substituted dependency.
        kwargs: Keyword arguments accepted by the substituted dependency.

    Raises:
        sqlite3.OperationalError: Always, to exercise direct GeoPackage reading.
    """
    message = "boom"
    raise sqlite3.OperationalError(message)


def make_phantom_snapshot_listing(
    *,
    original: typing.Callable[..., list[peri_scribe.sources.snapshots.SourceFile]],
) -> typing.Callable[..., list[peri_scribe.sources.snapshots.SourceFile]]:
    """Create a callback with controlled dependencies.

    Include a missing snapshot to exercise stale directory-entry handling.

    Args:
        original: Original operation whose results the callback preserves.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def phantom_files(
        directory: pathlib.Path,
    ) -> list[peri_scribe.sources.snapshots.SourceFile]:
        """Include a missing snapshot to exercise stale directory-entry handling.

        Args:
            directory: Directory supplied to the intercepted storage operation.

        Returns:
            The real source files plus a nonexistent snapshot.
        """
        files = original(directory)
        return [
            *files,
            peri_scribe.sources.snapshots.SourceFile(
                serial_number=99,
                last_edit_timestamp=0,
            ),
        ]

    return phantom_files
