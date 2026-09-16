"""Inspect package behavior with shared test utilities."""

from __future__ import annotations

import pathlib

import peri_scribe.sources.snapshots


def record_cache_database_path(path: pathlib.Path) -> pathlib.Path:
    """Return the record cache database for the feed holding *path*.

    Args:
        path: A snapshot path under ``sources/{feed}/...``.

    Returns:
        The feed's record cache database path.
    """
    return peri_scribe.sources.snapshots.record_cache_database_path(path.parent.parent)
