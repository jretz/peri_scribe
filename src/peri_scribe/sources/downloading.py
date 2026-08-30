"""Downloading and streaming external datasets as GeoPackages."""

from __future__ import annotations

import pathlib
import tempfile
import typing
import urllib.parse

import requests
import structlog

import peri_scribe.exceptions
import peri_scribe.fires.centroid_streaming
import peri_scribe.geo.reading
import peri_scribe.geo.spatial_reference
import peri_scribe.sources.archives
import peri_scribe.sources.conversion
import peri_scribe.sources.external_sources


logger = structlog.get_logger()


if typing.TYPE_CHECKING:
    import geopandas

REQUEST_TIMEOUT_SECONDS = 60


DOWNLOAD_CHUNK_SIZE = 1024 * 1024


def state_download_url(
    source: peri_scribe.sources.external_sources.ExternalSource,
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
    source: peri_scribe.sources.external_sources.ExternalSource,
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
    directory = peri_scribe.sources.external_sources.source_directory_path(
        year_directory,
        source,
    )
    if source.combine:
        if source.stream:
            return (stream_combined_source(source, year_directory),)
        return (combine_downloaded_source(source, year_directory),)
    directory.mkdir(parents=True, exist_ok=True)
    paths: list[pathlib.Path] = []
    for state in source.states or (None,):
        output = peri_scribe.sources.external_sources.output_path(
            year_directory,
            source,
            state=state,
        )
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
    source: peri_scribe.sources.external_sources.ExternalSource,
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
    output = peri_scribe.sources.external_sources.output_path(year_directory, source)
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
    output.parent.mkdir(parents=True, exist_ok=True)
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
    ``peri_scribe.fires.centroid_streaming`` without ever writing the archive or its
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
        return peri_scribe.fires.centroid_streaming.convert_zip_stream(
            response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE),
            output,
            layer_name,
            first=not append,
        )
    except requests.exceptions.RequestException as error:
        message = f"Failed to download {url}: {error}"
        raise peri_scribe.exceptions.ExternalDataError(message) from error


def combine_downloaded_source(
    source: peri_scribe.sources.external_sources.ExternalSource,
    year_directory: pathlib.Path,
) -> pathlib.Path:
    """Download every state of *source* and combine them into one GeoPackage.

    Each state's archive is downloaded and converted inside a temporary directory, and
    the converted per-state GeoPackages are concatenated into the source's single
    GeoPackage. The temporary directory holds only intermediate files and is removed
    when the conversion finishes. When the combined GeoPackage already exists, the
    download is skipped entirely, since the archives are large and rarely change, and
    the page of per-state links is not read.

    Args:
        source: The combined download-backed external source.
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The path of the combined GeoPackage.
    """
    output = peri_scribe.sources.external_sources.output_path(year_directory, source)
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
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary_directory:
        temporary_path = pathlib.Path(temporary_directory)
        for state in source.states:
            state_output = temporary_path / f"{state}.gpkg"
            url = state_download_url(source, state, state_urls)
            download_and_convert(source, temporary_path, url, state_output)
            for chunk in peri_scribe.geo.reading.read_layer_chunks(
                state_output,
                layer_name,
                peri_scribe.sources.conversion.CONVERSION_CHUNK_SIZE,
            ):
                dataframe = chunk.to_crs(
                    peri_scribe.geo.spatial_reference.WGS84_SPATIAL_REFERENCE,
                )
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
    source: peri_scribe.sources.external_sources.ExternalSource,
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
        peri_scribe.sources.archives.download_archive(url, archive_path)
        with tempfile.TemporaryDirectory(dir=directory) as extraction_directory:
            extraction_path = pathlib.Path(extraction_directory)
            peri_scribe.sources.archives.extract_archive(archive_path, extraction_path)
            geodata_path = peri_scribe.sources.archives.find_geodata_path(
                extraction_path,
                source.geodata_suffix,
            )
            peri_scribe.sources.conversion.convert_to_geopackage(
                geodata_path,
                output,
                source.layer_name or source.name,
                centroids=source.centroids,
                keep_attributes=source.keep_attributes,
            )
    finally:
        archive_path.unlink(missing_ok=True)
    return output
