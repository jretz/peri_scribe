"""Isolate fire data tests with explicit fixtures."""

from __future__ import annotations

import collections.abc

import pytest

import peri_scribe.execution


@pytest.fixture
def isolated_added_area_cache() -> collections.abc.Iterator[None]:
    """Keep cache assertions independent of rings processed by other tests.

    Yields:
        An isolated publication execution for compact added-area results.
    """
    with peri_scribe.execution.sharing():
        yield
