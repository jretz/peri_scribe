"""Reading typed values from a fire row's attribute dictionary.

These helpers read the first present value among a list of candidate column names and
convert it to the requested type. They are shared by version reconciliation and row
construction, which both interpret the attributes a source row carries.
"""

from __future__ import annotations

import datetime

import peri_scribe.geo.parsing
import peri_scribe.sources.changes


def attribute_value(
    attributes: dict[str, object],
    *column_names: str,
) -> object | None:
    """Return the first present value among *column_names*, or None.

    Args:
        attributes: The row's attributes.
        column_names: The column names to look up, in priority order.

    Returns:
        The first non-missing value, or None.

    Examples:
        >>> attribute_value({"old": None, "new": "value"}, "old", "new")
        'value'
    """
    for column_name in column_names:
        if column_name in attributes:
            value = attributes[column_name]
            if not peri_scribe.geo.parsing.is_missing(value):
                return value
    return None


def text_attribute(
    attributes: dict[str, object],
    *column_names: str,
) -> str | None:
    """Return the first present text value among *column_names*, or None.

    Args:
        attributes: The row's attributes.
        column_names: The column names to look up, in priority order.

    Returns:
        The first non-blank text value, or None.

    Examples:
        >>> text_attribute({"name": "  Rumsey Fire  "}, "name")
        'Rumsey Fire'
    """
    value = attribute_value(attributes, *column_names)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def float_attribute(
    attributes: dict[str, object],
    *column_names: str,
) -> float | None:
    """Return the first present numeric value among *column_names*, or None.

    Args:
        attributes: The row's attributes.
        column_names: The column names to look up, in priority order.

    Returns:
        The first numeric value as a float, or None.

    Examples:
        >>> float_attribute({"acres": "12.5"}, "acres")
        12.5
    """
    return peri_scribe.geo.parsing.numeric_value(
        attribute_value(attributes, *column_names),
    )


def datetime_attribute(
    attributes: dict[str, object],
    *column_names: str,
) -> datetime.datetime | None:
    """Return the first present datetime value among *column_names*, or None.

    Args:
        attributes: The row's attributes.
        column_names: The column names to look up, in priority order.

    Returns:
        The first datetime value, or None.

    Examples:
        >>> datetime_attribute({"edited": 0}, "edited").isoformat()
        '1970-01-01T00:00:00+00:00'
    """
    return peri_scribe.sources.changes.modified_datetime_from(
        attribute_value(attributes, *column_names),
    )
