"""Inspect conversion behavior with shared test utilities."""

from __future__ import annotations

import typing

import pandas as pd


if typing.TYPE_CHECKING:
    import geopandas


def comparable_attributes(frame: geopandas.GeoDataFrame) -> pd.DataFrame:
    """Treat Pandas null representations and chunk-dependent dtypes as equivalent.

    Args:
        frame: Features read together or in separate chunks.

    Returns:
        Attribute values with uniform missing-value representation.
    """
    attributes = pd.DataFrame(frame.drop(columns=frame.geometry.name), dtype=object)
    return attributes.where(attributes.notna(), None)
