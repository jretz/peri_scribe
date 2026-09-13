"""Area provenance identifies the supporting observation instead of the policy clock."""

from __future__ import annotations

import pytest

import peri_scribe.kml.text
import tests.factories
from peri_scribe.units import units


@pytest.mark.parametrize(
    ("report", "expected_area", "expected_basis"),
    [(False, 100, "Mapped; 08/31 17:00 PDT"), (True, 200, "Reported; 09/02 17:00 PDT")],
)
def test_selected_area_description_dates_the_supporting_evidence(
    *,
    report: bool,
    expected_area: float,
    expected_basis: str,
) -> None:
    days = (1, 5) if report else (1,)
    shape = tests.factories.square(0.01)
    perimeters = tests.factories.geo_frame(
        {
            "observation_time": [tests.factories.utc(2026, 9, day, 0) for day in days],
            "geometry_area_square_meters": [(100 * units.acres).m_as("meters**2")]
            * len(days),
        },
        [shape] * len(days),
    )
    incidents = (
        tests.factories.geo_frame(
            {
                "observation_time": [tests.factories.utc(2026, 9, 3, 0)],
                "report_confirmed": [False],
                "incident_size": [200],
            },
            [None],
        )
        if report
        else None
    )
    area, basis = peri_scribe.kml.text.selected_area_description(
        perimeters,
        perimeters.iloc[0:0],
        incidents,
    )
    assert area == expected_area * units.acres
    assert basis == expected_basis
