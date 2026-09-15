"""Provide data builders and stand-ins for sources tests."""

from __future__ import annotations

import pathlib
import typing

import peri_scribe.exceptions
import peri_scribe.fires.sources
import peri_scribe.models
import tests.factories


CROSSWHITE_ID = "1b0219ee-5298-4fef-9927-c2666d9d53fc"


ROWE_CREEK_COMPLEX_ID = "b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3"


def listed_fires(
    directory: pathlib.Path = pathlib.Path("sources"),
) -> list[peri_scribe.models.Fire]:
    """Return the fires indexed from the GeoPackage files under *directory*.

    Args:
        directory: The directory tree holding GeoPackage files with fire data. Defaults
            to the canonical ``sources`` directory.

    Returns:
        The fires, in the order first encountered.
    """
    record_groups = peri_scribe.fires.sources.fire_record_groups(directory)
    return [
        source.fire
        for source in peri_scribe.fires.sources.fire_sources_from_groups(record_groups)
    ]


def complex_parent_and_child_fires(
    stub_fire_reader: tests.factories.StubFireReader,
) -> list[peri_scribe.models.Fire]:
    """Return fires indexed from the canonical parent/child GeoPackage.

    Args:
        stub_fire_reader: The fixture installing in-memory fire reads.

    Returns:
        The parent and child fires, with the child linked to its complex.
    """
    stub_fire_reader(
        {
            pathlib.Path("one.gpkg"): [
                tests.factories.fire_record(
                    "ROWE CREEK COMPLEX",
                    tests.factories.ACTIVE,
                    identifiers={ROWE_CREEK_COMPLEX_ID},
                ),
                tests.factories.fire_record(
                    "0445 CROSSWHITE",
                    tests.factories.ACTIVE,
                    identifiers={CROSSWHITE_ID},
                ),
            ],
        },
        {
            pathlib.Path("one.gpkg"): [
                peri_scribe.models.ComplexMembership(
                    fire_identifier=CROSSWHITE_ID,
                    complex_identifier=ROWE_CREEK_COMPLEX_ID,
                    complex_name="ROWE CREEK COMPLEX",
                ),
            ],
        },
    )
    return listed_fires()


def raise_unknown_layer(_path: pathlib.Path) -> typing.Never:
    """Simulate a snapshot containing an unconfigured layer.

    Args:
        _path: File path accepted for compatibility; the configured stub outcome is
            used.

    Raises:
        peri_scribe.exceptions.UnknownLayerError: Always, for the synthetic unknown
            layer.
    """
    layer_name = "Mystery_Layer_0"
    raise peri_scribe.exceptions.UnknownLayerError(
        layer_name,
        pathlib.Path("fires.gpkg"),
    )


def raise_missing_snapshot(_path: pathlib.Path) -> typing.Never:
    """Simulate a snapshot disappearing before it can be read.

    Args:
        _path: File path accepted for compatibility; the configured stub outcome is
            used.

    Raises:
        FileNotFoundError: Always, to exercise unreadable-source handling.
    """
    message = "no such file"
    raise FileNotFoundError(message)
