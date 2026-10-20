"""Isolate every process-local dart cache when testing reuse and eviction."""

import collections.abc
import contextlib

import peri_scribe.presentation.preview_geometry


def clear_dart_caches() -> None:
    """Keep angle, raster, and coarse-grid cache observations independent."""
    peri_scribe.presentation.preview_geometry.coarse_dart_hulls.cache_clear()
    peri_scribe.presentation.preview_geometry.north_dart_hull.cache_clear()
    peri_scribe.presentation.preview_geometry.dart_hull_from_state.cache_clear()


@contextlib.contextmanager
def isolated_dart_caches() -> collections.abc.Generator[None]:
    """Restore empty caches even when a test replaces one of their implementations.

    Yields:
        Control with all dart caches initially empty.
    """
    clear_dart_caches()
    try:
        yield
    finally:
        clear_dart_caches()
