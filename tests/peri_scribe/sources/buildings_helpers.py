"""Provide data builders and stand-ins for buildings tests."""

from __future__ import annotations

import io
import json
import pathlib
import sqlite3
import tempfile
import typing
import zipfile

import hypothesis.strategies
import numpy as np
import shapely
import shapely.affinity

import peri_scribe.sources.buildings
import peri_scribe.sources.external_sources
import tests.geometry_strategies
import tests.peri_scribe.sources.external_source_helpers


def encoded_coordinate(maximum: int) -> hypothesis.strategies.SearchStrategy[int]:
    """Exercise the inclusive geographic extremes as well as ordinary coordinates.

    Args:
        maximum: The largest representable longitude or latitude magnitude.

    Returns:
        An encoded coordinate with frequent samples at the limits of its domain.
    """
    return hypothesis.strategies.one_of(
        hypothesis.strategies.integers(-maximum, maximum),
        hypothesis.strategies.sampled_from([-maximum, maximum]),
    )


def encoded_points() -> hypothesis.strategies.SearchStrategy[list[tuple[int, int]]]:
    """Exercise signed coordinates, repeated records, and empty payloads.

    Returns:
        Lists of coordinate pairs in the database's quantized WGS84 domain.
    """
    return hypothesis.strategies.lists(
        hypothesis.strategies.tuples(
            encoded_coordinate(18_000_000),
            encoded_coordinate(9_000_000),
        ),
        max_size=40,
    )


@hypothesis.strategies.composite
def building_queries(
    draw: hypothesis.strategies.DrawFn,
) -> tuple[np.ndarray, list[shapely.Geometry | None]]:
    """Place buildings and queries on a shared grid to exercise containment boundaries.

    Small coordinate offsets straddle quantization thresholds; the grid crosses tile
    boundaries and allows duplicates, polygon holes, and bounding-box false positives.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        Building centroids and nearby geometries to query against the stored points.
    """
    longitude = draw(hypothesis.strategies.integers(-340, 340)) / 2
    latitude = draw(hypothesis.strategies.integers(-140, 140)) / 2
    coordinate = hypothesis.strategies.tuples(
        hypothesis.strategies.integers(-2, 18),
        hypothesis.strategies.sampled_from(
            [-0.000006, -0.000004, 0, 0.000004, 0.000006],
        ),
    ).map(lambda pair: pair[0] / 4 + pair[1])
    points = np.asarray(
        draw(
            hypothesis.strategies.lists(
                hypothesis.strategies.tuples(coordinate, coordinate),
                max_size=40,
            ),
        ),
        dtype=float,
    ).reshape(-1, 2)
    points += [longitude, latitude]
    shapes = draw(
        hypothesis.strategies.lists(
            hypothesis.strategies.one_of(
                tests.geometry_strategies.local_shapes(),
                hypothesis.strategies.just(shapely.Polygon()),
                hypothesis.strategies.none(),
            ),
            max_size=6,
        ),
    )
    queries = [
        None
        if shape is None
        else shapely.affinity.translate(
            shapely.affinity.scale(shape, xfact=0.5, yfact=0.5, origin=(0, 0)),
            xoff=longitude,
            yoff=latitude,
        )
        for shape in shapes
    ]
    return points, queries


def write_database(points: np.ndarray, path: pathlib.Path) -> None:
    """Build a compact buildings database at *path* holding *points*.

    The points are appended to temporary partition files and processed through the
    production database build, so the resulting file is a real compact database.

    Args:
        points: The ``(n, 2)`` longitude/latitude pairs in degrees.
        path: The database path to write.
    """
    with tempfile.TemporaryDirectory() as temporary_directory:
        partition_directory = pathlib.Path(temporary_directory)
        with peri_scribe.sources.buildings.PartitionFiles(
            partition_directory,
        ) as partition_files:
            peri_scribe.sources.buildings.append_centroids_to_partitions(
                points,
                partition_files,
            )
        peri_scribe.sources.buildings.build_tiles_database(partition_directory, path)


def zip_bytes(members: dict[str, bytes]) -> bytes:
    """Return a zip archive holding *members*.

    Args:
        members: The member name to bytes mapping.

    Returns:
        The zip archive's bytes.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in members.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def feature_collection_bytes(rings: list[list[list[float]]]) -> bytes:
    """Return the bytes of a GeoJSON FeatureCollection holding *rings*.

    Args:
        rings: Each feature's polygon ring coordinates.

    Returns:
        The FeatureCollection's bytes.
    """
    features = [
        {
            "type": "Feature",
            "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        }
        for ring in rings
    ]
    body = json.dumps(
        {"type": "FeatureCollection", "features": features},
        separators=(",", ":"),
    )
    return body.encode("utf-8")


def square_ring(
    center_x: float,
    center_y: float,
    half: float = 0.5,
) -> list[list[float]]:
    """Return the ring of a square centered at (*center_x*, *center_y*).

    Args:
        center_x: The center longitude.
        center_y: The center latitude.
        half: Half the square's side length.

    Returns:
        The ring's coordinates.
    """
    return [
        [center_x - half, center_y - half],
        [center_x + half, center_y - half],
        [center_x + half, center_y + half],
        [center_x - half, center_y + half],
        [center_x - half, center_y - half],
    ]


def buildings_fetch_page() -> str:
    """Return a repository page with a download link for every state.

    Returns:
        The page's HTML.
    """
    links = {
        state: f"https://example.com/{state.replace(' ', '')}.geojson.zip"
        for state in peri_scribe.sources.external_sources.BUILDINGS_STATES
    }
    return tests.peri_scribe.sources.external_source_helpers.buildings_page_html(links)


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
    tests.peri_scribe.sources.external_source_helpers.FakeResponse,
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
    ) -> tests.peri_scribe.sources.external_source_helpers.FakeResponse:
        """Serve the buildings index or matching state archive without HTTP access.

        Args:
            url: ArcGIS layer or download URL supplied by the caller.
            kwargs: HTTP request options accepted by the response substitute.

        Returns:
            The index page or state archive selected by the URL.
        """
        urls.append(url)
        if url == peri_scribe.sources.external_sources.BUILDINGS_SOURCE.url:
            return tests.peri_scribe.sources.external_source_helpers.FakeResponse(
                page.encode("utf-8"),
            )
        return tests.peri_scribe.sources.external_source_helpers.FakeResponse(
            archives[url.rsplit("/", 1)[-1]],
        )

    return get
