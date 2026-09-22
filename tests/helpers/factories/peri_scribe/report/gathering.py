"""Build inputs for gathering tests."""

from __future__ import annotations

import datetime

import shapely.geometry

import peri_scribe.models
import peri_scribe.presentation.descriptions
import peri_scribe.presentation.fire_data
import peri_scribe.presentation.perimeters
import peri_scribe.report.gathering
from measurement_units import units


def make_fire(
    name: str,
    identifier: str,
) -> peri_scribe.presentation.fire_data.FireSummary:
    """Return a described fire with the given name and identifier.

    Args:
        name: The fire's name.
        identifier: The fire's identifier.

    Returns:
        An active fire with a description carrying fixed area, containment, and
        discovery facts.
    """
    return peri_scribe.presentation.fire_data.FireSummary(
        name=name,
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=None,
        perimeters=(),
        identifiers=frozenset({identifier}),
        description=peri_scribe.presentation.descriptions.FireDescription(
            identifier=identifier,
            area=100.0 * units.acres,
            percent_contained=50.0,
            discovery_time=datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC),
        ),
    )


def make_entry(
    name: str,
    *,
    identifier: str | None = None,
) -> peri_scribe.report.gathering.FireReportEntry:
    """Return a report entry carrying only the given identity facts.

    Args:
        name: The fire's name.
        identifier: The fire's identifier, or None.

    Returns:
        An active fire entry with no other facts set.
    """
    return peri_scribe.report.gathering.FireReportEntry(
        name=name,
        identifier=identifier,
        status=peri_scribe.models.FireStatus.ACTIVE,
    )


def located_fire(
    name: str,
    identifier: str,
) -> peri_scribe.presentation.fire_data.FireSummary:
    """Return an active fire with one mapped perimeter.

    Args:
        name: The fire's name.
        identifier: The fire's identifier.

    Returns:
        A fire whose latest perimeter is a non-empty polygon, so its location can be
        measured from an interior.
    """
    return peri_scribe.presentation.fire_data.FireSummary(
        name=name,
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=None,
        perimeters=(
            peri_scribe.presentation.perimeters.Perimeter(
                geometry=shapely.geometry.Point(-122.675, 45.5051).buffer(0.1),
                observation_time=None,
            ),
        ),
        identifiers=frozenset({identifier}),
    )
