"""Download policy and cooperative cancellation for building point datasets."""

from __future__ import annotations

import asyncio
import functools
import pathlib
import tempfile
import threading
import typing

import stream_unzip
import structlog

import peri_scribe.concurrency
import peri_scribe.exceptions
import peri_scribe.logging
import peri_scribe.phases
import peri_scribe.sources.downloading
import peri_scribe.sources.external_data
import peri_scribe.sources.network
import spatial_data.centroid_streaming
import spatial_data.point_store


logger = structlog.get_logger()


ARCHIVE_CONCURRENCY = 3


def convert_geometry_chunks_to_partitions(
    features_iter: typing.Iterator[typing.Any],
    partition_files: spatial_data.point_store.PartitionFiles,
    *,
    stopped: threading.Event,
) -> int:
    """Convert *features_iter*'s geometry dicts into records at *partition_files*.

    Each bounded chunk's centroid points are quantized and appended to the partition
    files, so the stream is consumed without ever holding the whole archive in memory.

    Args:
        features_iter: The ijson geometry iterator, created by the caller.
        partition_files: The partition files to append to.
        stopped: The worker's cooperative cancellation signal.

    Returns:
        The number of features converted.
    """
    feature_count = 0
    for centroids in peri_scribe.concurrency.cancellable(
        spatial_data.centroid_streaming.centroid_chunks(features_iter),
        stopped,
    ):
        spatial_data.point_store.append_centroids_to_partitions(
            centroids,
            partition_files,
        )
        feature_count += len(centroids)
    return feature_count


async def stream_one_archive(
    url: str,
    partition_files: spatial_data.point_store.PartitionFiles,
    limit: asyncio.Semaphore,
) -> None:
    """Let conversion demand pace each download inside a bounded worker set.

    Args:
        url: The state archive URL.
        partition_files: Shared partitions with serialized append operations.
        limit: The maximum number of simultaneous converters.
    """
    async with limit:
        stopped = threading.Event()
        await peri_scribe.concurrency.run_blocking(
            functools.partial(
                stream_state_archive,
                url,
                partition_files,
                stopped=stopped,
            ),
            stopped=stopped,
        )


async def stream_state_archives(
    urls: typing.Iterable[str],
    partition_files: spatial_data.point_store.PartitionFiles,
) -> None:
    """Overlap network waits without buffering entire archives or centroid datasets.

    Cancellation stops workers between download and conversion chunks. Each task waits
    for its worker to exit so the temporary partitions outlive every write.

    Args:
        urls: Each state archive URL.
        partition_files: Shared partitions with serialized append operations.

    Raises:
        ExternalDataError: An archive could not be downloaded or converted.
    """
    limit = asyncio.Semaphore(ARCHIVE_CONCURRENCY)
    try:
        async with asyncio.TaskGroup() as tasks:
            for url in urls:
                tasks.create_task(stream_one_archive(url, partition_files, limit))
    except* peri_scribe.exceptions.ExternalDataError as errors:
        raise peri_scribe.exceptions.ExternalDataError(
            str(errors.exceptions[0]),
        ) from errors


def stream_state_archive(
    url: str,
    partition_files: spatial_data.point_store.PartitionFiles,
    *,
    stopped: threading.Event,
) -> int:
    """Stream *url*'s archive and convert its records at *partition_files*.

    The archive's bytes are read from the response as they arrive and converted without
    ever writing the archive or its GeoJSON to disk.

    Args:
        url: The archive's URL.
        partition_files: The partition files to append to.
        stopped: The worker's cooperative cancellation signal.

    Returns:
        The number of features converted.

    Raises:
        ExternalDataError: If the download fails, the stream is not a zip archive, or
            the archive holds no GeoJSON member with any features.
    """
    with peri_scribe.sources.network.downloaded_response(
        url,
        stream=True,
    ) as response:
        feature_count = convert_stream_to_partitions(
            response.iter_content(
                chunk_size=peri_scribe.sources.network.DOWNLOAD_CHUNK_SIZE,
            ),
            partition_files,
            stopped=stopped,
        )
    if not feature_count:
        message = "No GeoJSON data found in the streamed archive"
        raise peri_scribe.exceptions.ExternalDataError(message)
    return feature_count


