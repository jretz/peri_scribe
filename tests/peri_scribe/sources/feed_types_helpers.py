"""Provide data builders and stand-ins for feed types tests."""

from __future__ import annotations

from tests.conftest import (
    SAMPLE_FEED_URL,
    SAMPLE_FIRE_NAME_COLUMN,
    SAMPLE_STATUS_COLUMN,
)


def feed_document(**overrides: object) -> dict[str, object]:
    """Return the sample feed's configuration document with *overrides*.

    Args:
        overrides: Configuration keys to add or replace.

    Returns:
        The feed configuration document.
    """
    return {
        "feed_type": "ArcGISFeed",
        "url": SAMPLE_FEED_URL,
        "fire_name_column": SAMPLE_FIRE_NAME_COLUMN,
        "status_column": SAMPLE_STATUS_COLUMN,
        **overrides,
    }
