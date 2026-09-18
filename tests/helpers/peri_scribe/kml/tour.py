"""Inspect tour behavior with shared test utilities."""

from __future__ import annotations

import datetime
import typing

import peri_scribe.kml.tour
import tests.helpers.factories.peri_scribe.kml.geometry
import tests.helpers.peri_scribe.kml.parsing


if typing.TYPE_CHECKING:
    import xml.etree.ElementTree as ET


def rendered_tour(times: list[datetime.datetime | None]) -> ET.Element:
    """Expose the emitted playlist so tests check the KML a viewer actually receives.

    Args:
        times: The fire's chronological ring observations.

    Returns:
        The parsed progression tour element.
    """
    writer = tests.helpers.factories.peri_scribe.kml.geometry.MemoryKmlWriter()
    with writer.folder("River") as folder_id:
        peri_scribe.kml.tour.progression_tour(writer, folder_id, times)
    folder = tests.helpers.peri_scribe.kml.parsing.folder_named(
        tests.helpers.peri_scribe.kml.parsing.document_from_writer(writer),
        "River",
    )
    return tests.helpers.peri_scribe.kml.parsing.tour_named(folder, "Progression")
