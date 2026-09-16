"""Build inputs for centroid streaming tests."""

from __future__ import annotations

import io
import json
import typing
import zipfile

import ijson


def geometry_features(
    geometries: list[dict[str, object]],
) -> typing.Iterator[typing.Any]:
    """Return an ijson geometry iterator over *geometries*.

    Args:
        geometries: The GeoJSON geometry dicts to iterate.

    Returns:
        An iterator of ``features.item.geometry`` dicts.
    """
    features = [
        {"type": "Feature", "properties": {}, "geometry": geometry}
        for geometry in geometries
    ]
    body = json.dumps(
        {"type": "FeatureCollection", "features": features},
        separators=(",", ":"),
    ).encode("utf-8")
    return ijson.items(io.BytesIO(body), "features.item.geometry", use_float=True)


def archive_bytes(members: dict[str, bytes]) -> bytes:
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


def polygon(coordinates: list[object]) -> dict[str, object]:
    """Return a Polygon geometry dict with *coordinates*.

    Args:
        coordinates: The GeoJSON coordinates.

    Returns:
        The Polygon geometry dict.
    """
    return {"type": "Polygon", "coordinates": coordinates}


SQUARE: dict[str, object] = polygon([[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]])


SQUARE_WITH_HOLE: dict[str, object] = polygon([
    [[10, 10], [12, 10], [12, 12], [10, 12], [10, 10]],
    [[10.5, 10.5], [10.5, 11.5], [11.5, 11.5], [11.5, 10.5], [10.5, 10.5]],
])


MULTIPOLYGON: dict[str, object] = {
    "type": "MultiPolygon",
    "coordinates": [
        [[[20, 20], [21, 20], [21, 21], [20, 21], [20, 20]]],
        [[[22, 20], [23, 20], [23, 21], [22, 21], [22, 20]]],
    ],
}


CLOCKWISE_SQUARE: dict[str, object] = polygon([
    [[40, 40], [40, 42], [42, 42], [42, 40], [40, 40]],
])
