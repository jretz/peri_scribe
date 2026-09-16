"""Inspect reuse behavior with shared test utilities."""

import pathlib

import peri_scribe.fires.reuse
import peri_scribe.fires.sources


def source_key(
    read: peri_scribe.fires.sources.ReadFireSources,
    context: str = "context",
) -> str:
    """Extract the first fire's reuse key for dependency invalidation assertions.

    Args:
        read: Source observations and provenance used to compute a reuse key.
        context: Derivation settings signature included in the reuse key.

    Returns:
        The first grouped fire's dependency key.
    """
    groups = peri_scribe.fires.sources.group_fire_sources(read)
    return next(
        iter(
            peri_scribe.fires.reuse.fire_keys(
                read,
                groups,
                pathlib.Path("sources"),
                context,
            ).values(),
        ),
    )
