"""Publish a prepared KMZ and advance the year's durable update state.

Design notes:
[Update journal](../../../docs/algorithms/update-journal.md).
"""

from __future__ import annotations

import collections.abc
import contextlib
import pathlib
import typing

import kml_io.kmz
import peri_scribe.fire_updates
import peri_scribe.publication


def publish(
    year_directory: pathlib.Path,
    output_path: pathlib.Path,
    *,
    write_document: collections.abc.Callable[
        [],
        collections.abc.Callable[[typing.TextIO], object],
    ],
    images: collections.abc.Mapping[str, bytes],
    checkpoint: tuple[
        peri_scribe.publication.Collection,
        dict[str, peri_scribe.publication.PublishedFire],
    ]
    | None,
    prepare: collections.abc.Callable[
        [peri_scribe.fire_updates.State],
        peri_scribe.fire_updates.PreparedUpdates,
    ],
    write_viewer: collections.abc.Callable[[pathlib.Path], None],
    archive_phase: collections.abc.Callable[
        [],
        contextlib.AbstractContextManager[None],
    ],
) -> pathlib.Path:
    """Recover the previous update before making the next publication durable.

    Args:
        year_directory: The year directory holding the archive and its durable state.
        output_path: The public KMZ path.
        write_document: Supply the stream renderer within the archive phase.
        images: Archive member names and their contents, in publication order.
        checkpoint: Source inventory and published fires for a fresh collection.
        prepare: Build the update batch against the recovered mapping checkpoint.
        write_viewer: Publish the viewer for the acknowledged update history.
        archive_phase: Manage the rendering phase around the actual archive write.

    Returns:
        The published KMZ path.
    """
    previous = peri_scribe.fire_updates.previous_state_for_preparation(year_directory)
    prepared = prepare(previous)
    with archive_phase():
        kml_io.kmz.write_kmz(output_path, write_document(), images)
    if checkpoint is not None:
        collection, fires = checkpoint
        peri_scribe.publication.commit(year_directory, output_path, collection, fires)
    peri_scribe.fire_updates.write_updates(year_directory, prepared)
    write_viewer(year_directory)
    return output_path
