"""Area selection follows mapping freshness and actual reporting evidence."""

from __future__ import annotations

import dataclasses
import datetime
import json
import math
import typing

import pandas as pd
import pytest
import shapely

import peri_scribe.areas
import peri_scribe.incidents
import tests.factories
from peri_scribe.units import units


if typing.TYPE_CHECKING:
    import geopandas
    import pint


def acres(value: pint.Quantity[float] | None) -> float | None:
    """Keep acreage assertions independent of a quantity's internal unit.

    Args:
        value: The selected area, including a possible missing result.

    Returns:
        The area in acres, or None when the measurement is absent.
    """
    return None if value is None else value.m_as("acres")


def time(days: float) -> datetime.datetime:
    """Give policy tests a shared clock with support for intraday deadlines.

    Args:
        days: Elapsed days from midnight UTC on September 1, 2026.

    Returns:
        The corresponding timezone-aware observation time.
    """
    return tests.factories.utc(2026, 9, 1, 0) + datetime.timedelta(days=days)


def mappings(entries: list[tuple[float, float]]) -> geopandas.GeoDataFrame:
    """Isolate area policy with explicit measurements and comparable footprints.

    Args:
        entries: Observation day offsets paired with stored acreage measurements.

    Returns:
        Synthetic perimeter rows whose stored areas support exact threshold checks and
        whose changing square footprints support survey-freshness checks.
    """
    return tests.factories.geo_frame(
        {
            "observation_time": [time(day) for day, _area in entries],
            "geometry_area_square_meters": [
                (area * units.acres).m_as("meters**2") for _day, area in entries
            ],
        },
        [
            shapely.box(
                -120,
                35,
                -120 + math.sqrt(area) / 1000,
                35 + math.sqrt(area) / 1000,
            )
            for _day, area in entries
        ],
    )


def reports(
    entries: list[tuple[float, float]],
    *,
    confirmed: bool = False,
) -> pd.DataFrame:
    """Make formal-report confirmation explicit in area-selection scenarios.

    Args:
        entries: Observation day offsets paired with reported acreage.
        confirmed: Whether each observation carries a distinct formal report time.

    Returns:
        Incident rows with serialized dispatch or ICS-209 source metadata.
    """
    return pd.DataFrame([
        {
            "observation_time": time(day),
            "incident_size": area,
            "source_attributes": json.dumps({
                "ModifiedBySystem": "ics209" if confirmed else "dispatch",
                "ICS209ReportDateTime": time(day).isoformat() if confirmed else None,
            }),
        }
        for day, area in entries
    ])


def test_area_history_prefers_recent_geometry_over_conflicting_reports() -> None:
    history = peri_scribe.areas.area_history(
        mappings([(0, 1000)]),
        reports([(1, 1200), (2, 900)]),
    )
    assert all(acres(item.area) == pytest.approx(1000) for item in history)
    assert all(item.source is peri_scribe.areas.AreaSource.MAPPED for item in history)


def test_area_history_uses_reports_without_mapping() -> None:
    history = peri_scribe.areas.area_history(mappings([]), reports([(0, 25), (1, 50)]))
    assert [item.area.m_as("acres") for item in history] == [25, 50]
    assert history[-1].source is peri_scribe.areas.AreaSource.REPORTED


def test_area_history_switches_for_significant_growth_after_stale_deadline() -> None:
    history = peri_scribe.areas.area_history(
        mappings([(0, 1000)]),
        reports([(2, 1500), (4, 1500)]),
    )
    assert acres(
        next(item for item in history if item.time == time(3)).area,
    ) == pytest.approx(1500)
    assert history[-1].observation_time == time(4)


@pytest.mark.parametrize("area", [1005, 1249])
def test_area_history_keeps_old_mapping_without_significant_growth(area: float) -> None:
    assert acres(
        peri_scribe.areas.latest_area(mappings([(0, 1000)]), reports([(5, area)])),
    ) == pytest.approx(1000)


def test_area_history_requires_absolute_increase_for_small_fire() -> None:
    assert acres(
        peri_scribe.areas.latest_area(mappings([(0, 10)]), reports([(5, 15)])),
    ) == pytest.approx(10)


