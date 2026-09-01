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

The buildings source stores its data as the compact buildings SQLite database instead
of a GeoPackage: a dedicated converter (``peri_scribe.sources.buildings``) streams every
state's archive directly into the database, so the archives and their GeoJSON are never
written to disk, and the stored file holds only quantized centroid records in compressed
0.5° tiles with no attributes. The database is regenerated only when it is
missing or no longer matches the expected format.

The fire-source reader skips these files, so their GeoPackages are never mistaken
for fire snapshots.
"""

from __future__ import annotations

import dataclasses
import enum
import pathlib
import typing
from collections.abc import Callable

import arcgis.features
import arcgis.gis
import structlog
import us

import peri_scribe.exceptions
import peri_scribe.geo.data
import peri_scribe.models
import peri_scribe.output
import peri_scribe.sources.archives
import peri_scribe.sources.buildings
import peri_scribe.sources.digests
import peri_scribe.sources.downloading
import peri_scribe.sources.snapshots


logger = structlog.get_logger()


if typing.TYPE_CHECKING:
    import geopandas


class ExternalSourceKind(enum.Enum):
    """How an external source is retrieved."""

    ARCGIS = "arcgis"
    DOWNLOAD = "download"


@dataclasses.dataclass(frozen=True, kw_only=True)
class ExternalSource:
    """One external dataset and how to retrieve it.

    For an ``arcgis`` source, ``layer_name`` names the GeoPackage layer the features are
    written to and ``where`` optionally restricts the query. For a ``download`` source,
    ``url`` points at a zip archive that is downloaded, extracted, and converted to a
    GeoPackage. When ``states`` is non-empty the URL is a format template containing
    ``{state}`` and one archive is fetched per state, unless ``state_urls`` is set: then
    ``url`` names the page whose "Download links" table maps each state to its archive
    URL, and that page is loaded only when an archive is actually downloaded, so the
    links are always current. When ``combine`` is true the per-state results are
    concatenated into a single GeoPackage named for the source, and the per-state files
    are removed. When ``centroids`` is true the converted GeoPackage holds each
    feature's centroid point instead of its original geometry, and ``geodata_suffix``
    names the file (or file geodatabase directory, for a ``.gdb`` archive) inside the
    extracted archive that holds the vector data. When ``keep_attributes`` is false the
    converted GeoPackage holds only the geometry, dropping every attribute column. When
    ``compact_database`` is true the source's output is the compact buildings SQLite
    database (``sources/{name}.sqlite``), produced and read by the dedicated buildings
    converter rather than the generic GeoPackage conversion paths; the database holds no
    named layers, so ``layer_name`` is not required, and the other conversion options do
    not apply.
    """

    name: str
    kind: ExternalSourceKind
    url: str
    layer_name: str | None = None
    where: str | None = None
    states: tuple[str, ...] = ()
    # When true, the source's output is the compact buildings SQLite database, built and
    # read by the dedicated buildings converter rather than the generic GeoPackage
    # conversion paths.
    compact_database: bool = False
    # When true, the per-state results are concatenated into a single GeoPackage named
    # for the source and the per-state files are removed.
    combine: bool = False
    # When true, the source's archive is streamed and converted without ever writing the
    # archive or its GeoJSON to disk: the archive's bytes feed ``stream_unzip`` while
    # they arrive and each footprint is reduced to its centroid point. Only meaningful
    # for a ``download`` source whose archive is a zip holding a GeoJSON member,
    # combined into one GeoPackage, and reduced to centroids with no attributes.
    stream: bool = False
    centroids: bool = False
    keep_attributes: bool = True
    geodata_suffix: str = ".geojson"
    # A callable returning the mapping from state name to archive URL, read from the
    # source's page when an archive is downloaded. When set, ``url`` names the page
    # holding the "Download links" table and is not a download URL itself.
    state_urls: Callable[[], dict[str, str]] | None = None


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
        ExternalDataError: If the page cannot be downloaded, holds no download links,
            or is missing a link for one of the states.
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


BUILDINGS_SOURCE = ExternalSource(
    name="buildings",
    kind=ExternalSourceKind.DOWNLOAD,
    url="https://github.com/microsoft/USBuildingFootprints",
    states=BUILDINGS_STATES,
    state_urls=buildings_state_urls,
    compact_database=True,
)

EVACUATIONS_SOURCE = ExternalSource(
    name="evacuations",
    kind=ExternalSourceKind.ARCGIS,
    url=(
        "https://services.arcgis.com/BLN4oKB0N1YSgvY8/arcgis/rest/services/"
        "CA_EVACUATIONS_CalOESHosted_view/FeatureServer/0"
    ),
    layer_name="evacuations",
)

EXTERNAL_SOURCES = (
    BUILDINGS_SOURCE,
    EVACUATIONS_SOURCE,
)


def source_directory_path(
    year_directory: pathlib.Path,
    source: ExternalSource,
) -> pathlib.Path:
    """Return the directory that holds *source*'s retrieved data.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.
        source: The external source.

    Returns:
        The source's directory under the year's sources directory.
    """
    return (
        peri_scribe.sources.snapshots.sources_directory_path(year_directory)
        / source.name
    )


def output_path(
    year_directory: pathlib.Path,
    source: ExternalSource,
    *,
    state: str | None = None,
) -> pathlib.Path:
    """Return the path where *source*'s database is stored.

    A source that produces a single file stores it directly under the sources directory,
    named for the source (or, for a live ArcGIS source, at that same fixed path holding
    its latest version). A per-state download source produces one file per state, so its
    files stay under the source's own directory. A compact source uses the ``.sqlite``
    suffix; every other source stores a GeoPackage.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.
        source: The external source.
        state: The state, for a per-state source.

    Returns:
        The path to the source's database.

    Raises:
        ValueError: If *source* is a combined source and *state* is given.
    """
    if source.combine and state is not None:
        message = f"Source {source.name} combines its states into one database"
        raise ValueError(message)
    suffix = ".sqlite" if source.compact_database else ".gpkg"
    if state is not None:
        return source_directory_path(year_directory, source) / f"{state}{suffix}"
    return (
        peri_scribe.sources.snapshots.sources_directory_path(year_directory)
        / f"{source.name}{suffix}"
    )


def fetch_external_source(
    source: ExternalSource,
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
    if source.kind is ExternalSourceKind.ARCGIS:
        return (fetch_arcgis_source(source, year_directory),)
    if source.kind is ExternalSourceKind.DOWNLOAD:
        return peri_scribe.sources.downloading.download_source(source, year_directory)
    message = f"Unknown external source kind {source.kind!r}"
    raise peri_scribe.exceptions.ExternalDataError(message)


def fetch_arcgis_source(
    source: ExternalSource,
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
        ExternalDataError: If the layer cannot be retrieved and no current version
            is stored.
    """
    layer_name = source.layer_name or source.name
    output = output_path(year_directory, source)
    try:
        geodataframe = query_arcgis_source(source)
    except peri_scribe.exceptions.ExternalDataError as error:
        if output.is_file():
            logger.warning(
                "Failed to fetch external source; keeping current data",
                source=source.name,
                error=str(error),
            )
            return output
        raise
    if output.is_file() and peri_scribe.sources.digests.snapshot_matches(
        geodataframe,
        output,
        layer_name,
    ):
        logger.debug(
            "External source unchanged",
            source=source.name,
            path=output,
        )
        return output
    temporary = output.with_name(f"{output.stem}.tmp.gpkg")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        peri_scribe.output.write_geopackage(
            temporary,
            [
                peri_scribe.models.LayerData(
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


def query_arcgis_source(source: ExternalSource) -> geopandas.GeoDataFrame:
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
            parameters={
                "where": source.where or "1=1",
                "out_sr": peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID,
            },
        )
    except Exception as error:
        message = f"Failed to fetch external source {source.name}: {error}"
        raise peri_scribe.exceptions.ExternalDataError(message) from error
    if not feature_set.features:
        message = f"External source {source.name} returned no features"
        raise peri_scribe.exceptions.ExternalDataError(message)
    dataframe, geometries, geometry_warning = peri_scribe.geo.data.extract_geometries(
        feature_set.sdf,
    )
    if geometry_warning is not None:
        logger.warning(geometry_warning)
    return peri_scribe.geo.data.geo_data_frame_from(
        dataframe,
        geometries,
        peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID,
    )
