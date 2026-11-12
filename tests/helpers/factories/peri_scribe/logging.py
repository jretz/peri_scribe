"""Build inputs for logging tests."""

from __future__ import annotations

import dataclasses
import enum
import pathlib
import types


class LogStatus(enum.StrEnum):
    """A named status must remain a plain string in serialized logs."""

    SKIPPED = "skipped"


@dataclasses.dataclass(frozen=True, kw_only=True)
class LogDetails:
    """Structured log fields need recursive normalization of their values.

    Args:
        path: A filesystem path that must become a JSON string.
        status: A named status that must retain its string value.
    """

    path: pathlib.Path
    status: LogStatus


def structured_log_value(value: object) -> types.SimpleNamespace:
    """Supply a custom JSON representation through Structlog's public protocol.

    Args:
        value: The custom representation, including its original keys and order.

    Returns:
        An object implementing the custom serialization callback.
    """

    def render() -> object:
        """Return the selected representation.

        Returns:
            The unmodified value.
        """
        return value

    return types.SimpleNamespace(__structlog__=render)
