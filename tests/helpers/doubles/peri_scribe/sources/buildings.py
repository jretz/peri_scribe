"""Replace buildings dependencies with controlled test doubles."""

from __future__ import annotations

import sqlite3
import threading
import typing

import numpy as np

import peri_scribe.exceptions
import peri_scribe.sources.buildings
import peri_scribe.sources.catalog
import tests.helpers.doubles.concurrency
import tests.helpers.doubles.peri_scribe.sources.external_source


class PausedArchiveResponse(
    tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse,
):
    """Pause a network read so cancellation can arrive before its bytes do."""

    def __init__(
        self,
        body: bytes,
        operation: tests.helpers.doubles.concurrency.BlockedOperation,
    ) -> None:
        """Keep read progress observable independently of worker lifetime.

        Args:
            body: A complete archive split into simulated network reads.
            operation: Gates controlling the first read.
        """
        super().__init__(body)
        self.operation = operation
        self.chunks_read = 0

    def iter_content(self, chunk_size: int) -> typing.Iterator[bytes]:
        """Expose whether cancellation prevents subsequent network reads.

        Args:
            chunk_size: The requested read size.

        Yields:
            Archive bytes, after the first read is released.
        """
        self.operation.run()
        for chunk in super().iter_content(chunk_size):
            self.chunks_read += 1
            yield chunk


def make_tile_read_recorder(
    *,
    identifiers: list[int],
    read_tile_points: typing.Callable[..., np.ndarray | None],
) -> typing.Callable[..., np.ndarray | None]:
    """Create a callback with controlled dependencies.

    Count tile reads while preserving real building coordinates.

    Args:
        identifiers: Shared list recording building tiles read from storage.
        read_tile_points: Original tile reader used to preserve stored building
            coordinates.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def read(connection: sqlite3.Connection, tile_id: int) -> np.ndarray | None:
        """Count tile reads while preserving real building coordinates.

        Args:
            connection: Open building-database connection used for the tile read.
            tile_id: Identifier of the building tile to read.

        Returns:
            The building coordinates stored in the selected tile.
        """
        identifiers.append(tile_id)
        return read_tile_points(connection, tile_id)

    return read


def make_state_archive_responder(
    *,
    urls: list[str],
    page: str,
    archives: dict[str, bytes],
) -> typing.Callable[
    ...,
    tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse,
]:
    """Create a callback with controlled dependencies.

    Serve the buildings index or matching state archive without HTTP access.

    Args:
        urls: Shared list recording requested download URLs.
        page: Buildings index HTML served before archive requests.
        archives: State archive contents keyed by archive filename.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def get(
        url: str,
        **kwargs: object,
    ) -> tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse:
        """Serve the buildings index or matching state archive without HTTP access.

        Args:
            url: ArcGIS layer or download URL supplied by the caller.
            kwargs: HTTP request options accepted by the response substitute.

        Returns:
            The index page or state archive selected by the URL.
        """
        urls.append(url)
        if url == peri_scribe.sources.catalog.BUILDINGS_SOURCE.url:
            return (
                tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse(
                    page.encode("utf-8"),
                )
            )
        return tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse(
            archives[url.rsplit("/", 1)[-1]],
        )

    return get


def archive_with_probe(
    probe: tests.helpers.doubles.concurrency.ConcurrentCalls,
    url: str,
    partitions: peri_scribe.sources.buildings.PartitionFiles,
    *,
    stopped: threading.Event,
) -> int:
    """Append repeated coordinates to shared partitions from overlapping workers.

    Args:
        probe: Gates shared by archive workers.
        url: The recognizable archive identifier.
        partitions: Real partition files receiving concurrent writes.
        stopped: The cancellation signal, which stays unset for successful workers.

    Returns:
        The number of appended building records.
    """
    probe.run(url)
    assert not stopped.is_set()
    points = np.zeros((10_000, 2))
    peri_scribe.sources.buildings.append_centroids_to_partitions(points, partitions)
    return len(points)


def interrupted_archives(
    operation: tests.helpers.doubles.concurrency.BlockedOperation,
    cancellation: threading.Event,
    url: str,
    partitions: peri_scribe.sources.buildings.PartitionFiles,
    *,
    stopped: threading.Event,
) -> int:
    """Fail one archive while another still owns the partition writer.

    Args:
        operation: Gates for the surviving worker.
        cancellation: Records when the surviving worker observes cancellation.
        url: The archive identifier, either broken or pending.
        partitions: Shared temporary partitions.
        stopped: The worker's cooperative cancellation signal.

    Returns:
        Zero, since the surviving archive stops before writing any points.

    Raises:
        ExternalDataError: For the broken archive after its peer starts.
    """
    if url == "broken":
        assert operation.started.wait(5)
        message = "archive failed"
        raise peri_scribe.exceptions.ExternalDataError(message)
    operation.started.set()
    assert stopped.wait(5)
    cancellation.set()
    operation.run()
    assert partitions.directory.exists()
    return 0
