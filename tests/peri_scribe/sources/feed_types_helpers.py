"""Provide data builders and stand-ins for feed types tests."""

from __future__ import annotations

import tests.conftest


def feed_document(**kwargs: object) -> dict[str, object]:
    """Return the sample feed's configuration document with *kwargs*.

    Args:
        kwargs: Configuration keys to add or replace.

    Returns:
        The feed configuration document.
    """
    return {
        "feed_type": "ArcGISFeed",
        "url": tests.conftest.SAMPLE_FEED_URL,
        "fire_name_column": tests.conftest.SAMPLE_FIRE_NAME_COLUMN,
        "status_column": tests.conftest.SAMPLE_STATUS_COLUMN,
        **kwargs,
    }
