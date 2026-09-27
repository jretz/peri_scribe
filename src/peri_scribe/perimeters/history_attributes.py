"""Reading typed values from a fire row's attribute dictionary.

Typed helpers use the first usable value in column priority order. They are shared by
version reconciliation and row construction, which both interpret source attributes.
"""

from __future__ import annotations

import datetime
import typing

import peri_scribe.geo.parsing
import peri_scribe.sources.changes


if typing.TYPE_CHECKING:
    import collections.abc


def attribute_value(attributes: dict[str, object], *args: str) -> object | None:
    """Return the first present value among *args*, or None.

    Args:
        attributes: The row's attributes.
        args: The column names to look up, in priority order.

    Returns:
        The first non-missing value, or None.

    Examples:
        >>> attribute_value({"old": None, "new": "value"}, "old", "new")
        'value'
    """
    for column_name in args:
        if column_name in attributes:
            value = attributes[column_name]
            if not peri_scribe.geo.parsing.is_missing(value):
                return value
    return None


def text_attribute(attributes: dict[str, object], *args: str) -> str | None:
    """Return the first nonblank text value among *args*, or None.

    Args:
        attributes: The row's attributes.
        args: The column names to look up, in priority order.

    Returns:
        The first non-blank text value, or None.

    Examples:
        >>> text_attribute({"name": "  Rumsey Fire  "}, "name")
        'Rumsey Fire'
    """
    return typed_attribute(attributes, args, peri_scribe.geo.parsing.fire_name_from)


def typed_attribute[T](
    attributes: dict[str, object],
    columns: tuple[str, ...],
    parse: collections.abc.Callable[[object], T | None],
) -> T | None:
    """Keep unusable higher-priority fields from hiding valid fallback values.

    Args:
        attributes: The row's attributes.
        columns: The column names to look up, in priority order.
        parse: The requested type's parser, returning None for unusable values.

    Returns:
        The first successfully parsed value, or None.
    """
    for column in columns:
        parsed = parse(attributes.get(column))
        if parsed is not None:
            return parsed
    return None


def float_attribute(attributes: dict[str, object], *args: str) -> float | None:
    """Return the first finite numeric value among *args*, or None.

    Args:
        attributes: The row's attributes.
        args: The column names to look up, in priority order.

    Returns:
        The first numeric value as a float, or None.

    Examples:
        >>> float_attribute({"acres": "12.5"}, "acres")
        12.5
    """
    return typed_attribute(attributes, args, peri_scribe.geo.parsing.numeric_value)


def datetime_attribute(
    attributes: dict[str, object],
    *args: str,
) -> datetime.datetime | None:
    """Return the first usable datetime value among *args*, or None.

    Args:
        attributes: The row's attributes.
        args: The column names to look up, in priority order.

    Returns:
        The first datetime value, or None.

    Examples:
        >>> datetime_attribute({"edited": 0}, "edited").isoformat()
        '1970-01-01T00:00:00+00:00'
    """
    return typed_attribute(
        attributes,
        args,
        peri_scribe.sources.changes.modified_datetime_from,
    )
