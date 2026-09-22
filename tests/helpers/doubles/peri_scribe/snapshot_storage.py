"""Replace snapshot storage dependencies with controlled test doubles."""

from __future__ import annotations

import pathlib
import typing

import peri_scribe.sources.feed_types
import peri_scribe.sources.snapshots


if typing.TYPE_CHECKING:
    import geopandas

    import spatial_data.layers


class GeoPackageStore:
    """In-memory stand-in for the GeoPackage files the fetch command writes.

    Written layers are keyed by (path, layer name) so tests can assert what was written
    and serve it back to incremental fetches without touching the filesystem.
    """

    def __init__(self) -> None:
        """Initialize an empty GeoPackage store for isolated file tests."""
        self.layers: dict[tuple[pathlib.Path, str], geopandas.GeoDataFrame] = {}

    def write(
        self,
        path: pathlib.Path,
        layers: list[spatial_data.layers.LayerData],
    ) -> None:
        """Record *layers* as the contents of the GeoPackage at *path*.

        Args:
            path: Path supplied to the intercepted file operation.
            layers: Named layers to store in the GeoPackage.
        """
        for layer_data in layers:
            self.layers[path, layer_data.name] = layer_data.dataframe

    def source_files(
        self,
        directory: pathlib.Path,
    ) -> list[peri_scribe.sources.snapshots.SourceFile]:
        """Return the source files stored under *directory*, in serial order.

        Files that do not encode a snapshot serial number and timestamp (the
        current-state files) are skipped, mirroring ``existing_source_files``.

        Args:
            directory: Directory supplied to the intercepted storage operation.

        Returns:
            The stored source files, sorted by serial number.
        """
        source_files: list[peri_scribe.sources.snapshots.SourceFile] = []
        for path, _layer_name in self.layers:
            if path.suffix != ".gpkg" or not path.is_relative_to(directory):
                continue
            try:
                source_files.append(
                    peri_scribe.sources.snapshots.SourceFile.from_path(path),
                )
            except ValueError:
                continue
        return sorted(source_files, key=lambda source_file: source_file.serial_number)

    def read_layer(
        self,
        path: pathlib.Path,
        feed: peri_scribe.sources.feed_types.Feed,
    ) -> geopandas.GeoDataFrame:
        """Return the layer for *feed* stored in the GeoPackage at *path*.

        Args:
            path: Path supplied to the intercepted file operation.
            feed: Feed configuration used to interpret the source observations.

        Returns:
            The feed's layer dataframe.
        """
        return self.layers[path, feed.name]

    def layer(self, path: pathlib.Path, layer_name: str) -> geopandas.GeoDataFrame:
        """Return the layer named *layer_name* stored at *path*.

        Args:
            path: Path supplied to the intercepted file operation.
            layer_name: Name of the layer to select within the GeoPackage.

        Returns:
            The layer dataframe.
        """
        return self.layers[path, layer_name]

    def has(self, path: pathlib.Path) -> bool:
        """Return whether any layer has been stored at *path*.

        Args:
            path: Path supplied to the intercepted file operation.

        Returns:
            True when a layer has been stored at *path*.
        """
        return any(stored_path == path for stored_path, _layer_name in self.layers)
