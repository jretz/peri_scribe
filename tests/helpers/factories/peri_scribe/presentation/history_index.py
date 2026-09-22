"""Build inputs for history index tests."""

from __future__ import annotations

import typing

import tests.helpers.factories.geography
import tests.helpers.factories.geometry


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
    return tests.helpers.factories.geography.geo_frame(
        {
            "fire_identifier": [identifier for identifier, _name in rows],
            "fire_name": [name for _identifier, name in rows],
        },
        [
            tests.helpers.factories.geometry.square(float(index + 1))
            for index in range(len(rows))
        ],
    )
