"""Time newly available source polygons through the first consuming KMZ run."""

from __future__ import annotations

import datetime
import pathlib
import typing

import peri_scribe.show_latencies.runs
import peri_scribe.show_latencies.sources
from measurement_units import units


if typing.TYPE_CHECKING:
    import pint


def latencies(
    year_directory: pathlib.Path,
    evidence: peri_scribe.show_latencies.runs.Evidence,
    window: peri_scribe.show_latencies.runs.Window,
) -> tuple[pint.Quantity, ...]:
    """Include source polygon updates independently of shape or publication filters.

    Args:
        year_directory: Retained source snapshots and the fire identity index.
        evidence: Successful KMZ writes, command endpoints when known, and input times.
        window: Inclusive source-publication and command bounds.

    Returns:
        One duration per fire and consuming KMZ run, from its earliest new polygon.
    """
    writes = sorted(
        (write for write in evidence.kmz_writes if write.geography is not None),
        key=lambda write: write.written,
    )
    if not writes:
        return ()
    publications: dict[tuple[int, str], datetime.datetime] = {}
    for publication in peri_scribe.show_latencies.sources.read_versions(
        year_directory,
        window,
    ):
        collected = evidence.snapshots.get(publication.source_file)
        if collected is None:
            continue
        for index, write in enumerate(writes):
            if collected <= typing.cast("datetime.datetime", write.geography) and (
                write.finished is None or publication.published <= write.finished
            ):
                key = (index, publication.identifier)
                publications[key] = min(
                    publications.get(key, publication.published),
                    publication.published,
                )
                break
    return tuple(
        (finished - published).total_seconds() * units.seconds
        for (index, _identifier), published in sorted(publications.items())
        if (finished := writes[index].finished) is not None
    )
