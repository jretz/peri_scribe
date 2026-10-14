"""Bounded vector-layer reads and GeoPackage writes share neutral layer records.

[Layer streaming reasoning](../../docs/algorithms/spatial-queries-and-measurements.md)
explains the contract and correctness argument.
"""

from __future__ import annotations

import dataclasses
import pathlib
import typing

import geopandas
import structlog


logger = structlog.get_logger()


@dataclasses.dataclass(frozen=True, kw_only=True)
class LayerData:
    """A named geospatial layer ready for GeoPackage output."""

    name: str
    dataframe: geopandas.GeoDataFrame


def read_layer(path: pathlib.Path, layer_name: str) -> geopandas.GeoDataFrame:
    """Read *layer_name* from the GeoPackage at *path*.

    The file is only read, never written.

    Args:
        path: The GeoPackage file to read.
        layer_name: The layer to read.

    Returns:
        The layer's features as a GeoDataFrame.
    """
    return geopandas.read_file(path, layer=layer_name)


def read_layer_chunks(
    path: pathlib.Path,
    layer_name: str | None,
    chunk_size: int,
) -> typing.Iterator[geopandas.GeoDataFrame]:
    """Yield *layer_name* from *path* in chunks of at most *chunk_size* rows.

    Limiting each read lets callers process a layer without loading it all into memory.
    The last chunk may be smaller, and an empty layer yields nothing. With *layer_name*
    set to None, the reader uses the file's default layer.

    A named GeoPackage layer is read by its ``fid`` primary key. Each chunk can then
    start where the previous one ended. Other reads use ``skip_features``, which can
    rescan earlier rows and make the whole read quadratic when the driver cannot seek
    directly.

    Args:
        path: The vector data file to read.
        layer_name: The layer to read, or None for the file's default layer.
        chunk_size: The maximum number of features per chunk.

    Yields:
        Each chunk of the layer's features, in row order.
    """
    if path.suffix.lower() == ".gpkg" and layer_name is not None:
        yield from read_gpkg_layer_chunks(path, layer_name, chunk_size)
        return
    yield from read_skip_layer_chunks(path, layer_name, chunk_size)


def read_skip_layer_chunks(
    path: pathlib.Path,
    layer_name: str | None,
    chunk_size: int,
) -> typing.Iterator[geopandas.GeoDataFrame]:
    """Yield chunks using ``skip_features``, which can rescan earlier rows.

    Args:
        path: The vector data file to read.
        layer_name: The layer to read, or None for the file's default layer.
        chunk_size: The maximum number of features per chunk.

    Yields:
        Each chunk of the layer's features, in row order.
    """
    offset = 0
    while True:
        dataframe = geopandas.read_file(
            path,
            layer=layer_name,
            max_features=chunk_size,
            skip_features=offset,
        )
        if dataframe.empty:
            return
        yield dataframe
        offset += len(dataframe)


def read_gpkg_layer_chunks(
    path: pathlib.Path,
    layer_name: str,
    chunk_size: int,
) -> typing.Iterator[geopandas.GeoDataFrame]:
    """Yield chunks of a GeoPackage layer paginated by its ``fid`` primary key.

    Each indexed read resumes after the previous chunk's last feature id and limits
    the number of returned features. Gaps in the ids therefore cannot enlarge a chunk,
    and earlier rows are not rescanned. The feature ids are used only for pagination;
    each yielded frame has the ordinary positional index used by the other readers.

    Args:
        path: The GeoPackage to read.
        layer_name: The layer whose ``fid`` primary key supports pagination.
        chunk_size: The maximum number of features per chunk.

    Yields:
        Each chunk of the layer's features, in fid order.
    """
    lower: int | None = None
    while True:
        dataframe = geopandas.read_file(
            path,
            layer=layer_name,
            where=None if lower is None else f"fid > {lower}",
            max_features=chunk_size,
            fid_as_index=True,
        )
        if dataframe.empty:
            return
        lower = int(dataframe.index[-1])
        yield dataframe.reset_index(drop=True)


def write_geopackage(
    path: pathlib.Path,
    layers: list[LayerData],
) -> None:
    """Replace a GeoPackage with the supplied layers so obsolete layers cannot remain.

    Args:
        path: The destination GeoPackage, replacing any existing file.
        layers: The named dataframes to write in order.
    """
    if path.exists():
        path.unlink()
        logger.debug("Replaced existing", path=path.name)
    mode = "w"
    for layer_data in layers:
        layer_data.dataframe.to_file(
            path,
            driver="GPKG",
            layer=layer_data.name,
            mode=mode,
        )
        logger.debug(
            "Wrote layer",
            layer=layer_data.name,
            features=len(layer_data.dataframe),
        )
        mode = "a"


def append_geopackage_chunk(
    output: pathlib.Path,
    layer_name: str,
    dataframe: geopandas.GeoDataFrame,
    *,
    replace: bool,
) -> None:
    """Append *dataframe* to the GeoPackage at *output*.

    Args:
        output: The GeoPackage path to write.
        layer_name: The layer to append to.
        dataframe: The chunk's features to write.
        replace: Whether to replace any existing file at *output*.
    """
    if replace:
        output.unlink(missing_ok=True)
    dataframe.to_file(
        output,
        driver="GPKG",
        layer=layer_name,
        mode="w" if replace else "a",
    )
