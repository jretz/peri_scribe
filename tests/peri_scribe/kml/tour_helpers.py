"""Generate chronological observations and parse their serialized progression tours."""

from __future__ import annotations

import datetime
import typing

import hypothesis.strategies

import peri_scribe.kml.geometry
import peri_scribe.kml.tour
import tests.peri_scribe.kml.kml_helpers


if typing.TYPE_CHECKING:
    import xml.etree.ElementTree as ET


@hypothesis.strategies.composite
def ring_times(
    draw: hypothesis.strategies.DrawFn,
) -> list[datetime.datetime | None]:
    """Exercise repeated times, uneven gaps, undated rings, and long-running fires.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        Observation times in chronological order, with undated rings first.
    """
    observations = draw(
        hypothesis.strategies.lists(
            hypothesis.strategies.one_of(
                hypothesis.strategies.none(),
                hypothesis.strategies.integers(0, 365 * 24 * 60 * 60),
            ),
            max_size=20,
        ),
    )
    base = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    return [
        None if seconds is None else base + datetime.timedelta(seconds=seconds)
        for seconds in sorted(
            observations,
            key=lambda value: -1 if value is None else value,
        )
    ]


def rendered_tour(times: list[datetime.datetime | None]) -> ET.Element:
    """Expose the emitted playlist so tests check the KML a viewer actually receives.

    Args:
        times: The fire's chronological ring observations.

    Returns:
        The parsed progression tour element.
    """
    writer = peri_scribe.kml.geometry.KmlWriter()
    with writer.folder("River") as folder_id:
        peri_scribe.kml.tour.progression_tour(writer, folder_id, times)
    folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.document_from_writer(writer),
        "River",
    )
    return tests.peri_scribe.kml.kml_helpers.tour_named(folder, "Progression")
