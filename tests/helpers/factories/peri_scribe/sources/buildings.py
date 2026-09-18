"""Build inputs for buildings tests."""

from __future__ import annotations

import io
import json
import pathlib
import tempfile
import typing
import zipfile

import peri_scribe.sources.buildings
import peri_scribe.sources.catalog
import tests.helpers.factories.peri_scribe.sources.external_source


if typing.TYPE_CHECKING:
    import numpy as np


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
        for state in peri_scribe.sources.catalog.BUILDINGS_STATES
    }
    return (
        tests.helpers.factories.peri_scribe.sources.external_source.buildings_page_html(
            links,
        )
    )


# The encoded coordinate values the quantization tests expect.


QUANTIZED_ONE_POINT_FIVE_DEGREES = 150_000


QUANTIZED_NEGATIVE_HALF_DEGREE = -50_000


QUANTIZED_FORTY_POINT_TWENTY_FIVE_DEGREES = 4_025_000


QUANTIZED_NEGATIVE_NINETY_DEGREES = -9_000_000


QUANTIZED_HALF_DEGREE = 50_000
