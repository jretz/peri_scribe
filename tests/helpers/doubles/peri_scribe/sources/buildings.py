"""Replace buildings dependencies with controlled test doubles."""

from __future__ import annotations

import sqlite3
import typing

import peri_scribe.sources.catalog
import tests.helpers.doubles.peri_scribe.sources.external_source


if typing.TYPE_CHECKING:
    import numpy as np


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
