"""Replace downloading dependencies with controlled test doubles."""

from __future__ import annotations

import pathlib
import typing

import requests

import peri_scribe.sources.catalog
import peri_scribe.sources.downloading
import spatial_data.layers
import tests.helpers.doubles.peri_scribe.sources.external_source


if typing.TYPE_CHECKING:
    import geopandas
    import pytest


def make_failing_archive_responder(
    *,
    page: str,
) -> typing.Callable[
    ...,
    tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse,
]:
    """Create a callback with controlled dependencies.

    Serve the buildings index and fail the subsequent archive download.

    Args:
        page: Buildings index HTML served before archive requests.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def get(
        url: str,
        **kwargs: object,
    ) -> tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse:
        """Serve the buildings index and fail the subsequent archive download.

        Args:
            url: ArcGIS layer or download URL supplied by the caller.
            kwargs: HTTP request options accepted by the response substitute.

        Returns:
            The buildings index response.

        Raises:
            requests.exceptions.RequestException: If the
                request targets an archive.
        """
        if url == peri_scribe.sources.catalog.BUILDINGS_SOURCE.url:
            return (
                tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse(
                    page.encode("utf-8"),
                )
            )
        message = "boom"
        raise requests.exceptions.RequestException(
            message,
        )

    return get


def fail_after_append(
    monkeypatch: pytest.MonkeyPatch,
    *,
    write_number: int,
) -> None:
    """Interrupt a real conversion after bytes have reached its destination.

    Args:
        monkeypatch: Isolated replacement scope.
        write_number: The successful chunk write after which to interrupt.
    """
    original = spatial_data.layers.append_geopackage_chunk
    calls = 0

    def append(
        output: pathlib.Path,
        layer_name: str,
        dataframe: geopandas.GeoDataFrame,
        *,
        replace: bool,
    ) -> None:
        """Expose readable partial data before the conversion fails.

        Args:
            output: Destination selected by the production coordinator.
            layer_name: Destination layer.
            dataframe: The successfully received chunk.
            replace: Whether this begins the output file.

        Raises:
            RuntimeError: After the selected completed chunk write.
        """
        nonlocal calls
        original(output, layer_name, dataframe, replace=replace)
        calls += 1
        if calls == write_number:
            message = "interrupted after chunk write"
            raise RuntimeError(message)

    monkeypatch.setattr(spatial_data.layers, "append_geopackage_chunk", append)


def fail_after_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    """Interrupt between streamed state archives after the first file exists.

    Args:
        monkeypatch: Isolated replacement scope.
    """
    original = peri_scribe.sources.downloading.stream_download_and_convert

    def convert(
        url: str,
        output: pathlib.Path,
        layer_name: str,
        *,
        append: bool,
    ) -> int:
        """Leave a successfully written chunk before interrupting its coordinator.

        Args:
            url: Mocked archive URL.
            output: Destination selected by the production coordinator.
            layer_name: Destination layer.
            append: Whether the destination already contains data.

        Raises:
            RuntimeError: After the streamed archive is written.
        """
        original(url, output, layer_name, append=append)
        message = "interrupted after chunk write"
        raise RuntimeError(message)

    monkeypatch.setattr(
        peri_scribe.sources.downloading,
        "stream_download_and_convert",
        convert,
    )


def guard_immutable_chunk_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bound real chunk iteration when a write accidentally targets its own input.

    Args:
        monkeypatch: Isolated replacement scope.
    """
    original = spatial_data.layers.read_layer_chunks

    def chunks(
        path: pathlib.Path,
        layer_name: str | None,
        chunk_size: int,
    ) -> typing.Iterator[geopandas.GeoDataFrame]:
        """Reject mutation of a completed source while yielding its actual rows.

        Args:
            path: The completed conversion to read.
            layer_name: Its selected layer.
            chunk_size: The production chunk bound.

        Yields:
            Real chunks without letting source mutation create an infinite reader.
        """
        content = path.read_bytes()
        for chunk in original(path, layer_name, chunk_size):
            yield chunk
            assert path.read_bytes() == content, "The source changed while being read"

    monkeypatch.setattr(spatial_data.layers, "read_layer_chunks", chunks)