def test_area_history_requires_growth_since_mapping() -> None:
    assert acres(
        peri_scribe.areas.latest_area(
            mappings([(1, 1000)]),
            reports([(0, 2000), (5, 2000)]),
        ),
    ) == pytest.approx(1000)


def test_area_history_uses_dispatch_growth_while_a_formal_report_is_unchanged() -> None:
    points = reports([(4, 1200), (5, 3171)], confirmed=True)
    points.loc[1, "source_attributes"] = json.dumps({
        "ModifiedBySystem": "wildcade",
        "ICS209ReportDateTime": time(4).isoformat(),
    })
    history = peri_scribe.areas.area_history(mappings([(0, 1163)]), points)
    assert history[-1].source is peri_scribe.areas.AreaSource.REPORTED
    assert acres(history[-1].area) == pytest.approx(3171)


def test_area_history_accepts_two_fresh_reports_for_rapid_growth() -> None:
    history = peri_scribe.areas.area_history(
        mappings([(0, 400)]),
        reports([(1, 900), (2, 1300)], confirmed=True),
    )
    assert acres(history[-1].area) == pytest.approx(1300)
    assert history[-1].source is peri_scribe.areas.AreaSource.REPORTED


def test_area_history_requires_distinct_confirmations_for_rapid_growth() -> None:
    points = reports([(1, 900), (2, 1300)], confirmed=True)
    points.loc[1, "source_attributes"] = points.loc[0, "source_attributes"]
    assert acres(
        peri_scribe.areas.latest_area(mappings([(0, 400)]), points),
    ) == pytest.approx(400)


def test_area_history_does_not_refresh_mapping_for_negligible_geometry_edit() -> None:
    history = peri_scribe.areas.area_history(
        mappings([(0, 17), (5, 17.001)]),
        reports([(4, 500)]),
    )
    assert acres(history[-1].area) == pytest.approx(500)
    assert history[-1].source is peri_scribe.areas.AreaSource.REPORTED


def test_area_history_resumes_geometry_when_mapping_catches_up() -> None:
    history = peri_scribe.areas.area_history(
        mappings([(0, 17), (6, 575)]),
        reports([(4, 500)]),
    )
    assert acres(history[-1].area) == pytest.approx(575)
    assert history[-1].source is peri_scribe.areas.AreaSource.MAPPED


def test_area_history_accepts_new_survey_of_unchanged_boundary() -> None:
    perimeters = mappings([(0, 1000), (5, 1000)])
    perimeters["source_subsource"] = ["FIRIS", "CAL FIRE INTEL FLIGHT DATA"]
    history = peri_scribe.areas.area_history(perimeters, reports([(4, 2000)]))
    assert acres(history[-1].area) == pytest.approx(1000)


def test_area_history_uses_independent_incident_history() -> None:
    incident_rows = reports([(5, 1500)])
    assert acres(
        peri_scribe.areas.latest_area(
            mappings([(0, 1000)]),
            reports([]),
            incident_rows,
        ),
    ) == pytest.approx(1500)


def test_area_history_preserves_downward_mapping_corrections() -> None:
    assert acres(
        peri_scribe.areas.latest_area(mappings([(0, 1000), (5, 700)]), reports([])),
    ) == pytest.approx(700)


def test_area_history_ignores_empty_and_undated_geometry() -> None:
    perimeters = mappings([(0, 1000), (1, 1100)])
    perimeters.loc[0, "geometry"] = shapely.Polygon()
    perimeters.loc[1, "observation_time"] = None
    assert peri_scribe.areas.area_history(perimeters, reports([])) == ()


def test_area_history_supports_configured_staleness() -> None:
    policy = dataclasses.replace(
        peri_scribe.areas.DEFAULT_POLICY,
        stale_after=datetime.timedelta(days=6),
    )
    history = peri_scribe.areas.area_history(
        mappings([(0, 1000)]),
        reports([(5, 1500)]),
        policy=policy,
    )
    assert acres(history[-1].area) == pytest.approx(1000)


@pytest.mark.parametrize(
    "capture",
    [None, "1970-01-01T00:00:01Z", "2026-09-07T00:00:00Z", "2026-08-01T00:00:00Z"],
)
def test_new_survey_rejects_unusable_capture_dates(capture: str | None) -> None:
    row = pd.Series({
        "observation_time": time(5),
        "source_attributes": {"poly_PolygonDateTime": capture},
    })
    assert not peri_scribe.areas.new_survey(row, time(0))


