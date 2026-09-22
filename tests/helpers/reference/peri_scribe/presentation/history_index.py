"""Calculate independent expected results for history index tests."""

from __future__ import annotations

import typing


if typing.TYPE_CHECKING:
    import geopandas


def select(
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
