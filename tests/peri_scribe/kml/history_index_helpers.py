"""Provide data builders and stand-ins for history index tests."""

from __future__ import annotations

import typing

import hypothesis.strategies
import pandas as pd

import tests.factories


if typing.TYPE_CHECKING:
    import geopandas


def history_frame(rows: list[tuple[object, object]]) -> geopandas.GeoDataFrame:
    """Build a history frame from *(identifier, name)* rows.

    Each row gets a distinct square so its position stays observable in the geometry.

    Args:
        rows: Each row's identifier and name.

    Returns:
        The rows as a GeoDataFrame.
    """
    return tests.factories.geo_frame(
        {
            "fire_identifier": [identifier for identifier, _name in rows],
            "fire_name": [name for _identifier, name in rows],
        },
        [tests.factories.square(float(index + 1)) for index in range(len(rows))],
    )


def assert_same_rows(
    actual: geopandas.GeoDataFrame,
    expected: geopandas.GeoDataFrame,
) -> None:
    """Assert that two frames hold the same rows in the same order.

    Args:
        actual: The rows the index selected.
        expected: The rows the reference filter selected.
    """
    assert list(actual["fire_identifier"]) == list(expected["fire_identifier"])
    assert list(actual["fire_name"]) == list(expected["fire_name"])
    assert len(actual) == len(expected)
    assert all(
        a.equals(b) for a, b in zip(actual.geometry, expected.geometry, strict=True)
    )


def reference_selection(
    frame: geopandas.GeoDataFrame,
    fire_identifiers: frozenset[str],
    name: str,
) -> geopandas.GeoDataFrame:
    """Return the rows the old boolean filters would select.

    Args:
        frame: The history layer to search.
        fire_identifiers: The fire's identifiers.
        name: The fire's name, used when it has no identifiers.

    Returns:
        The matching rows.
    """
    if fire_identifiers:
        return frame[frame["fire_identifier"].isin(sorted(fire_identifiers))]
    return frame[frame["fire_name"] == name]


def history_rows() -> hypothesis.strategies.SearchStrategy[list[tuple[object, object]]]:
    """Exercise repeated lookup keys, null conventions, and distinct scalar types.

    Returns:
        Raw identifier and name pairs for a generated history layer.
    """
    values = hypothesis.strategies.sampled_from(
        (None, pd.NA, float("nan"), 0, 1, "0", "1", "", "River", "Cañon"),
    )
    return hypothesis.strategies.lists(
        hypothesis.strategies.tuples(values, values),
        max_size=30,
    )
