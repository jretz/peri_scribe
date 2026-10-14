"""Retrieve the datasets that explain a fire's surroundings and what it threatens.

These datasets provide national and regional context and sit beside the fire-feed
snapshots under ``data/{year}/sources/``, so a report's inputs are kept together. A
source that produces one GeoPackage uses a file named for the source. Sources with
separate state files keep them in their own directory. The fire-source reader skips
these files when finding fire snapshots.

Each retrieval kind has a different reason to refresh or reuse its stored data:

- ``arcgis`` sources are live FeatureServer layers. Evacuation zones, for example,
  refresh every few minutes. Each fetch replaces the stored GeoPackage only when the
  features change, and keeps only the latest version. If retrieval fails, a warning is
  logged and an existing version is kept so the pipeline can proceed. Without a stored
  version, the failure is raised.
- ``download`` sources are static archives, usually zip files. Their GeoPackages are
  reused once they exist because downloading and converting the same large archive again
  would add work without new data.
- ``cities`` sources check Natural Earth's populated places on every fetch, using HTTP
  validators to avoid downloading unchanged data. A complete, validated SQLite database
  replaces the stored copy. Retrieval failures keep an existing usable copy.

Download sources can supply one archive per state. The generic converter can combine the
state results into one GeoPackage, replace polygons with centroid points, and drop
attributes when only locations are needed. It reads GeoJSON features with ``ijson`` and
other vector data in bounded chunks, so conversion does not require the entire source in
memory. Original archives are removed after conversion. When state results are combined,
their intermediate GeoPackages are removed too.

Buildings use a dedicated converter in ``peri_scribe.sources.buildings``. It reads each
state's archive links from the repository page's "Download links" table when a download
is needed, so changed links are picked up automatically. It streams the archives into a
compact SQLite database without writing the archives or their GeoJSON to disk. The
database keeps quantized centroid records in compressed 0.5° tiles and drops attributes.
It is rebuilt only when missing or incompatible with the expected format.

Design notes:
[External source refresh](../../../docs/algorithms/external-source-refresh.md).
"""

from __future__ import annotations

import pathlib
import typing

import arcgis.features
import arcgis.gis
import structlog

import arcgis_access.data
import peri_scribe.exceptions
import peri_scribe.geo.data
import peri_scribe.logging
import peri_scribe.phases
import peri_scribe.sources.buildings
import peri_scribe.sources.catalog
import peri_scribe.sources.cities
import peri_scribe.sources.digests
import peri_scribe.sources.downloading
import peri_scribe.sources.external_data
import spatial_data.layers


logger = structlog.get_logger()


if typing.TYPE_CHECKING:
    import geopandas


def fetch_external_source(
    source: peri_scribe.sources.external_data.ExternalSource,
    year_directory: pathlib.Path,
) -> tuple[pathlib.Path, ...]:
    """Retrieve *source* into *year_directory*'s sources directory.

    Each source uses the storage and refresh policy suited to its data. Buildings use
    the dedicated compact-database converter. ArcGIS layers replace one GeoPackage when
    features change and keep a stored copy if retrieval fails. Downloads are converted
    to GeoPackages, combining state files when configured. Cities use conditional HTTP
    requests and keep named points with their download metadata in SQLite.

    Args:
        source: The external source to retrieve.
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The paths of the retrieved databases.

    Raises:
        ExternalDataError: If the source cannot be retrieved.
    """
    if source.compact_database:
        return peri_scribe.sources.buildings.fetch_buildings_database(
            source,
            year_directory,
        )
    if source.kind is peri_scribe.sources.external_data.ExternalSourceKind.CITIES:
        return peri_scribe.sources.cities.fetch_cities_database(source, year_directory)
    if source.kind is peri_scribe.sources.external_data.ExternalSourceKind.ARCGIS:
        return (fetch_arcgis_source(source, year_directory),)
    if source.kind is peri_scribe.sources.external_data.ExternalSourceKind.DOWNLOAD:
        return peri_scribe.sources.downloading.download_source(source, year_directory)
    message = f"Unknown external source kind {source.kind!r}"
    raise peri_scribe.exceptions.ExternalDataError(message)


