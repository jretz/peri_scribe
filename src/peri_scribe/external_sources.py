"""Retrieving external (non-fire) datasets into a year's sources directory.

The fire feeds describe the fires themselves; the datasets here describe what those
fires threaten or what the conditions are around them. Each dataset is retrieved into
its own directory under ``data/{year}/sources/{name}/``, the same tree that holds the
fire-feed snapshots, so everything a report needs is in one place. The datasets cover
the whole United States, not just California.

Two retrieval kinds are supported:

- ``arcgis``: an ArcGIS FeatureServer layer is queried and stored as a GeoPackage
  snapshot. The layers are live (the evacuation zones refresh every few minutes), so
  each fetch stores a new serial-numbered snapshot when the layer's features changed,
  keeping the season's history for later per-fire analysis.
- ``download``: a file (typically a zip archive) is downloaded, extracted, and converted
  to a GeoPackage holding the same data. These datasets are static, so a source whose
  GeoPackage already exists is left alone.

A download source covers the whole country as one archive per state (the building
footprints). A combined source (the building footprints) concatenates the per-state
results into a single GeoPackage and keeps no other files; the building-footprint source
reduces each footprint polygon to a centroid point and keeps no attributes, since only
the buildings' locations are wanted. The buildings source is streamed: its zip archives
are decompressed as their bytes arrive and the conversion feeds on the stream, so the
archive and its GeoJSON are never written to disk. Any other download is converted in
bounded chunks — a GeoJSON archive is parsed one feature at a time with ``ijson`` and
any other vector data is read in chunks — so a source of any size is converted without
loading the whole file into memory. The original archives are not kept once converted.
The building footprints' per-state archive links are not constructed from a URL pattern;
they are read from the "Download links" table on the dataset's repository page whenever
the archives are downloaded, so a change in the link scheme is picked up automatically.

The fire-source reader skips these directories, so their GeoPackages are never mistaken
for fire snapshots.
"""

from __future__ import annotations

import dataclasses
import datetime
import enum
import hashlib
import math
import pathlib
import tempfile
import time
import typing
import urllib.parse
import zipfile
from collections.abc import Callable
from html.parser import HTMLParser

import arcgis.features
import arcgis.gis
import geopandas
import ijson
import pandas as pd
import pyproj
import requests
import shapely
import structlog
import us

import peri_scribe.centroid_streaming
import peri_scribe.exceptions
import peri_scribe.feed_types
import peri_scribe.geo_data
import peri_scribe.geo_package
import peri_scribe.models
import peri_scribe.output
import peri_scribe.snapshots


logger = structlog.get_logger()

REQUEST_TIMEOUT_SECONDS = 60
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
CONVERSION_CHUNK_SIZE = 100_000

