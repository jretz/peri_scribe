"""Provide data builders and stand-ins for logging tests."""

from __future__ import annotations

import dataclasses
import enum
import pathlib


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
