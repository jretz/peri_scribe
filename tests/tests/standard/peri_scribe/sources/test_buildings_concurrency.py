"""Concurrent archive conversion preserves every shared-tile record."""

import asyncio
import functools
import pathlib
import threading
import unittest.mock

import pytest
import shapely.geometry

import peri_scribe.exceptions
import peri_scribe.fires.centroid_streaming
import peri_scribe.sources.buildings
import peri_scribe.sources.network
import tests.helpers.doubles.concurrency
import tests.helpers.doubles.peri_scribe.sources.buildings
import tests.helpers.factories.peri_scribe.sources.buildings


@pytest.mark.asyncio
async def test_stream_one_archive_stops_download_on_cancellation(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = tests.helpers.doubles.concurrency.BlockedOperation()
    body = tests.helpers.factories.peri_scribe.sources.buildings.zip_bytes({
        "buildings.geojson": (
            tests.helpers.factories.peri_scribe.sources.buildings.feature_collection_bytes([
                tests.helpers.factories.peri_scribe.sources.buildings.square_ring(0, 0),
            ])
        ),
    })
    response = (
        tests.helpers.doubles.peri_scribe.sources.buildings.PausedArchiveResponse(
            body,
            operation,
        )
    )
    monkeypatch.setattr(peri_scribe.sources.network, "DOWNLOAD_CHUNK_SIZE", 32)
    monkeypatch.setattr(
        peri_scribe.sources.network.requests,
        "get",
        unittest.mock.Mock(return_value=response),
    )
    with peri_scribe.sources.buildings.PartitionFiles(tmp_path) as partitions:
        task = asyncio.create_task(
            peri_scribe.sources.buildings.stream_one_archive(
                "https://example.com/buildings.zip",
                partitions,
                asyncio.Semaphore(1),
            ),
        )
        try:
            assert await asyncio.to_thread(operation.started.wait, 5)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            assert not response.closed
        finally:
            operation.release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert response.closed
    assert response.chunks_read == 1
    assert await asyncio.to_thread(
        lambda: all(path.stat().st_size == 0 for path in tmp_path.iterdir()),
    )


@pytest.mark.asyncio
async def test_stream_state_archives_bounds_overlap_and_preserves_shared_tiles(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capacity = 2
    probe = tests.helpers.doubles.concurrency.ConcurrentCalls(capacity)
    monkeypatch.setattr(peri_scribe.sources.buildings, "ARCHIVE_CONCURRENCY", capacity)
    monkeypatch.setattr(
        peri_scribe.sources.buildings,
        "stream_state_archive",
        functools.partial(
            tests.helpers.doubles.peri_scribe.sources.buildings.archive_with_probe,
            probe,
        ),
    )
    with peri_scribe.sources.buildings.PartitionFiles(tmp_path) as partitions:
        task = asyncio.create_task(
            peri_scribe.sources.buildings.stream_state_archives(
                (str(index) for index in range(5)),
                partitions,
            ),
        )
        try:
            assert await asyncio.to_thread(probe.ready.wait, 5)
            assert len(probe.started) == capacity
        finally:
            probe.release.set()
        await task
    assert probe.peak == capacity
    database = tmp_path / "buildings.sqlite"
    expected_count = 50_000
    assert (
        peri_scribe.sources.buildings.build_tiles_database(tmp_path, database)
        == expected_count
    )
    assert peri_scribe.sources.buildings.building_counts_within(
        [shapely.geometry.box(-1, -1, 1, 1)],
        database,
    ) == [expected_count]


@pytest.mark.asyncio
async def test_stream_state_archives_keeps_partitions_until_workers_finish(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = tests.helpers.doubles.concurrency.BlockedOperation()
    cancellation = threading.Event()
    monkeypatch.setattr(
        peri_scribe.sources.buildings,
        "stream_state_archive",
        functools.partial(
            tests.helpers.doubles.peri_scribe.sources.buildings.interrupted_archives,
            operation,
            cancellation,
        ),
    )
    with peri_scribe.sources.buildings.PartitionFiles(tmp_path) as partitions:
        task = asyncio.create_task(
            peri_scribe.sources.buildings.stream_state_archives(
                ["pending", "broken"],
                partitions,
            ),
        )
        try:
            assert await asyncio.to_thread(cancellation.wait, 5)
            assert not task.done()
        finally:
            operation.release.set()
        with pytest.raises(
            peri_scribe.exceptions.ExternalDataError,
            match="archive failed",
        ):
            await task
    assert operation.finished.is_set()
    assert await asyncio.to_thread(
        lambda: all(path.stat().st_size == 0 for path in tmp_path.iterdir()),
    )


def test_convert_geometry_chunks_to_partitions_stops_before_next_batch(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stopped = threading.Event()
    first = shapely.geometry.mapping(shapely.geometry.box(0, 0, 1, 1))
    second = shapely.geometry.mapping(shapely.geometry.box(1, 1, 2, 2))
    geometries = iter([first, second])
    monkeypatch.setattr(peri_scribe.fires.centroid_streaming, "FEATURE_CHUNK_SIZE", 1)
    monkeypatch.setattr(
        peri_scribe.sources.buildings,
        "append_centroids_to_partitions",
        lambda *_args: stopped.set(),
    )
    with (
        peri_scribe.sources.buildings.PartitionFiles(tmp_path) as partitions,
        pytest.raises(asyncio.CancelledError),
    ):
        peri_scribe.sources.buildings.convert_geometry_chunks_to_partitions(
            geometries,
            partitions,
            stopped=stopped,
        )
    assert next(geometries) == second
