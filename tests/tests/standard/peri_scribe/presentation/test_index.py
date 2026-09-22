"""Tests for peri_scribe.presentation.builder."""

from __future__ import annotations

import peri_scribe.presentation.index
import tests.helpers.factories.geography
import tests.helpers.factories.peri_scribe.kml.parsing
import tests.helpers.factories.time


def test_area_qualified_index_includes_independent_incident_history() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "Example",
            "active",
            identifier="example",
        ),
    ])
    empty = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([])
    incidents = tests.helpers.factories.geography.geo_frame(
        {
            "fire_identifier": ["example"],
            "fire_name": ["Example"],
            "observation_time": [tests.helpers.factories.time.utc(2026, 9, 1, 0)],
            "incident_size": [100],
            "report_confirmed": [False],
        },
        [None],
    )
    assert (
        peri_scribe.presentation.index.area_qualified_index(
            index,
            empty,
            empty,
            incidents,
        )
        == index
    )