def convert_stream_to_partitions(
    bytes_source: typing.Iterable[bytes],
    partition_files: spatial_data.point_store.PartitionFiles,
    *,
    stopped: threading.Event,
) -> int:
    """Convert the GeoJSON members of a zip archive streaming from *bytes_source*.

    Each member named like ``*.geojson`` is parsed and converted; other members are
    consumed so the archive's next member can be read from the stream.

    Args:
        bytes_source: An iterable of byte chunks of the zip archive, in order.
        partition_files: The partition files to append to.
        stopped: The worker's cooperative cancellation signal.

    Returns:
        The number of features converted.

    Raises:
        ExternalDataError: If the stream is not a zip archive or its GeoJSON cannot be
            read.
    """
    try:
        return convert_geometry_chunks_to_partitions(
            spatial_data.centroid_streaming.zip_geometries(
                peri_scribe.concurrency.cancellable(bytes_source, stopped),
            ),
            partition_files,
            stopped=stopped,
        )
    except stream_unzip.UnzipError as error:
        message = f"The streamed archive is not a zip file: {error}"
        raise peri_scribe.exceptions.ExternalDataError(message) from error
    except Exception as error:
        message = f"Failed to read the streamed GeoJSON: {error}"
        raise peri_scribe.exceptions.ExternalDataError(message) from error


def fetch_buildings_database(
    source: peri_scribe.sources.external_data.ExternalSource,
    year_directory: pathlib.Path,
) -> tuple[pathlib.Path, ...]:
    """Retrieve *source*'s compact buildings database into *year_directory*.

    When a valid database already exists at the output path, nothing is downloaded and
    its path is returned. Otherwise the repository page is read, every state's archive
    is streamed into the sixteen partition files, and the partition files are processed
    into a database written at a temporary path. The temporary database is validated and
    only then atomically renamed into place, so an existing database (valid or not) is
    preserved whenever downloading or generation fails and the temporary partition files
    are removed either way.

    Args:
        source: The compact buildings external source.
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The path of the stored database.

    Raises:
        ExternalDataError: If the source's page or any archive cannot be retrieved, or
            the generated database fails validation.
    """
    output = peri_scribe.sources.external_data.output_path(year_directory, source)
    if spatial_data.point_store.is_valid_database(output):
        logger.debug("External source already present", source=source.name, path=output)
        return (output,)
    with peri_scribe.logging.log_phase(
        peri_scribe.phases.Phase.BUILDINGS_DATABASE,
        source=source.name,
        path=output,
    ):
        output.parent.mkdir(parents=True, exist_ok=True)
        state_urls = source.state_urls() if source.state_urls is not None else None
        with tempfile.TemporaryDirectory(dir=output.parent) as temporary_directory:
            directory = pathlib.Path(temporary_directory)
            partition_directory = directory / "partitions"
            partition_directory.mkdir()
            with spatial_data.point_store.PartitionFiles(
                partition_directory,
            ) as partition_files:
                urls = (
                    peri_scribe.sources.downloading.state_download_url(
                        source,
                        state,
                        state_urls,
                    )
                    for state in source.states
                )
                asyncio.run(stream_state_archives(urls, partition_files))
            database_path = directory / f"{output.stem}.tmp.sqlite"
            building_count = spatial_data.point_store.build_tiles_database(
                partition_directory,
                database_path,
            )
            if not spatial_data.point_store.is_valid_database(database_path):
                message = "The generated buildings database is invalid"
                raise peri_scribe.exceptions.ExternalDataError(message)
            database_path.replace(output)
        logger.debug(
            "Fetched compact buildings database",
            source=source.name,
            path=output,
            buildings=building_count,
        )
    return (output,)
