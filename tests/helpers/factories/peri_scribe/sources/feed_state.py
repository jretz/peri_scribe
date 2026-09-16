"""Build inputs for feed state tests."""

from __future__ import annotations

import typing

import shapely

import tests.helpers.factories.geography


if typing.TYPE_CHECKING:
    import geopandas


def feature_frames(
    batches: list[list[tuple[int, str]]],
) -> list[geopandas.GeoDataFrame]:
    """Exercise both fetched and persisted geometry column conventions.

    Args:
        batches: Source feature identifiers and values, oldest batch first.

    Returns:
        Frames alternating between fetched and persisted geometry column names.
    """
    frames = []
    for index, batch in enumerate(batches):
        frame = tests.helpers.factories.geography.geo_frame(
            {
                "OBJECTID": [identifier for identifier, _value in batch],
                "value": [value for _identifier, value in batch],
            },
            [shapely.Point(identifier, len(value)) for identifier, value in batch],
        )
        if index % 2:
            frame = typing.cast("geopandas.GeoDataFrame", frame.rename_geometry("geom"))
        frames.append(frame)
    return frames