WGS84_SPATIAL_REFERENCE = pyproj.CRS.from_epsg(
    peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID,
)


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
    converted GeoPackage holds only the geometry, dropping every attribute column.
    """

    name: str
    kind: ExternalSourceKind
    url: str
    layer_name: str | None = None
    where: str | None = None
    states: tuple[str, ...] = ()
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


# Microsoft's computer-generated US building footprints: one zip per state (plus the
# District of Columbia), each holding a single GeoJSON of footprint polygons. The
# per-state download links are not constructed from a URL pattern; they are read from
# the "Download links" table on the dataset's repository page when the archives are
# downloaded, because the pattern is not reliable (for example, New Hampshire's archive
# is named NewHampshire.geojson.zip, without the space). The source is combined: every
# state's footprints are reduced to their centroid points (the full polygon shapes are
# not needed) and concatenated into one GeoPackage, keeping no attributes and no
# per-state files.
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
    html_text = fetch_page_text(BUILDINGS_SOURCE.url)
    links = download_links(html_text)
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
    layer_name="buildings",
    states=BUILDINGS_STATES,
    combine=True,
    stream=True,
    centroids=True,
    keep_attributes=False,
    state_urls=buildings_state_urls,
)

# Cal OES's California Evacuation Aggregation Layer: an aggregation of county
# evacuation-zone services and Genasys, refreshed every five minutes. California is the
# only state with a published, aggregated evacuation-zones layer.
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
    return peri_scribe.snapshots.sources_directory_path(year_directory) / source.name


def output_path(
    year_directory: pathlib.Path,
    source: ExternalSource,
    *,
    state: str | None = None,
) -> pathlib.Path:
    """Return the path where a downloaded *source*'s GeoPackage is stored.

    A live ArcGIS source stores serial-numbered snapshots instead, so its output path is
    chosen per fetch and this function is only meaningful for a download source. A
    per-state source stores one GeoPackage per state; a combined source stores a single
    GeoPackage named for the source.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.
        source: The external source.
        state: The state, for a per-state source.

    Returns:
        The path to the source's GeoPackage.

    Raises:
        ValueError: If *source* is a live ArcGIS source, or a combined source and
            *state* is given.
    """
    if source.kind is ExternalSourceKind.ARCGIS:
        message = f"Live source {source.name} stores snapshots, not a single file"
        raise ValueError(message)
    if source.combine and state is not None:
        message = f"Source {source.name} combines its states into one GeoPackage"
        raise ValueError(message)
    directory = source_directory_path(year_directory, source)
    if state is not None:
        return directory / f"{state}.gpkg"
    return directory / f"{source.name}.gpkg"


def fetch_external_source(
    source: ExternalSource,
    year_directory: pathlib.Path,
) -> tuple[pathlib.Path, ...]:
    """Retrieve *source* into *year_directory*'s sources directory.

    A live ArcGIS source is queried and stored as a serial-numbered snapshot, writing
    nothing when its features are unchanged since the latest snapshot. A download
    source's archive is downloaded, extracted, and converted to a GeoPackage, with the
    per-state results combined into one file when the source combines them.

    Args:
        source: The external source to retrieve.
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The paths of the retrieved GeoPackages.

    Raises:
        ExternalDataError: If the source cannot be retrieved.
    """
    if source.kind is ExternalSourceKind.ARCGIS:
        return (fetch_arcgis_source(source, year_directory),)
    if source.kind is ExternalSourceKind.DOWNLOAD:
        return download_source(source, year_directory)
    message = f"Unknown external source kind {source.kind!r}"
    raise peri_scribe.exceptions.ExternalDataError(message)


def fetch_arcgis_source(
    source: ExternalSource,
    year_directory: pathlib.Path,
) -> pathlib.Path:
    """Query a live ArcGIS layer and store a snapshot when its data changed.

    The layer is queried in full. When the features are identical to the latest stored
    snapshot, nothing is written and that snapshot's path is returned. Otherwise a new
    snapshot is written, numbered one past the largest stored serial number and named
    for the layer's observed last-edit timestamp (the current time when the timestamp
    cannot be observed), so each fetch keeps the season's history of the layer's state.

    Args:
        source: The ArcGIS-backed external source.
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The path of the stored snapshot.
    """
    directory = source_directory_path(year_directory, source)
    existing = peri_scribe.snapshots.existing_source_files(directory)
    geodataframe = query_arcgis_source(source)
    layer_name = source.layer_name or source.name
    if existing:
        latest_path = directory / existing[-1].relative_path
        if snapshot_matches(geodataframe, latest_path, layer_name):
            logger.debug(
                "External source unchanged",
                source=source.name,
                path=latest_path,
            )
            return latest_path
    timestamp = snapshot_timestamp(source)
    source_file = peri_scribe.snapshots.SourceFile(
        serial_number=peri_scribe.snapshots.next_serial_number(
            existing,
            timestamp,
            reuse_same_timestamp=False,
        ),
        last_edit_timestamp=timestamp,
    )
    path = directory / source_file.relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    peri_scribe.output.write_geopackage(
        path,
        [
            peri_scribe.models.LayerData(
                name=layer_name,
                dataframe=geodataframe,
            ),
        ],
    )
    logger.debug(
        "Fetched external source",
        source=source.name,
        path=path,
        features=len(geodataframe),
    )
    return path


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
        feature_set = peri_scribe.geo_data.query_with_retry(
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
    dataframe, geometries, geometry_warning = peri_scribe.geo_data.extract_geometries(
        feature_set.sdf,
    )
    if geometry_warning is not None:
        logger.warning(geometry_warning)
    return peri_scribe.geo_data.geo_data_frame_from(
        dataframe,
        geometries,
        peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID,
    )


def snapshot_timestamp(source: ExternalSource) -> int:
    """Return the last-edit timestamp naming *source*'s next snapshot.

    The layer's ``editingInfo.lastEditDate`` value is used when it can be observed; the
    current time is used otherwise, so a snapshot can always be named.

    Args:
        source: The ArcGIS-backed external source.

    Returns:
        The timestamp in epoch milliseconds.
    """
    observed = peri_scribe.feed_types.observe_layer_last_edit_timestamp(
        source.url,
        source.name,
    )
    if observed is not None:
        return observed
    return time.time_ns() // 1_000_000


def snapshot_matches(
    dataframe: geopandas.GeoDataFrame,
    snapshot_path: pathlib.Path,
    layer_name: str,
) -> bool:
    """Return whether *dataframe* holds the same features as *snapshot_path*.

    The comparison uses each frame's content digest, so the features may appear in any
    row order. An unreadable snapshot is treated as a mismatch, so a new snapshot is
    written rather than history being lost.

    Args:
        dataframe: The freshly fetched features.
        snapshot_path: The latest stored snapshot.
        layer_name: The snapshot's layer name.

    Returns:
        True when the snapshot holds the same features as *dataframe*.
    """
    try:
        stored = geopandas.read_file(snapshot_path, layer=layer_name)
    except (OSError, RuntimeError, ValueError) as error:
        logger.warning(
            "Failed to read external source snapshot",
            path=snapshot_path,
            error=str(error),
        )
        return False
    return dataframe_digest(dataframe) == dataframe_digest(stored)


def dataframe_digest(dataframe: geopandas.GeoDataFrame) -> str:
    """Return an order-independent content digest for *dataframe*.

    Every row contributes a digest of its attributes and geometry, and the row digests
    are hashed in sorted order, so two dataframes holding the same features in a
    different row order digest alike. Missing values of any kind (None, pandas NA or
    NaT, NaN) digest alike, so a value that a GeoPackage round-trip stores as NaN rather
    than None does not count as a change.

    Args:
        dataframe: The GeoDataFrame to digest.

    Returns:
        The SHA-256 digest of the dataframe's content.
    """
    geometry_column = dataframe.geometry.name
    attribute_columns = sorted(
        column for column in dataframe.columns if column != geometry_column
    )
    row_digests: list[str] = []
    for _index, row in dataframe.iterrows():
        hasher = hashlib.sha256()
        for column in attribute_columns:
            hasher.update(digest_value(row[column]))
        geometry = row[geometry_column]
        hasher.update(geometry.wkb if geometry is not None else b"m")
        row_digests.append(hasher.hexdigest())
    row_digests.sort()
    final_hasher = hashlib.sha256()
    for digest in row_digests:
        final_hasher.update(digest.encode("ascii"))
    return final_hasher.hexdigest()


def digest_value(value: object) -> bytes:
    """Return a digest fragment for one attribute *value*.

    Missing values of any flavor (None, pandas NA or NaT, NaN) share a fragment, so a
    value stored by a GeoPackage as NaN rather than None does not count as a change. The
    remaining fragments tag the value's kind, keeping values of different types from
    digesting alike.

    Args:
        value: The attribute value to digest.

    Returns:
        The digest fragment for *value*.
    """
    if (
        value is None
        or value is pd.NA
        or value is pd.NaT
        or (isinstance(value, float) and math.isnan(value))
    ):
        fragment = b"m"
    elif isinstance(value, str):
        fragment = b"s" + value.encode("utf-8")
    elif isinstance(value, bool):
        fragment = b"t" if value else b"f"
    elif isinstance(value, (int, float)):
        fragment = b"n" + repr(value).encode("ascii")
    elif isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        fragment = b"d" + value.isoformat().encode("ascii")
    elif isinstance(value, bytes):
        fragment = b"x" + value
    elif isinstance(value, shapely.Geometry):
        fragment = b"g" + value.wkb
    else:
        fragment = b"?" + repr(value).encode("utf-8")
    return fragment


def state_download_url(
    source: ExternalSource,
    state: str | None,
    state_urls: dict[str, str] | None,
) -> str:
    """Return the archive URL for *state*.

    When the source reads its links from a web page, *state_urls* maps each state to its
    archive URL. Otherwise *source.url* is the archive URL itself (for a single-archive
    source) or a format template containing ``{state}``.

    Args:
        source: The download-backed external source.
        state: The state whose archive is fetched, or None for a single archive.
        state_urls: The state-to-URL mapping read from the source's page, or None
            when the source has no page of links.

    Returns:
        The archive's URL.
    """
    if state is not None:
        if state_urls is not None:
            return state_urls[state]
        return source.url.format(state=urllib.parse.quote(state))
    return source.url


def download_source(
    source: ExternalSource,
    year_directory: pathlib.Path,
) -> tuple[pathlib.Path, ...]:
    """Download and convert *source*'s archives into GeoPackages.

    A source with ``states`` downloads and converts one archive per state, and a
    combined source concatenates the per-state results into a single GeoPackage,
    removing the per-state files; any other source downloads and converts its single
    archive. A source whose GeoPackage already exists is skipped, since the archives are
    large and rarely change, and a page of per-state links is only read when something
    will actually be downloaded.

    Args:
        source: The download-backed external source.
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The paths of the written GeoPackages.
    """
    directory = source_directory_path(year_directory, source)
    directory.mkdir(parents=True, exist_ok=True)
    if source.combine:
        if source.stream:
            return (stream_combined_source(source, year_directory),)
        return (combine_downloaded_source(source, directory, year_directory),)
    paths: list[pathlib.Path] = []
    for state in source.states or (None,):
        output = output_path(year_directory, source, state=state)
        if output.is_file():
            logger.debug(
                "External source already present",
                source=source.name,
                path=output,
            )
            paths.append(output)
            continue
        state_urls = source.state_urls() if source.state_urls is not None else None
        url = state_download_url(source, state, state_urls)
        paths.append(download_and_convert(source, directory, url, output))
    return tuple(paths)


def stream_combined_source(
    source: ExternalSource,
    year_directory: pathlib.Path,
) -> pathlib.Path:
    """Stream every state of *source* into one combined GeoPackage.

    Each state's archive is downloaded and converted as one stream: the archive is
    decompressed as its bytes arrive and each footprint is reduced to its centroid
    point, appended directly into the source's single GeoPackage. Nothing is written to
    disk except the combined GeoPackage, so the archive, its GeoJSON, and the per-state
    files never exist. When the combined GeoPackage already exists, the download is
    skipped entirely, since the archives are large and rarely change, and the page of
    per-state links is not read.

    Args:
        source: The combined streaming download-backed external source.
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The path of the combined GeoPackage.

    Raises:
        ValueError: If the source is not configured to reduce to centroid points
            with no attributes, which the streaming conversion requires.
    """
    output = output_path(year_directory, source)
    if output.is_file():
        logger.debug(
            "External source already present",
            source=source.name,
            path=output,
        )
        return output
    if not source.centroids or source.keep_attributes:
        message = (
            f"Streaming source {source.name} must reduce to centroid points "
            "with no attributes"
        )
        raise ValueError(message)
    state_urls = source.state_urls() if source.state_urls is not None else None
    layer_name = source.layer_name or source.name
    feature_count = 0
    wrote_any = False
    for state in source.states:
        url = state_download_url(source, state, state_urls)
        count = stream_download_and_convert(
            url,
            output,
            layer_name,
            append=wrote_any,
        )
        wrote_any = wrote_any or count > 0
        feature_count += count
    logger.debug(
        "Combined external source",
        path=output,
        features=feature_count,
    )
    return output


def stream_download_and_convert(
    url: str,
    output: pathlib.Path,
    layer_name: str,
    *,
    append: bool,
) -> int:
    """Stream *url*'s archive and convert it to centroid points at *output*.

    The archive's bytes are read from the response as they arrive and converted by
    ``peri_scribe.centroid_streaming`` without ever writing the archive or its
    GeoJSON to disk.

    Args:
        url: The archive's URL.
        output: The GeoPackage path to append to.
        layer_name: The GeoPackage layer.
        append: Append to an existing layer rather than creating the file.

    Returns:
        The number of features converted.

    Raises:
        ExternalDataError: If the download fails.
    """
    try:
        response = requests.get(
            url,
            stream=True,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return peri_scribe.centroid_streaming.convert_zip_stream(
            response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE),
            output,
            layer_name,
            first=not append,
        )
    except requests.exceptions.RequestException as error:
        message = f"Failed to download {url}: {error}"
        raise peri_scribe.exceptions.ExternalDataError(message) from error


def combine_downloaded_source(
    source: ExternalSource,
    directory: pathlib.Path,
    year_directory: pathlib.Path,
) -> pathlib.Path:
    """Download every state of *source* and combine them into one GeoPackage.

    Each state's archive is downloaded and converted inside a temporary directory, and
    the converted per-state GeoPackages are concatenated into the source's single
    GeoPackage. The temporary directory holds only intermediate files and is removed
    when the conversion finishes, so the source directory ends up holding just the
    combined GeoPackage. When the combined GeoPackage already exists, the download is
    skipped entirely, since the archives are large and rarely change, and the page of
    per-state links is not read.

    Args:
        source: The combined download-backed external source.
        directory: The directory that holds the source's data.
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The path of the combined GeoPackage.
    """
    output = output_path(year_directory, source)
    if output.is_file():
        logger.debug(
            "External source already present",
            source=source.name,
            path=output,
        )
        return output
    state_urls = source.state_urls() if source.state_urls is not None else None
    layer_name = source.layer_name or source.name
    wrote_any = False
    feature_count = 0
    with tempfile.TemporaryDirectory(dir=directory) as temporary_directory:
        temporary_path = pathlib.Path(temporary_directory)
        for state in source.states:
            state_output = temporary_path / f"{state}.gpkg"
            url = state_download_url(source, state, state_urls)
            download_and_convert(source, temporary_path, url, state_output)
            for chunk in peri_scribe.geo_package.read_layer_chunks(
                state_output,
                layer_name,
                CONVERSION_CHUNK_SIZE,
            ):
                dataframe = chunk.to_crs(WGS84_SPATIAL_REFERENCE)
                append_geopackage_chunk(
                    output,
                    layer_name,
                    dataframe,
                    replace=not wrote_any,
                )
                wrote_any = True
                feature_count += len(dataframe)
    logger.debug(
        "Combined external source",
        path=output,
        features=feature_count,
    )
    return output


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


def download_and_convert(
    source: ExternalSource,
    directory: pathlib.Path,
    url: str,
    output: pathlib.Path,
) -> pathlib.Path:
    """Download and convert one of *source*'s archives into *output*.

    Args:
        source: The download-backed external source.
        directory: The directory that holds the source's archives.
        url: The archive's URL.
        output: The GeoPackage path to write.

    Returns:
        The path of the written GeoPackage.
    """
    archive_name = urllib.parse.unquote(
        pathlib.Path(urllib.parse.urlsplit(url).path).name,
    )
    archive_path = directory / archive_name
    try:
        download_archive(url, archive_path)
        with tempfile.TemporaryDirectory(dir=directory) as extraction_directory:
            extraction_path = pathlib.Path(extraction_directory)
            extract_archive(archive_path, extraction_path)
            geodata_path = find_geodata_path(
                extraction_path,
                source.geodata_suffix,
            )
            convert_to_geopackage(
                geodata_path,
                output,
                source.layer_name or source.name,
                centroids=source.centroids,
                keep_attributes=source.keep_attributes,
            )
    finally:
        archive_path.unlink(missing_ok=True)
    return output


def fetch_page_text(url: str) -> str:
    """Download *url* and return its text.

    Args:
        url: The page's URL.

    Returns:
        The page's text.

    Raises:
        ExternalDataError: If the page cannot be downloaded.
    """
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.exceptions.RequestException as error:
        message = f"Failed to download {url}: {error}"
        raise peri_scribe.exceptions.ExternalDataError(message) from error
    return response.text


class DownloadLinksParser(HTMLParser):
    """Extract the state-to-URL pairs from a page's "Download links" table.

    GitHub renders the repository's README into the page: each heading is a ``<div
    class="markdown-heading">`` holding the heading element and a permalink anchor, and
    the tables that follow hold the links. The links are collected from the table after
    the "Download links" heading until the next heading starts. The README's copy inside
    the page's embedded-data script is script content, which the parser never treats as
    markup.
    """

    def __init__(self) -> None:
        super().__init__()
        self.links: dict[str, str] = {}
        self._heading_level: str | None = None
        self._heading_text: list[str] = []
        self._collecting = False
        self._anchor_href: str | None = None
        self._anchor_text: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attribute_map = dict(attrs)
        if tag in {"h1", "h2", "h3"}:
            self._heading_level = tag
            self._heading_text = []
        elif tag == "a":
            self._anchor_href = attribute_map.get("href")
            self._anchor_text = []
        elif (
            tag == "div"
            and "markdown-heading" in (attribute_map.get("class") or "").split()
        ):
            # A new README heading ends the previous section's link table.
            self._collecting = False

    def handle_data(self, data: str) -> None:
        if self._heading_level is not None:
            self._heading_text.append(data)
        elif self._anchor_href is not None:
            self._anchor_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h1", "h2", "h3"} and tag == self._heading_level:
            heading = "".join(self._heading_text).strip().lower()
            if heading in {"download links", "downloads links"}:
                self._collecting = True
            self._heading_level = None
            self._heading_text = []
        elif tag == "a":
            if self._collecting:
                label = "".join(self._anchor_text).strip()
                href = self._anchor_href
                if label and href is not None and href.startswith("http"):
                    self.links[label] = href
            self._anchor_href = None
            self._anchor_text = []


def download_links(html_text: str) -> dict[str, str]:
    """Return the state-to-URL pairs from a page's "Download links" table.

    Args:
        html_text: The page's HTML.

    Returns:
        The mapping from state name to archive URL, in table order.
    """
    parser = DownloadLinksParser()
    parser.feed(html_text)
    return parser.links


def download_archive(url: str, archive_path: pathlib.Path) -> None:
    """Download *url* to *archive_path*.

    Args:
        url: The archive's URL.
        archive_path: Where to store the downloaded archive.

    Raises:
        ExternalDataError: If the download fails.
    """
    try:
        response = requests.get(
            url,
            stream=True,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        with archive_path.open("wb") as file:
            for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                file.write(chunk)
    except requests.exceptions.RequestException as error:
        message = f"Failed to download {url}: {error}"
        raise peri_scribe.exceptions.ExternalDataError(message) from error


def extract_archive(
    archive_path: pathlib.Path,
    extraction_directory: pathlib.Path,
) -> None:
    """Extract *archive_path* into *extraction_directory*.

    Args:
        archive_path: The zip archive to extract.
        extraction_directory: The directory to extract into.

    Raises:
        ExternalDataError: If the archive is not a zip file.
    """
    try:
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(extraction_directory)
    except zipfile.BadZipFile as error:
        message = f"{archive_path} is not a zip file: {error}"
        raise peri_scribe.exceptions.ExternalDataError(message) from error


def find_geodata_path(
    directory: pathlib.Path,
    suffix: str,
) -> pathlib.Path:
    """Return the first vector data path ending in *suffix* under *directory*.

    The suffix names either a data file (``.geojson``, ``.shp``) or a file geodatabase
    directory (``.gdb``), so both files and directories are matched.

    Args:
        directory: The extracted archive directory.
        suffix: The suffix that names the vector data (``.geojson``, ``.shp``,
            ``.gdb``).

    Returns:
        The vector data path.

    Raises:
        ExternalDataError: If no matching path is found.
    """
    matches = sorted(
        path
        for path in directory.rglob(f"*{suffix}")
        if path.is_file() or path.is_dir()
    )
    if not matches:
        message = f"No {suffix} data found under {directory}"
        raise peri_scribe.exceptions.ExternalDataError(message)
    return matches[0]


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
        yield from peri_scribe.geo_package.read_layer_chunks(
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
            append_geopackage_chunk(
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
        append_geopackage_chunk(
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
