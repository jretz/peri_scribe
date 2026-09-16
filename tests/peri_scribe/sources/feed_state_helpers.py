"""Build source snapshots with repeated identifiers and mixed geometry column names."""

from __future__ import annotations

import typing

import hypothesis.strategies
import shapely

import tests.factories


if typing.TYPE_CHECKING:
    import geopandas


def sql_values() -> hypothesis.strategies.SearchStrategy[str | int | float | bool]:
    """Exercise literal escaping and fractional numbers within SQLite's value domain.

    SQLite provides an independent decoder for standard SQL literals. Query text cannot
    contain NUL or unpaired surrogates, and integers must fit its signed 64-bit range.

    Returns:
        Text, booleans, finite real numbers, and signed 64-bit integers.
    """
    return hypothesis.strategies.one_of(
        hypothesis.strategies.text(
            hypothesis.strategies.characters(
                exclude_categories=("Cs",),
                exclude_characters="\0",
            ),
            max_size=80,
        ),
        hypothesis.strategies.integers(-(2**63), 2**63 - 1),
        hypothesis.strategies.floats(-1_000_000, 1_000_000),
        hypothesis.strategies.booleans(),
    )


def feature_batches() -> hypothesis.strategies.SearchStrategy[
    list[list[tuple[int, str]]]
]:
    """Make repeated identifiers common across short sequences of source snapshots.

    Returns:
        Feature batches in their source observation order.
    """
    return hypothesis.strategies.lists(
        hypothesis.strategies.lists(
            hypothesis.strategies.tuples(
                hypothesis.strategies.integers(0, 5),
                hypothesis.strategies.text(max_size=30),
            ),
            max_size=8,
        ),
        min_size=1,
        max_size=5,
    )


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
        frame = tests.factories.geo_frame(
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