def fetch_arcgis_source(
    source: peri_scribe.sources.external_data.ExternalSource,
    year_directory: pathlib.Path,
) -> pathlib.Path:
    """Query a live ArcGIS layer and keep its latest version.

    The layer is queried in full. When the stored GeoPackage already holds the same
    features, nothing is written and its path is returned. Otherwise the stored
    GeoPackage is replaced with the freshly fetched version, so only the latest version
    of the layer is kept at the source's fixed output path. Empty evacuation responses
    clear the stored features because live zones can all be removed. Other sources
    require at least one feature. When retrieval fails, a warning is logged and the
    stored version is kept so that the caller can proceed; when no version is stored,
    the failure is raised.

    Args:
        source: The ArcGIS-backed external source.
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The path of the stored GeoPackage.

    Raises:
        ExternalDataError: If the layer cannot be retrieved and no current version is
            stored.
    """
    layer_name = source.layer_name or source.name
    output = peri_scribe.sources.external_data.output_path(year_directory, source)
    try:
        geodataframe = query_arcgis_source(source)
        with peri_scribe.logging.log_phase(
            peri_scribe.phases.Phase.NORMALIZE_DATETIMES,
            source=source.name,
        ):
            geodataframe = normalize_arcgis_datetimes(geodataframe)
    except peri_scribe.exceptions.ExternalDataError as error:
        if output.is_file():
            logger.warning(
                "Failed to fetch external source; keeping current data",
                source=source.name,
                error=str(error),
                exc_info=True,
            )
            return output
        raise
    with peri_scribe.logging.log_phase(
        peri_scribe.phases.Phase.COMPARE_FEATURES,
        source=source.name,
    ):
        if output.is_file() and peri_scribe.sources.digests.snapshot_matches(
            geodataframe,
            output,
            layer_name,
            normalize=(
                evacuation_comparison_frame
                if source.name == peri_scribe.sources.catalog.EVACUATIONS_SOURCE.name
                else None
            ),
        ):
            logger.debug("External source unchanged", source=source.name, path=output)
            return output
    temporary = output.with_name(f"{output.stem}.tmp.gpkg")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with peri_scribe.logging.log_phase(
            peri_scribe.phases.Phase.WRITE_SNAPSHOT,
            source=source.name,
        ):
            spatial_data.layers.write_geopackage(
                temporary,
                [
                    spatial_data.layers.LayerData(
                        name=layer_name,
                        dataframe=geodataframe,
                    ),
                ],
            )
            temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    logger.debug(
        "Fetched external source",
        source=source.name,
        path=output,
        features=len(geodataframe),
    )
    return output


def normalize_arcgis_datetimes(
    dataframe: geopandas.GeoDataFrame,
) -> geopandas.GeoDataFrame:
    """Keep millisecond source dates stable across GeoPackage storage.

    ArcGIS dates have millisecond precision. The client can introduce sub-millisecond
    floating-point noise when converting them to datetimes, and GeoPackage storage drops
    that precision. Comparison and storage must use the same rounded values so an
    identical response cannot repeatedly count as a change.

    Args:
        dataframe: The query result, including the client's converted date columns.

    Returns:
        A copy with date columns rounded to their source precision.
    """
    return typing.cast(
        "geopandas.GeoDataFrame",
        dataframe.assign(**{
            column: dataframe[column].dt.round("ms")
            for column in dataframe.select_dtypes(include=["datetime", "datetimetz"])
        }),
    )


def evacuation_comparison_frame(
    dataframe: geopandas.GeoDataFrame,
) -> geopandas.GeoDataFrame:
    """Compare evacuation audit dates at the service's reliable precision.

    The evacuation service alternates between fractional and whole-second values for
    CreationDate and EditDate on otherwise identical features. Those audit fields must
    compare at whole-second precision to avoid false updates. Geometry, other fields,
    and the dates written to storage retain their precision.

    Args:
        dataframe: The fetched or stored evacuation features.

    Returns:
        A comparison-only copy with audit dates truncated to whole seconds.
    """
    date_columns = dataframe.select_dtypes(include=["datetime", "datetimetz"])
    return typing.cast(
        "geopandas.GeoDataFrame",
        dataframe.assign(**{
            column: dataframe[column].dt.floor("s")
            for column in ("CreationDate", "EditDate")
            if column in date_columns
        }),
    )


def query_arcgis_source(
    source: peri_scribe.sources.external_data.ExternalSource,
) -> geopandas.GeoDataFrame:
    """Query *source*'s ArcGIS layer and return its features as a GeoDataFrame.

    Args:
        source: The ArcGIS-backed external source.

    Returns:
        The layer's features in WGS84.

    Raises:
        ExternalDataError: If the layer cannot be fetched or a non-evacuation source
            returns no features.
    """
    try:
        gis = arcgis.gis.GIS()
        layer = arcgis.features.FeatureLayer(source.url, gis)
        feature_set = peri_scribe.geo.data.query_with_retry(
            source.name,
            layer,
            parameters=arcgis_access.data.wgs84_query_parameters(
                source.where or "1=1",
            ),
        )
    except Exception as error:
        message = f"Failed to fetch external source {source.name}: {error}"
        raise peri_scribe.exceptions.ExternalDataError(message) from error
    if (
        not feature_set.features
        and source.name != peri_scribe.sources.catalog.EVACUATIONS_SOURCE.name
    ):
        message = f"External source {source.name} returned no features"
        raise peri_scribe.exceptions.ExternalDataError(message)
    with peri_scribe.logging.log_phase(
        peri_scribe.phases.Phase.CONVERT_FEATURES,
        source=source.name,
    ):
        return arcgis_access.data.geo_data_frame_from_feature_set(feature_set)
