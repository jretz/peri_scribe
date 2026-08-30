"""Fire identity and grouping keys."""

from __future__ import annotations

import typing

import pandas as pd

import peri_scribe.geo.parsing


if typing.TYPE_CHECKING:
    import geopandas


def identity_key(name: str, identifier: str | None) -> str:
    """Return the key that identifies a fire for score persistence.

    A fire's identifier is preferred; a fire without one is keyed by name.

    Args:
        name: The fire's name.
        identifier: The fire's canonical identifier, or None.

    Returns:
        The fire's stable key.
    """
    return identifier if identifier is not None else f"name:{name}"


def normalized_identifier(value: object) -> str | None:
    """Return an identifier as a string, or None when it is missing.

    Args:
        value: A row's identifier value.

    Returns:
        The identifier, or None when the value is missing.
    """
    if peri_scribe.geo.parsing.is_missing(value):
        return None
    return str(value)


def group_keys(dataframe: geopandas.GeoDataFrame) -> pd.Series:
    """Return the identity key for each history row.

    Args:
        dataframe: A history layer.

    Returns:
        One identity key per row, aligned with the dataframe's index.
    """
    if dataframe.empty:
        return pd.Series(dtype=object, index=dataframe.index)
    return pd.Series(
        [
            identity_key(
                str(name),
                normalized_identifier(identifier),
            )
            for name, identifier in zip(
                dataframe["fire_name"],
                dataframe["fire_identifier"],
                strict=True,
            )
        ],
        index=dataframe.index,
    )
