"""Share exact native inputs within one finite snapshot collection test."""

from __future__ import annotations

import contextlib
import json
import pathlib
import typing

import arcgis.features
import geopandas
import geopandas.testing
import pyarrow as pa
import pyarrow.ipc
import pyogrio
import pytest
import shapely

import arcgis_access.data
import spatial_data.layers
import tests.formal.helpers.snapshot_collection


if typing.TYPE_CHECKING:
    import collections.abc


def encode(frame: geopandas.GeoDataFrame) -> bytes:
    """Preserve the frame schema and ordered values in an immutable message.

    Args:
        frame: The actual GeoDataFrame supplied by a native boundary.

    Returns:
        A complete GeoArrow stream with index and coordinate reference metadata.
    """
    table = pa.table(frame.to_arrow())
    stream = pa.BufferOutputStream()
    with pa.ipc.new_stream(stream, table.schema) as writer:
        writer.write_table(table)
    return stream.getvalue().to_pybytes()


def decode(content: bytes) -> geopandas.GeoDataFrame:
    """Give each consumer an independent frame built from the same immutable bytes.

    Args:
        content: A GeoArrow stream captured during this test.

    Returns:
        A new frame with the original attributes, geometry, and index.
    """
    with pa.ipc.open_stream(content) as reader:
        return geopandas.GeoDataFrame.from_arrow(reader.read_all())


def qualify(frame: geopandas.GeoDataFrame, content: bytes) -> None:
    """Check lossless reconstruction before admitting an exact native input.

    Args:
        frame: The actual decoded frame or input to a native writer.
        content: Its serialized frame for repeated exact requests.
    """
    restored = decode(content)
    geopandas.testing.assert_geodataframe_equal(
        restored,
        frame,
        check_geom_type=True,
        check_index_type=True,
        check_column_type=True,
    )
    assert restored.index.identical(frame.index)
    assert restored.columns.identical(frame.columns)
    assert restored.geometry.name == frame.geometry.name
    assert shapely.to_wkb(restored.geometry, include_srid=True).tolist() == (
        shapely.to_wkb(frame.geometry, include_srid=True).tolist()
    )


def compatible(frame: geopandas.GeoDataFrame) -> bool:
    """Limit reconstruction to plain frames with no custom metadata.

    Args:
        frame: The frame returned to or supplied by the collector.

    Returns:
        Whether this fixture can share the frame by complete value.
    """
    return type(frame) is geopandas.GeoDataFrame and not frame.attrs


def owns(directory: pathlib.Path, path: pathlib.Path, *, new: bool = False) -> bool:
    """Restrict reuse to the isolated GeoPackages with no SQLite sidecars.

    Args:
        directory: The private root of this snapshot collection test.
        path: The real file requested by the production call.
        new: Whether the request needs a new file rather than an update.

    Returns:
        Whether complete file bytes cover the native input.
    """
    if new and path.exists():
        return False
    return (
        path.is_relative_to(directory)
        and path.suffix == ".gpkg"
        and not path.is_symlink()
        and not any(
            path.with_name(path.name + suffix).exists()
            for suffix in ("-wal", "-shm", "-journal")
        )
    )


@contextlib.contextmanager
def shared(directory: pathlib.Path) -> collections.abc.Generator[None]:
    """Retain real snapshot files and coordinator effects for every checked history.

    Args:
        directory: Private root for all GeoPackages owned by this test.

    Yields:
        A scoped transport that calls each native leaf once for each exact input.
    """
    feed = tests.formal.helpers.snapshot_collection.FEED_NAME
    reads: dict[bytes, bytes] = {}
    writes: dict[bytes, bytes] = {}
    conversions: dict[str, bytes] = {}
    read_layer = spatial_data.layers.read_layer
    write_layer = typing.cast(
        "collections.abc.Callable[..., None]",
        geopandas.GeoDataFrame.to_file,
    )
    convert_features = arcgis_access.data.dataframe_for_layer

    def read(path: pathlib.Path, layer_name: str) -> geopandas.GeoDataFrame:
        """Decode the current actual bytes and keep each returned frame private.

        Args:
            path: The current snapshot or its derived state file.
            layer_name: The requested feed layer.

        Returns:
            A fresh frame from the current file's exact bytes and requested layer.
        """
        if layer_name != feed or not owns(directory, path):
            return read_layer(path, layer_name)
        try:
            source = path.read_bytes()
        except OSError:
            return read_layer(path, layer_name)
        if source in reads:
            return decode(reads[source])
        frame = read_layer(path, layer_name)
        if not compatible(frame):
            return frame
        content = encode(frame)
        qualify(frame, content)
        reads[source] = content
        return frame

    def write(
        frame: geopandas.GeoDataFrame,
        filename: pathlib.Path | str,
        *arguments: object,
        **options: object,
    ) -> None:
        """Write real GeoPackage bytes at the normal staging location.

        Args:
            frame: The current rows computed by production.
            filename: The native writer's requested destination.
            arguments: Other positional arguments forwarded to the native writer.
            options: Driver and layer options requested by production.
        """
        if (
            not isinstance(filename, pathlib.Path)
            or not compatible(frame)
            or not owns(directory, filename, new=True)
            or arguments
            or options != {"driver": "GPKG", "layer": feed, "mode": "w"}
        ):
            write_layer(frame, filename, *arguments, **options)
            return
        content = encode(frame)
        if content in writes:
            filename.write_bytes(writes[content])
            return
        qualify(frame, content)
        write_layer(frame, filename, **options)
        writes[content] = filename.read_bytes()

    def convert(
        feed_name: str,
        layer: arcgis.features.FeatureLayer,
        feature_set: arcgis.features.FeatureSet,
        *,
        geometry_column: str = arcgis_access.data.GEOMETRY_COLUMN_NAME,
    ) -> geopandas.GeoDataFrame:
        """Convert each complete provider reply with its actual layer metadata.

        Args:
            feed_name: The configured feed used by the conversion.
            layer: The queried layer supplying spatial reference metadata.
            feature_set: The native ArcGIS query result.
            geometry_column: The requested output geometry column name.

        Returns:
            An independent frame for the actual native conversion inputs.
        """
        layer_type = tests.formal.helpers.snapshot_collection.QueryInterleaving
        if (
            feed_name != feed
            or type(layer) is not layer_type
            or type(feature_set) is not arcgis.features.FeatureSet
            or not feature_set.features
        ):
            return convert_features(
                feed_name,
                layer,
                feature_set,
                geometry_column=geometry_column,
            )
        key = json.dumps((
            layer.url,
            layer.properties,
            feature_set.to_dict(),
            geometry_column,
        ))
        if key in conversions:
            return decode(conversions[key])
        frame = convert_features(
            feed_name,
            layer,
            feature_set,
            geometry_column=geometry_column,
        )
        if not compatible(frame):
            return frame
        content = encode(frame)
        qualify(frame, content)
        conversions[key] = content
        return frame

    with pytest.MonkeyPatch.context() as patch:
        # Freeze the driver's file metadata clock independently of the source marker.
        fixed_date = "2026-09-01T00:00:00.000Z"
        patch.setenv("OGR_CURRENT_DATE", fixed_date)
        assert pyogrio.get_gdal_config_option("OGR_CURRENT_DATE") == fixed_date
        patch.setattr(spatial_data.layers, "read_layer", read)
        patch.setattr(geopandas.GeoDataFrame, "to_file", write)
        patch.setattr(arcgis_access.data, "dataframe_for_layer", convert)
        yield
