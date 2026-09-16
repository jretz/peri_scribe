"""Provide data builders and stand-ins for descriptions tests."""

from __future__ import annotations

import datetime

import hypothesis.strategies

import peri_scribe.kml.descriptions
from peri_scribe.units import units


def balloon_text() -> hypothesis.strategies.SearchStrategy[str]:
    """Exercise both markup escaping layers with XML-compatible display text.

    Returns:
        Unicode text including HTML punctuation, entity spellings, and CDATA endings.
    """
    return hypothesis.strategies.one_of(
        hypothesis.strategies.text(
            alphabet=hypothesis.strategies.characters(
                exclude_categories=("Cc", "Cs"),
                exclude_characters=("\ufffe", "\uffff"),
            ),
            max_size=40,
        ),
        hypothesis.strategies.sampled_from([
            "]]>",
            "&amp;",
            '<b title="quoted">text</b>',
            "O'Brien & Sons",
        ]),
    )


def full_description() -> peri_scribe.kml.descriptions.FireDescription:
    """Return a fire description with every field populated.

    Returns:
        The description.
    """
    return peri_scribe.kml.descriptions.FireDescription(
        identifier="2026-cabug-000001",
        source="FIRIS / NIFC",
        mission="CA-BUG-000001",
        area=102003.46 * units.acres,
        exterior_perimeter=33.1 * units.miles,
        percent_contained=77.0,
        estimated_cost_to_date=104_600_000.0 * units.dollars,
        estimated_final_cost=120_000_000.0 * units.dollars,
        total_personnel=1_234.0,
        protecting_unit="CALMU",
        discovery_time=datetime.datetime(2026, 6, 29, 12, 4, 46, tzinfo=datetime.UTC),
        observation_time=datetime.datetime(2026, 8, 2, 5, 30, tzinfo=datetime.UTC),
        initial_response_time=datetime.datetime(
            2026,
            7,
            27,
            19,
            24,
            tzinfo=datetime.UTC,
        ),
        incident_type="Wildfire",
        incident_complexity="Type 3 Incident; Type 4 Incident; Type 3 Team",
        fuel_model="Timber (Litter and Understory); Brush (2 feet); GS1; Grass",
        fire_behavior="Active; Creeping; Smoldering",
        landowner_category="Federal",
        of_note="Over 100,000 acres, and a Type 1 Incident.",
    )
