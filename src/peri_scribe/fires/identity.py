"""Fire identity and grouping keys."""

from __future__ import annotations

import typing

import pandas as pd

import peri_scribe.geo.parsing


if typing.TYPE_CHECKING:
    import geopandas


def identity_key(
    name: str,
    identifier: str | None,
    component_id: str | None = None,
) -> str:
    """Return the key that identifies a fire for score persistence.

    External identifiers, anonymous source components, and legacy names have separate
    namespaces. Reserved identifier prefixes are escaped so source text cannot
    impersonate an internal component or a name.

    Args:
        name: The fire's name.
        identifier: The fire's canonical identifier, or None.
        component_id: Its internal anonymous component, when known.

    Returns:
        The fire's stable key.

    Examples:
        >>> identity_key("Camp Fire", "2025-LNU-123456")
        '2025-LNU-123456'

        >>> identity_key("Camp Fire", None)
        'name:Camp Fire'
    """
    if identifier is not None:
        return (
            "id:" + identifier
            if identifier.startswith(("id:", "name:", "component:"))
            else identifier
        )
    if component_id is not None:
        return f"component:{component_id}"
    return f"name:{name}"


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
                normalized_identifier(component),
            )
            for name, identifier, component in zip(
                dataframe["fire_name"],
                dataframe["fire_identifier"],
                dataframe.get("fire_component_id", [None] * len(dataframe)),
                strict=True,
            )
        ],
        index=dataframe.index,
    )
