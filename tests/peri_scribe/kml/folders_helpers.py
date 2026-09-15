"""Provide data builders and stand-ins for folders tests."""

from __future__ import annotations

import datetime

import peri_scribe.kml.builder
import peri_scribe.kml.descriptions
import peri_scribe.kml.fire_data
import peri_scribe.kml.perimeters
import peri_scribe.models
import tests.factories


def ring_style_urls_for(fire: peri_scribe.kml.fire_data.FireGeometry) -> dict[str, str]:
    """Return a ring style URL for every color *fire*'s rings use.

    The mapping mirrors the builder's, so the fire's rings resolve to the styles the KMZ
    document defines.

    Args:
        fire: The fire to symbolize.

    Returns:
        The ring style URLs.
    """
    return peri_scribe.kml.builder.ring_style_urls_for([fire])


def score_entry(
    name: str,
    identifier: str | None,
    score: int,
    explanation: str,
    *,
    area: float | None = None,
    building_count: int | None = None,
    evacuation_overlap: bool | None = None,
) -> peri_scribe.models.FireScoreEntry:
    """Return a saved score for a fire.

    Args:
        name: The fire's name.
        identifier: The fire's identifier, or None.
        score: The fire's score.
        explanation: Why the fire has the score.
        area: The fire's presented area in acres, or None.
        building_count: The buildings within a mile, or None.
        evacuation_overlap: Whether the fire overlaps an evacuation zone.

    Returns:
        The score entry.
    """
    return peri_scribe.models.FireScoreEntry(
        name=name,
        identifier=identifier,
        score=score,
        explanation=explanation,
        area=area,
        building_count=building_count,
        evacuation_overlap=evacuation_overlap,
    )


REFERENCE_TIME = datetime.datetime(2026, 8, 20, 12, 0, tzinfo=datetime.UTC)


def active_fire(
    name: str,
    *,
    description: peri_scribe.kml.descriptions.FireDescription | None = None,
    perimeters: tuple[peri_scribe.kml.perimeters.Perimeter, ...] = (),
    identifiers: frozenset[str] = frozenset(),
) -> peri_scribe.kml.fire_data.FireGeometry:
    """Return an active fire with the given description and perimeters.

    Args:
        name: The fire's name.
        description: The fire's latest state, or None.
        perimeters: The fire's perimeters, oldest first.
        identifiers: The fire's identifiers.

    Returns:
        The active fire.
    """
    return peri_scribe.kml.fire_data.FireGeometry(
        name=name,
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=None,
        perimeters=perimeters,
        description=description,
        identifiers=identifiers,
    )


def growing_fire(
    name: str,
    baseline_side: float,
    latest_side: float,
    reference_time: datetime.datetime,
) -> peri_scribe.kml.fire_data.FireGeometry:
    """Return an active fire growing from *baseline_side* to *latest_side*.

    The baseline perimeter sits at the start of the 48-hour window and the latest one at
    *reference_time*, so the fire's growth over the window is measurable.

    Args:
        name: The fire's name.
        baseline_side: The side length of the baseline square.
        latest_side: The side length of the latest square.
        reference_time: The time the snapshot is as of.

    Returns:
        The growing fire.
    """
    return active_fire(
        name,
        perimeters=(
            peri_scribe.kml.perimeters.Perimeter(
                geometry=tests.factories.square(baseline_side),
                observation_time=reference_time - datetime.timedelta(hours=48),
            ),
            peri_scribe.kml.perimeters.Perimeter(
                geometry=tests.factories.square(latest_side),
                observation_time=reference_time,
            ),
        ),
    )


def type_one_fire(
    name: str,
    *,
    active: bool = True,
) -> peri_scribe.kml.fire_data.FireGeometry:
    """Return a fire carrying the given name and Type 1 marker.

    Args:
        name: The fire's name.
        active: Whether the fire is active.

    Returns:
        The fire.
    """
    return peri_scribe.kml.fire_data.FireGeometry(
        name=name,
        status=(
            peri_scribe.models.FireStatus.ACTIVE
            if active
            else peri_scribe.models.FireStatus.INACTIVE
        ),
        point=None,
        perimeters=(),
        type_one=True,
    )


def balloon_text(
    description: peri_scribe.kml.descriptions.FireDescription,
    image_filenames: tuple[str, ...] = (),
    leading_rows: tuple[tuple[str, str | None], ...] = (),
) -> str:
    """Return *description*'s balloon as the KML parser reads it.

    Args:
        description: The fire description to render.
        image_filenames: The plot image filenames to show below the table.
        leading_rows: The rows to lead the table with.

    Returns:
        The balloon's CDATA content, without the section markers the parser strips.
    """
    html = peri_scribe.kml.descriptions.description_html(
        description,
        image_filenames,
        leading_rows=leading_rows,
    )
    return html[len("<![CDATA[") : -len("]]>")]
