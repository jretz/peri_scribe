"""Reading derived values from one history row.

The history layers keep each fire's derived columns and its preserved source attributes;
these helpers read a single row's values and parse them for the KML output.
"""

from __future__ import annotations

import datetime
import json
import typing

import peri_scribe.geo_package


if typing.TYPE_CHECKING:
    import geopandas
    import pandas as pd


def latest_matching_row(
    frame: geopandas.GeoDataFrame,
    fire_identifiers: frozenset[str],
    entry_name: str,
) -> pd.Series | None:
    """Return the chronologically latest row of *frame* for one fire, or None.

    A fire with identifiers is matched by those identifiers; a fire without any is
    matched by name. The layer's rows are already in chronological order, so the last
    matching row is the latest.

    Args:
        frame: The history layer to search.
        fire_identifiers: The fire's identifiers.
        entry_name: The fire's name, used when it has no identifiers.

    Returns:
        The latest matching row, or None when the fire has none.
    """
    if fire_identifiers:
        matched = frame[frame["fire_identifier"].isin(sorted(fire_identifiers))]
    else:
        matched = frame[frame["fire_name"] == entry_name]
    if matched.empty:
        return None
    return matched.iloc[-1]


def column_value(row: pd.Series | None, column: str) -> object:
    """Return *row*'s value in *column*, or None when it is missing.

    Args:
        row: A history row, or None.
        column: The column to read.

    Returns:
        The column's value, or None when the row or value is missing.
    """
    if row is None or column not in row.index:
        return None
    value = row[column]
    if peri_scribe.geo_package.is_missing(value):
        return None
    return value


def text_value(row: pd.Series | None, column: str) -> str | None:
    """Return *row*'s text value in *column*, or None when it is blank.

    Args:
        row: A history row, or None.
        column: The column to read.

    Returns:
        The column's text, or None when it is missing or whitespace only.
    """
    value = column_value(row, column)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def float_value(row: pd.Series | None, column: str) -> float | None:
    """Return *row*'s numeric value in *column*, or None when it is missing.

    Args:
        row: A history row, or None.
        column: The column to read.

    Returns:
        The column's numeric value, or None when it cannot be read as a number.
    """
    value = column_value(row, column)
    if value is None:
        return None
    return peri_scribe.geo_package.numeric_value(value)


def as_datetime(value: object) -> datetime.datetime | None:
    """Return *value* as an aware datetime, or None when it is not one.

    Args:
        value: Any timestamp value.

    Returns:
        The value as an aware UTC datetime, or None when it cannot be parsed.
    """
    return peri_scribe.geo_package.observation_time_from(value)


def datetime_value(row: pd.Series | None, column: str) -> datetime.datetime | None:
    """Return *row*'s datetime value in *column*, or None when it is missing.

    Args:
        row: A history row, or None.
        column: The column to read.

    Returns:
        The column's value as an aware datetime, or None.
    """
    return as_datetime(column_value(row, column))


def source_attribute_value(row: pd.Series | None, key: str) -> object:
    """Return *key* from *row*'s preserved source attributes, or None.

    The history layers keep each row's original source attributes as a JSON string,
    which is where fields that have no derived column (such as the protecting unit)
    still live.

    Args:
        row: A history row, or None.
        key: The source attribute to read.

    Returns:
        The attribute's value, or None when it is absent.
    """
    raw = column_value(row, "source_attributes")
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            attributes = json.loads(raw)
        except json.JSONDecodeError:
            return None
    else:
        attributes = raw
    if not isinstance(attributes, dict):
        return None
    return attributes.get(key)


def source_text_value(row: pd.Series | None, key: str) -> str | None:
    """Return *key* from *row*'s source attributes as text, or None when blank.

    Args:
        row: A history row, or None.
        key: The source attribute to read.

    Returns:
        The attribute's text, or None when it is missing or whitespace only.
    """
    value = source_attribute_value(row, key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def first_source_text(
    perimeter_row: pd.Series | None,
    point_row: pd.Series | None,
    point_key: str | None,
    perimeter_key: str | None,
) -> str | None:
    """Return the first present attribute value among *point_key* and *perimeter_key*.

    The point feed's value wins when both feeds carry the same attribute; the perimeter
    feed's ``attr_``-prefixed value is the fallback.

    Args:
        perimeter_row: A perimeter history row, or None.
        point_row: A point history row, or None.
        point_key: The attribute key in the point row's source attributes, or
            None.
        perimeter_key: The attribute key in the perimeter row's source
            attributes, or None.

    Returns:
        The first present value, or None when both are missing.
    """
    if point_key is not None:
        value = source_text_value(point_row, point_key)
        if value is not None:
            return value
    if perimeter_key is not None:
        return source_text_value(perimeter_row, perimeter_key)
    return None


def numbered_source_text(
    perimeter_row: pd.Series | None,
    point_row: pd.Series | None,
    slot_keys: dict[int, tuple[str, str]],
) -> str | None:
    """Return the distinct present attribute values, ordered by slot number.

    Each numbered slot pairs the point feed's attribute with the perimeter feed's
    ``attr_``-prefixed counterpart. Values are kept in slot order, and a value that
    already appeared in an earlier slot is not repeated.

    Args:
        perimeter_row: A perimeter history row, or None.
        point_row: A point history row, or None.
        slot_keys: The point and perimeter attribute keys for each slot number.

    Returns:
        The distinct values joined with ``; ``, or None when all slots are missing.
    """
    values: list[str] = []
    for number in sorted(slot_keys):
        point_key, perimeter_key = slot_keys[number]
        for row, key in ((point_row, point_key), (perimeter_row, perimeter_key)):
            value = source_text_value(row, key)
            if value is not None and value not in values:
                values.append(value)
    return "; ".join(values) if values else None


def source_label(source: object) -> str | None:
    """Return the human-readable name of a perimeter source kind.

    Args:
        source: The ``source`` column value of a perimeter row.

    Returns:
        The source's display name, or None when *source* is missing or unknown.
    """
    if peri_scribe.geo_package.is_missing(source):
        return None
    return {
        "firis_perimeter": "FIRIS / NIFC",
        "wfigs_perimeter": "WFIGS",
    }.get(str(source))
