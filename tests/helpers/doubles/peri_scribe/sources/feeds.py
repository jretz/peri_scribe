"""Replace feeds dependencies with controlled test doubles."""

from __future__ import annotations

import typing

import peri_scribe.sources.feed_types
import peri_scribe.sources.feeds


if typing.TYPE_CHECKING:
    import pytest


def configure_feeds(
    monkeypatch: pytest.MonkeyPatch,
    feeds: list[peri_scribe.sources.feed_types.Feed],
) -> list[peri_scribe.sources.feed_types.Feed]:
    """Point feeds.FEEDS at *feeds* and return them.

    Args:
        monkeypatch: The monkeypatch fixture.
        feeds: The feeds to serve as the configured feeds.

    Returns:
        The configured feeds.
    """
    monkeypatch.setattr(peri_scribe.sources.feeds, "FEEDS", feeds)
    return feeds
