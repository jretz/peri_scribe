"""Whole histories agree across source parsing, field ledgers, and SQLite geography."""

from __future__ import annotations

import pathlib

import pandas as pd

import peri_scribe.fires.derived_layers
import peri_scribe.fires.history
import peri_scribe.fires.incident_history
import peri_scribe.fires.sources
import peri_scribe.incidents
import spatial_data.layers
import tests.formal.helpers.incident_histories
import tests.formal.helpers.oracle


def test_reconcile_updates_matches_lean_complete_sparse_histories() -> None:
    cases = tests.formal.helpers.incident_histories.cases()
    expected = tests.formal.helpers.oracle.evaluate(
        [tests.formal.helpers.incident_histories.command(case) for case in cases],
        executable="oracleIncident",
    )
    expected_count = 1301
    assert len(cases) == expected_count
    for case, result in zip(cases, expected, strict=True):
        actual = peri_scribe.incidents.reconcile_updates(case)
        tests.formal.helpers.incident_histories.assert_provenance(case, actual)
        assert tests.formal.helpers.incident_histories.projection(actual) == result, (
            case
        )
        assert [item.observation_time for item in actual] == sorted(
            item.observation_time for item in actual
        )
        assert peri_scribe.incidents.reconcile_updates(actual) == actual


def test_latest_value_matches_lean_complete_field_histories() -> None:
    cases = tests.formal.helpers.incident_histories.cases()
    expected = tests.formal.helpers.oracle.evaluate(
        [tests.formal.helpers.incident_histories.command(case) for case in cases],
        executable="oracleIncident",
    )
    for case, result in zip(cases, expected, strict=True):
        actual = peri_scribe.incidents.reconcile_updates(case)
        vectors = [result[index : index + 8] for index in range(0, len(result), 8)]
        for field, column in enumerate(peri_scribe.incidents.VALUE_COLUMNS):
            expected_value = next(
                (vector[7] for vector in reversed(vectors) if vector[6] == field),
                None,
            )
            assert peri_scribe.incidents.latest_value(actual, column) == expected_value


def test_incident_layer_rows_matches_lean_through_storage_and_polygon_removal(
    tmp_path: pathlib.Path,
) -> None:
    cases = tests.formal.helpers.incident_histories.cases()[1001::15]
    prepared = [
        tests.formal.helpers.incident_histories.source_history(case, tmp_path)
        for case in cases
    ]
    expected = tests.formal.helpers.oracle.evaluate(
        [
            tests.formal.helpers.incident_histories.command(normalized)
            for _, normalized in prepared
        ],
        executable="oracleIncident",
    )
    expected_count = 20
    assert len(prepared) == expected_count
    for index, ((read, normalized), result) in enumerate(
        zip(prepared, expected, strict=True),
    ):
        groups = peri_scribe.fires.sources.group_fire_sources(read)
        rows = peri_scribe.fires.incident_history.incident_layer_rows(
            read,
            groups,
            tmp_path,
        )
        path = tmp_path / f"incident-{index}.gpkg"
        spatial_data.layers.write_geopackage(
            path,
            [
                spatial_data.layers.LayerData(
                    name=peri_scribe.incidents.LAYER_NAME,
                    dataframe=peri_scribe.fires.history.build_dataframe(
                        rows,
                        peri_scribe.fires.incident_history.COLUMNS,
                    ),
                ),
            ],
        )
        frame = peri_scribe.fires.derived_layers.read_incident_layer(path)
        actual = peri_scribe.incidents.history(pd.DataFrame(), pd.DataFrame(), frame)
        tests.formal.helpers.incident_histories.assert_provenance(normalized, actual)
        assert tests.formal.helpers.incident_histories.projection(actual) == result
        conflicting_fallback = pd.DataFrame([
            {
                "observation_time": tests.formal.helpers.incident_histories.moment(100),
                "personnel": 9999,
            },
        ])
        assert (
            peri_scribe.incidents.history(
                conflicting_fallback,
                conflicting_fallback,
                frame,
            )
            == actual
        )