def test_new_survey_accepts_advanced_capture_date() -> None:
    row = pd.Series({
        "observation_time": time(5),
        "source_attributes": {"poly_PolygonDateTime": time(4)},
    })
    assert peri_scribe.areas.new_survey(row, time(0))
    assert peri_scribe.areas.new_survey(row, None)


def test_accepted_reports_rejects_uncorroborated_large_decrease() -> None:
    updates = peri_scribe.incidents.history(
        mappings([]),
        reports([(0, 39000), (1, 4000)]),
    )
    accepted = peri_scribe.areas.accepted_reports(
        updates,
        peri_scribe.areas.DEFAULT_POLICY,
    )
    assert [item.measurements["incident_size"] for item in accepted] == [39000]


def test_accepted_reports_allows_explicit_report_correction() -> None:
    updates = peri_scribe.incidents.history(
        mappings([]),
        reports([(0, 1000), (1, 700)], confirmed=True),
    )
    assert (
        peri_scribe.areas.accepted_reports(updates, peri_scribe.areas.DEFAULT_POLICY)
        == updates
    )


def test_latest_area_uses_undated_geometry() -> None:
    perimeters = mappings([(0, 1000)])
    perimeters["observation_time"] = None
    assert acres(
        peri_scribe.areas.latest_area(perimeters, reports([])),
    ) == pytest.approx(1000)


def test_latest_area_uses_undated_report_without_mapping() -> None:
    assert acres(
        peri_scribe.areas.latest_area(
            mappings([]),
            pd.DataFrame({"incident_size": [500]}),
        ),
    ) == pytest.approx(500)


def test_latest_area_uses_supplied_polygon_acreage_without_geometry() -> None:
    assert acres(
        peri_scribe.areas.latest_area(pd.DataFrame({"area_acres": [30]}), reports([])),
    ) == pytest.approx(30)


def test_latest_area_returns_none_without_measurements() -> None:
    assert (
        peri_scribe.areas.latest_area(
            pd.DataFrame({"geometry": [None]}),
            pd.DataFrame({"incident_size": [None]}),
        )
        is None
    )


def test_row_area_skips_zero_measurement() -> None:
    row = mappings([(0, 1)]).iloc[0].copy()
    row["geometry_area_square_meters"] = 0
    assert peri_scribe.areas.row_area(row) is None


@pytest.mark.parametrize(
    ("reported", "calculated", "expected"),
    [(100, 90, 90), (None, 90, 90), (100, None, 100), (None, None, None)],
)
def test_presented_area_uses_geometry_for_growth(
    reported: float | None,
    calculated: float | None,
    expected: float | None,
) -> None:
    result = peri_scribe.areas.presented_area(
        None if reported is None else reported * units.acres,
        None if calculated is None else calculated * units.acres,
    )
    assert result == (None if expected is None else expected * units.acres)


def test_historical_area_keeps_earlier_size_after_mapping_correction() -> None:
    assert acres(
        peri_scribe.areas.historical_area(mappings([(0, 100), (4, 10)]), reports([])),
    ) == pytest.approx(100)


def test_historical_area_rejects_report_conflicting_with_fresh_mapping() -> None:
    assert acres(
        peri_scribe.areas.historical_area(mappings([(0, 10)]), reports([(1, 100)])),
    ) == pytest.approx(10)


def test_historical_area_prefers_undated_geometry_to_supplied_acreage() -> None:
    perimeters = mappings([(0, 30)])
    perimeters["observation_time"] = None
    perimeters["area_acres"] = 1000
    assert acres(
        peri_scribe.areas.historical_area(perimeters, reports([])),
    ) == pytest.approx(30)


def test_historical_area_uses_sparse_reported_measurements() -> None:
    assert acres(
        peri_scribe.areas.historical_area(
            pd.DataFrame([{"area_acres": 10}, {"area_acres": None}]),
            pd.DataFrame([{"discovery_acres": 25, "final_acres": -1}]),
            pd.DataFrame([{"incident_size": 20}]),
        ),
    ) == pytest.approx(25)


def test_historical_area_returns_none_without_usable_measurements() -> None:
    assert peri_scribe.areas.historical_area(pd.DataFrame(), pd.DataFrame()) is None
