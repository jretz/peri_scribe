"""Report identity prevents polygons and republished attributes from moving metrics."""

from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

import peri_scribe.incidents
import tests.peri_scribe.incidents_helpers


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, {}), ("broken", {}), ("[]", {}), ("{}", {}), ({"a": 1}, {"a": 1})],
)
def test_attributes_dictionary_handles_missing_and_malformed_values(
    value: object,
    expected: dict[str, object],
) -> None:
    assert peri_scribe.incidents.attributes_dictionary(value) == expected


def test_update_from_row_dates_perimeter_attributes_by_incident_time() -> None:
    row = pd.Series({
        "observation_time": tests.peri_scribe.incidents_helpers.time(2),
        "source_attributes": {
            "attr_ModifiedOnDateTime_dt": tests.peri_scribe.incidents_helpers.time(4),
            "attr_EstimatedCostToDate": 44300000,
            "attr_TotalIncidentPersonnel": 526,
        },
    })
    result = peri_scribe.incidents.update_from_row(row, perimeter=True)
    assert result is not None
    assert result.observation_time == tests.peri_scribe.incidents_helpers.time(4)
    assert result.measurements == {"estimated_cost_to_date": 44300000, "personnel": 526}


def test_update_from_row_omits_undated_perimeter_attributes() -> None:
    assert (
        peri_scribe.incidents.update_from_row(
            pd.Series({
                "observation_time": tests.peri_scribe.incidents_helpers.time(2),
                "estimated_cost_to_date": 500,
            }),
            perimeter=True,
        )
        is None
    )


def test_update_from_row_preserves_zero_and_skips_invalid_values() -> None:
    result = peri_scribe.incidents.update_from_row(
        pd.Series({
            "observation_time": tests.peri_scribe.incidents_helpers.time(1),
            "percent_contained": 0,
            "incident_size": -1,
            "estimated_cost_to_date": float("nan"),
        }),
        perimeter=False,
    )
    assert result is not None
    assert result.measurements == {"percent_contained": 0}


def test_reconcile_updates_prefers_direct_report_and_fills_missing_fields() -> None:
    direct = tests.peri_scribe.incidents_helpers.update(1, 100)
    perimeter = dataclasses.replace(
        direct,
        source="wfigs_perimeter",
        serial=100,
        measurements={"incident_size": 99, "personnel": 50},
    )
    result = peri_scribe.incidents.reconcile_updates([direct, perimeter])
    assert {item.source: item.measurements for item in result} == {
        "wfigs_location": {"incident_size": 100},
        "wfigs_perimeter": {"personnel": 50},
    }


def test_reconcile_updates_preserves_confirmation_for_matching_value() -> None:
    perimeter = dataclasses.replace(
        tests.peri_scribe.incidents_helpers.update(1, 100, confirmed=True),
        source="wfigs_perimeter",
    )
    direct = tests.peri_scribe.incidents_helpers.update(1, 100)
    result = peri_scribe.incidents.reconcile_updates([perimeter, direct])
    assert result == (perimeter,)


def test_reconcile_updates_does_not_confirm_a_conflicting_value() -> None:
    perimeter = dataclasses.replace(
        tests.peri_scribe.incidents_helpers.update(1, 100, confirmed=True),
        source="wfigs_perimeter",
        measurements={"incident_size": 100, "personnel": 50},
    )
    direct = tests.peri_scribe.incidents_helpers.update(1, 200)
    result = peri_scribe.incidents.reconcile_updates([perimeter, direct])
    assert {tuple(item.measurements): item.confirmed for item in result} == {
        ("incident_size",): False,
        ("personnel",): True,
    }
    assert peri_scribe.incidents.reconcile_updates(result) == result


def test_reconcile_updates_retains_newest_confirmation_for_matching_value() -> None:
    perimeter = dataclasses.replace(
        tests.peri_scribe.incidents_helpers.update(2, 100, confirmed=True),
        source="wfigs_perimeter",
    )
    direct = dataclasses.replace(
        tests.peri_scribe.incidents_helpers.update(2, 100, confirmed=True),
        report_time=tests.peri_scribe.incidents_helpers.time(1),
    )
    assert peri_scribe.incidents.reconcile_updates([direct, perimeter]) == (perimeter,)


def test_update_from_row_does_not_invent_incident_size_from_perimeter_columns() -> None:
    result = peri_scribe.incidents.update_from_row(
        pd.Series({
            "modified_time": tests.peri_scribe.incidents_helpers.time(1),
            "incident_size": 500,
            "area_acres": 500,
            "percent_contained": 10,
        }),
        perimeter=True,
    )
    assert result is not None
    assert result.measurements == {"percent_contained": 10}


def test_reconcile_updates_ignores_dispatch_reversion_to_pre_report_values() -> None:
    report = tests.peri_scribe.incidents_helpers.update(1, 39073, confirmed=True)
    dispatch = dataclasses.replace(
        tests.peri_scribe.incidents_helpers.update(2, 4000),
        report_time=report.report_time,
    )
    correction = tests.peri_scribe.incidents_helpers.update(3, 39103, confirmed=True)
    result = peri_scribe.incidents.reconcile_updates([dispatch, correction, report])
    assert [item.measurements["incident_size"] for item in result] == [
        39073,
        39073,
        39103,
    ]


def test_reconcile_updates_accepts_newer_reporting_evidence() -> None:
    first = tests.peri_scribe.incidents_helpers.update(1, 100, confirmed=True)
    later = dataclasses.replace(
        tests.peri_scribe.incidents_helpers.update(3, 110),
        report_time=tests.peri_scribe.incidents_helpers.time(2),
    )
    assert peri_scribe.incidents.reconcile_updates([first, later])[-1].measurements[
        "incident_size"
    ] == pytest.approx(110)


def test_reconcile_updates_accepts_dispatch_growth_between_formal_reports() -> None:
    report = tests.peri_scribe.incidents_helpers.update(1, 1200, confirmed=True)
    dispatch = dataclasses.replace(
        tests.peri_scribe.incidents_helpers.update(2, 3171),
        report_time=report.report_time,
    )
    result = peri_scribe.incidents.reconcile_updates([report, dispatch])
    assert result[-1].measurements["incident_size"] == pytest.approx(3171)
    assert not result[-1].confirmed


def test_reconcile_updates_skips_empty_updates() -> None:
    assert (
        peri_scribe.incidents.reconcile_updates([
            dataclasses.replace(
                tests.peri_scribe.incidents_helpers.update(1, 100),
                measurements={},
            ),
        ])
        == ()
    )


def test_history_reads_normalized_records_and_preserves_confirmation() -> None:
    normalized = pd.DataFrame([
        {
            "observation_time": tests.peri_scribe.incidents_helpers.time(1),
            "report_time": tests.peri_scribe.incidents_helpers.time(1),
            "report_confirmed": True,
            "incident_size": 100,
        },
    ])
    result = peri_scribe.incidents.history(pd.DataFrame(), pd.DataFrame(), normalized)
    assert result[0].confirmed
    assert result[0].report_time == tests.peri_scribe.incidents_helpers.time(1)
    assert peri_scribe.incidents.latest_value(result, "incident_size") == pytest.approx(
        100,
    )
    assert peri_scribe.incidents.latest_value(result, "personnel") is None
