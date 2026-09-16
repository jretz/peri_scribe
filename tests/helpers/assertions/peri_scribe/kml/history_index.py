"""Compare history index behavior through reusable assertions."""

from __future__ import annotations

import typing


if typing.TYPE_CHECKING:
    import geopandas


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
