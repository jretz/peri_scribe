"""Build inputs for digests tests."""

from __future__ import annotations

import typing

import pandas as pd
import shapely.geometry

import tests.helpers.factories.geography


if typing.TYPE_CHECKING:
    import geopandas


def missing_value_frame(missing: object) -> geopandas.GeoDataFrame:
    """Build equivalent dataframes with different missing-value representations.

    Args:
        missing: Missing-value representation to place in the attribute column.

    Returns:
        Two point rows with the selected missing attribute value.
    """
    return tests.helpers.factories.geography.geo_frame(
        {"value": pd.array([1, missing], dtype=object)},
        [shapely.geometry.Point(0.0, 0.0), shapely.geometry.Point(1.0, 1.0)],
    )
