"""Authenticate complete source generations before loading fire observations."""

from __future__ import annotations

import collections.abc
import pathlib

import peri_scribe.execution
import peri_scribe.fires.reuse
import peri_scribe.fires.sources
import peri_scribe.sources.snapshots


def source_key(year_directory: pathlib.Path) -> str:
    """Include every ordered source byte and geography dependency in a generation.

    Args:
        year_directory: The publication year whose authoritative inputs are examined.

    Returns:
        An exact source generation, shared only within its owning execution.
    """
    directory = peri_scribe.sources.snapshots.sources_directory_path(year_directory)
    paths = peri_scribe.sources.snapshots.geo_package_files(directory)
    context = peri_scribe.fires.reuse.derivation_context(year_directory)
    stamps = tuple(
        (path, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)
        for path in paths
        for stat in (path.stat(),)
    )
    key = ("source_generation", directory.resolve(), context, stamps)
    cached = peri_scribe.execution.get(peri_scribe.execution.Group.SOURCES, key)
    if isinstance(cached, str):
        return cached
    result = peri_scribe.fires.reuse.data_digest({
        "context": context,
        "sources": [
            (
                str(path.relative_to(directory)),
                peri_scribe.fires.reuse.file_digest(path),
            )
            for path in paths
        ],
    })
    peri_scribe.execution.put(peri_scribe.execution.Group.SOURCES, key, result)
    return result


def classifications_complete(
    groups: peri_scribe.fires.sources.FireRecordGroups,
    classifications: collections.abc.Collection[int],
) -> bool:
    """Keep unavailable boundary classification eligible for a future retry.

    Args:
        groups: All grouped source evidence, including complex membership.
        classifications: Successfully classified fire identities.

    Returns:
        Whether every non-complex fire has a completed classification.
    """
    expected = {
        id(source.fire)
        for source, _group in peri_scribe.fires.sources.non_complex_fire_sources(groups)
    }
    return expected.issubset(classifications)
