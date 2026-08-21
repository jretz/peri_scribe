"""Reading typed values from a fire row's attribute dictionary.

These helpers read the first present value among a list of candidate column names and
convert it to the requested type. They are shared by version reconciliation and row
construction, which both interpret the attributes a source row carries.
"""

from __future__ import annotations

import datetime

import peri_scribe.changes
import peri_scribe.geo_package


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
    """
    for column_name in column_names:
        if column_name in attributes:
            value = attributes[column_name]
            if not peri_scribe.geo_package.is_missing(value):
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
    """
    return peri_scribe.geo_package.numeric_value(
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
    """
    return peri_scribe.changes.modified_datetime_from(
        attribute_value(attributes, *column_names),
    )
