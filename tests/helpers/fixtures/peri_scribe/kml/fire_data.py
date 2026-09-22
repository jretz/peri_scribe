"""Isolate fire data tests with explicit fixtures."""

from __future__ import annotations

import functools

import pytest

import peri_scribe.kml.fire_data


@pytest.fixture
def isolated_added_area_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep cache assertions independent of rings processed by other tests.

    Args:
        monkeypatch: Replace dependencies and restore them after the test.
    """
    monkeypatch.setattr(
        peri_scribe.kml.fire_data,
        "added_areas_for_rings",
        functools.cache(peri_scribe.kml.fire_data.added_areas_for_rings.__wrapped__),
    )
