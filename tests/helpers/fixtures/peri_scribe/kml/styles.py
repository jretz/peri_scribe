"""Isolate styles tests with explicit fixtures."""

from __future__ import annotations

import pytest

import peri_scribe.kml.styles


@pytest.fixture
def style_urls() -> dict[str, str]:
    """Provide production placemark styles for folder assertions.

    Returns:
        The placemark style URLs keyed by style name.
    """
    return peri_scribe.kml.styles.PLACEMARK_STYLE_URLS
