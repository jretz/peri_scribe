"""Retrieving external (non-fire) datasets into a year's sources directory.

The fire feeds describe the fires themselves; the datasets here describe what those
fires threaten or what the conditions are around them. A source that produces a single
GeoPackage stores it directly under ``data/{year}/sources/``, named for the source; a
per-state source stores one GeoPackage per state under its own directory. Either way the
datasets sit in the same tree as the fire-feed snapshots, so everything a report needs
is in one place. The datasets cover the whole United States, not just California.

Two retrieval kinds are supported:

- ``arcgis``: an ArcGIS FeatureServer layer is queried and stored as a GeoPackage
  holding the layer's latest version. The layers are live (the evacuation zones refresh
  every few minutes), so each fetch replaces the stored GeoPackage when the layer's
  features changed; only the latest version is kept. A fetch that cannot reach the layer
  logs a warning and keeps the stored version so the rest of the pipeline can proceed.
- ``download``: a file (typically a zip archive) is downloaded, extracted, and converted
  to a GeoPackage holding the same data. These datasets are static, so a source whose
  GeoPackage already exists is left alone.

A download source covers the whole country as one archive per state (the building
footprints). A combined source concatenates the per-state results into a single
GeoPackage and keeps no other files; a source may reduce each footprint polygon to a
centroid point and keep no attributes, since only the buildings' locations are wanted.
Any download is converted in bounded chunks — a GeoJSON archive is parsed one feature at
a time with ``ijson`` and any other vector data is read in chunks — so a source of any
size is converted without loading the whole file into memory. The original archives are
not kept once converted. The building footprints' per-state archive links are not
constructed from a URL pattern; they are read from the "Download links" table on the
dataset's repository page whenever the archives are downloaded, so a change in the link
scheme is picked up automatically.

The buildings source stores its data as the compact buildings SQLite database instead of
a GeoPackage: a dedicated converter (``peri_scribe.sources.buildings``) streams every
state's archive directly into the database, so the archives and their GeoJSON are never
written to disk, and the stored file holds only quantized centroid records in compressed
0.5° tiles with no attributes. The database is regenerated only when it is missing or no
longer matches the expected format.

The fire-source reader skips these files, so their GeoPackages are never mistaken for
fire snapshots.
"""

from __future__ import annotations

import pathlib
import typing

import arcgis.features
import arcgis.gis
import structlog
import us

import peri_scribe.exceptions
import peri_scribe.geo.data
import peri_scribe.logging
import peri_scribe.models
import peri_scribe.output
import peri_scribe.phases
import peri_scribe.sources.archives
import peri_scribe.sources.buildings
import peri_scribe.sources.digests
import peri_scribe.sources.downloading
import peri_scribe.sources.external_data


logger = structlog.get_logger()


if typing.TYPE_CHECKING:
    import geopandas


BUILDINGS_STATES = tuple(state.name for state in (*us.states.STATES, us.states.DC))


def buildings_state_urls() -> dict[str, str]:
    """Return the state-to-archive-URL mapping from the repo's page.

    The per-state archive links live in the "Download links" table of the repository
    page named by ``BUILDINGS_SOURCE.url``; the page is loaded only when the archives
    are about to be downloaded, so a change in the link scheme is picked up
    automatically.

    Returns:
        The mapping from state name to archive URL.

    Raises:
        ExternalDataError: If the page cannot be downloaded, holds no download links, or
            is missing a link for one of the states.
    """
    html_text = peri_scribe.sources.archives.fetch_page_text(BUILDINGS_SOURCE.url)
    links = peri_scribe.sources.archives.download_links(html_text)
    if not links:
        message = f"No download links found on {BUILDINGS_SOURCE.url}"
        raise peri_scribe.exceptions.ExternalDataError(message)
    missing = [state for state in BUILDINGS_STATES if state not in links]
    if missing:
        message = f"No download link for {', '.join(missing)} on {BUILDINGS_SOURCE.url}"
        raise peri_scribe.exceptions.ExternalDataError(message)
    return links


BUILDINGS_SOURCE = peri_scribe.sources.external_data.ExternalSource(
    name="buildings",
    kind=peri_scribe.sources.external_data.ExternalSourceKind.DOWNLOAD,
    url="https://github.com/microsoft/USBuildingFootprints",
    states=BUILDINGS_STATES,
    state_urls=buildings_state_urls,
    compact_database=True,
)

EVACUATIONS_SOURCE = peri_scribe.sources.external_data.ExternalSource(
    name="evacuations",
    kind=peri_scribe.sources.external_data.ExternalSourceKind.ARCGIS,
    url=(
        "https://services.arcgis.com/BLN4oKB0N1YSgvY8/arcgis/rest/services/"
        "CA_EVACUATIONS_CalOESHosted_view/FeatureServer/0"
    ),
    layer_name="evacuations",
)

MAJOR_CITIES_SOURCE = peri_scribe.sources.external_data.ExternalSource(
    name="major_cities",
    kind=peri_scribe.sources.external_data.ExternalSourceKind.ARCGIS,
    url=(
        "https://services.arcgis.com/P3ePLMYs2RVChkJx/arcgis/rest/services/"
        "USA_Major_Cities_/FeatureServer/0"
    ),
    layer_name="major_cities",
)

EXTERNAL_SOURCES = (BUILDINGS_SOURCE, EVACUATIONS_SOURCE, MAJOR_CITIES_SOURCE)


def fetch_external_source(
    source: peri_scribe.sources.external_data.ExternalSource,
    year_directory: pathlib.Path,
) -> tuple[pathlib.Path, ...]:
    """Retrieve *source* into *year_directory*'s sources directory.

    A compact source's database is built by the dedicated buildings converter. A live
    ArcGIS source is queried and stored as a single GeoPackage holding the layer's
    latest version, writing nothing when its features are unchanged since the stored
    version; a fetch that cannot retrieve the layer logs a warning and keeps the stored
    version so the caller can proceed. A download source's archive is downloaded,
    extracted, and converted to a GeoPackage, with the per-state results combined into
    one file when the source combines them.

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
    of the layer is kept at the source's fixed output path. When the layer cannot be
    retrieved and a current version is stored, a warning is logged and the stored
    version is kept so that the caller can proceed; when no version is stored at all,
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
                if source.name == EVACUATIONS_SOURCE.name
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
            peri_scribe.output.write_geopackage(
                temporary,
                [peri_scribe.models.LayerData(name=layer_name, dataframe=geodataframe)],
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
        ExternalDataError: If the layer cannot be fetched or returns no features.
    """
    try:
        gis = arcgis.gis.GIS()
        layer = arcgis.features.FeatureLayer(source.url, gis)
        feature_set = peri_scribe.geo.data.query_with_retry(
            source.name,
            layer,
            parameters=peri_scribe.geo.data.wgs84_query_parameters(
                source.where or "1=1",
            ),
        )
    except Exception as error:
        message = f"Failed to fetch external source {source.name}: {error}"
        raise peri_scribe.exceptions.ExternalDataError(message) from error
    if not feature_set.features:
        message = f"External source {source.name} returned no features"
        raise peri_scribe.exceptions.ExternalDataError(message)
    with peri_scribe.logging.log_phase(
        peri_scribe.phases.Phase.CONVERT_FEATURES,
        source=source.name,
    ):
        return peri_scribe.geo.data.geo_data_frame_from_feature_set(feature_set)
