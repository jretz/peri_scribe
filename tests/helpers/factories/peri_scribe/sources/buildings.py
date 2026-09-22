"""Build inputs for buildings tests."""

from __future__ import annotations

import io
import json
import zipfile

import peri_scribe.sources.catalog
import tests.helpers.factories.peri_scribe.sources.external_source


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
