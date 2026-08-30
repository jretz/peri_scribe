"""Converting geodata files into GeoPackage layers."""

from __future__ import annotations

import pathlib
import typing

import geopandas
import ijson
import shapely
import structlog

import peri_scribe.exceptions
import peri_scribe.geo.reading
import peri_scribe.models
import peri_scribe.sources.downloading


logger = structlog.get_logger()


CONVERSION_CHUNK_SIZE = 100_000


def geodata_chunks(
    geodata_path: pathlib.Path,
    chunk_size: int,
) -> typing.Iterator[geopandas.GeoDataFrame]:
    """Yield the vector data at *geodata_path* as bounded GeoDataFrames.

    A GeoJSON file is parsed with ``ijson`` so only one feature is in memory at a time;
    any other vector data (a shapefile or file geodatabase) is read in bounded chunks.
    Every yielded frame holds at most *chunk_size* features.

    Args:
        geodata_path: The vector data file or directory to read.
        chunk_size: The maximum number of features per chunk.

    Yields:
        Each chunk of the file's features, in row order.
    """
    if geodata_path.suffix.lower() in {".geojson", ".json"}:
        yield from geojson_feature_chunks(geodata_path, chunk_size)
    else:
        yield from peri_scribe.geo.reading.read_layer_chunks(
            geodata_path,
            None,
            chunk_size,
        )


def geojson_feature_chunks(
    geodata_path: pathlib.Path,
    chunk_size: int,
) -> typing.Iterator[geopandas.GeoDataFrame]:
    """Yield the features of the GeoJSON at *geodata_path* as bounded GeoDataFrames.

    The file is parsed with ``ijson`` so only one feature is in memory at a time; each
    yielded frame holds at most *chunk_size* features. A feature without a geometry
    keeps None as its geometry. GeoJSON has no coordinate reference system of its own,
    so every frame is WGS84, matching how GeoPandas would read the file.

    Args:
        geodata_path: The GeoJSON FeatureCollection to read.
        chunk_size: The maximum number of features per chunk.

    Yields:
        Each chunk of the file's features, in row order.
    """
    with geodata_path.open("rb") as file:
        geometries: list[shapely.Geometry | None] = []
        attributes: list[dict[str, object]] = []
        for feature in ijson.items(file, "features.item"):
            geometry = feature.get("geometry")
            geometries.append(
                None if geometry is None else shapely.geometry.shape(geometry),
            )
            properties = feature.get("properties")
            attributes.append(
                properties if isinstance(properties, dict) else {},
            )
            if len(geometries) >= chunk_size:
                yield geojson_chunk_dataframe(geometries, attributes)
                geometries = []
                attributes = []
        if geometries:
            yield geojson_chunk_dataframe(geometries, attributes)


def geojson_chunk_dataframe(
    geometries: list[shapely.Geometry | None],
    attributes: list[dict[str, object]],
) -> geopandas.GeoDataFrame:
    """Return a WGS84 GeoDataFrame for one chunk of GeoJSON features.

    The frame's columns are the sorted union of the features' property keys, so the
    schema is identical for every chunk of a file whose features share their keys.

    Args:
        geometries: One shapely geometry per feature, None where a feature has none.
        attributes: One properties dict per feature.

    Returns:
        The chunk's features as a WGS84 GeoDataFrame.
    """
    columns = sorted({column for row in attributes for column in row})
    rows = [{column: row.get(column) for column in columns} for row in attributes]
    return geopandas.GeoDataFrame(
        rows,
        geometry=geometries,
        crs=peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID,
    )


def convert_to_geopackage(
    geodata_path: pathlib.Path,
    output: pathlib.Path,
    layer_name: str,
    *,
    centroids: bool,
    keep_attributes: bool,
) -> None:
    """Convert *geodata_path* into a GeoPackage at *output*.

    The source is read and written in bounded chunks, so a source of any size is
    converted without loading the whole file into memory. When *centroids* is true each
    feature's geometry is replaced by its centroid point. When *keep_attributes* is
    false every attribute column is dropped, leaving only the geometry.

    Args:
        geodata_path: The vector data file to convert.
        output: The GeoPackage path to write.
        layer_name: The GeoPackage layer name.
        centroids: Replace each feature's geometry with its centroid.
        keep_attributes: Keep the source's attribute columns.

    Raises:
        ExternalDataError: If the vector data cannot be read.
    """
    wrote_any = False
    feature_count = 0
    try:
        for chunk in geodata_chunks(geodata_path, CONVERSION_CHUNK_SIZE):
            dataframe = converted_chunk(
                chunk,
                centroids=centroids,
                keep_attributes=keep_attributes,
            )
            peri_scribe.sources.downloading.append_geopackage_chunk(
                output,
                layer_name,
                dataframe,
                replace=not wrote_any,
            )
            wrote_any = True
            feature_count += len(dataframe)
    except Exception as error:
        message = f"Failed to read {geodata_path}: {error}"
        raise peri_scribe.exceptions.ExternalDataError(message) from error
    if not wrote_any:
        peri_scribe.sources.downloading.append_geopackage_chunk(
            output,
            layer_name,
            geopandas.GeoDataFrame(
                geometry=[],
                crs=peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID,
            ),
            replace=True,
        )
    logger.debug(
        "Converted external source to GeoPackage",
        path=output,
        features=feature_count,
    )


def converted_chunk(
    chunk: geopandas.GeoDataFrame,
    *,
    centroids: bool,
    keep_attributes: bool,
) -> geopandas.GeoDataFrame:
    """Return *chunk* with the source's conversion options applied.

    Args:
        chunk: One chunk of the source's features.
        centroids: Replace each feature's geometry with its centroid.
        keep_attributes: Keep the source's attribute columns.

    Returns:
        The chunk's features, reduced to centroids and to geometry alone when
        attributes are not kept.
    """
    dataframe = centroid_dataframe(chunk) if centroids else chunk
    if not keep_attributes:
        dataframe = dataframe[[dataframe.geometry.name]]
    return dataframe


def centroid_dataframe(dataframe: geopandas.GeoDataFrame) -> geopandas.GeoDataFrame:
    """Return *dataframe* with each geometry replaced by its centroid.

    A geographic CRS is projected before the centroid is computed, so the result is
    correct and the geometry is returned in the original CRS.

    Args:
        dataframe: The GeoDataFrame whose geometries are replaced.

    Returns:
        The GeoDataFrame with centroid point geometries.
    """
    crs = dataframe.crs
    if crs is not None and crs.is_geographic:
        projected = dataframe.to_crs(3857)
        projected.geometry = projected.geometry.centroid
        return projected.to_crs(crs)
    dataframe.geometry = dataframe.geometry.centroid
    return dataframe
