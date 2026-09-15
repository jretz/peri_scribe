"""Raw snapshots retain reporting updates even when geometry does not change."""

from __future__ import annotations

import dataclasses
import pathlib
from typing import TYPE_CHECKING

import numpy as np

import peri_scribe.fires.derived_layers
import peri_scribe.fires.history
import peri_scribe.fires.incident_history
import peri_scribe.fires.sources
import peri_scribe.incidents
import peri_scribe.models
import peri_scribe.output
import peri_scribe.sources.feeds
import tests.factories


if TYPE_CHECKING:
    import pytest


def test_incident_layer_rows_keeps_reports_on_unchanged_polygon(
    incident_sources: peri_scribe.fires.sources.ReadFireSources,
    tmp_path: pathlib.Path,
) -> None:
    groups = peri_scribe.fires.sources.group_fire_sources(incident_sources)
    rows = peri_scribe.fires.incident_history.incident_layer_rows(
        incident_sources,
        groups,
        tmp_path,
    )
    assert [row["estimated_cost_to_date"] for row in rows] == [2000, 3000]
    assert [row["observation_time"] for row in rows] == [
        tests.factories.utc(2026, 9, day, 0) for day in (2, 3)
    ]
    assert all(row["geometry"] is None for row in rows)


def test_incident_layer_rows_skips_complex_parent_duplicates(
    incident_sources: peri_scribe.fires.sources.ReadFireSources,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.fires.sources,
        "fire_is_complex_parent",
        lambda _groups, _group: True,
    )
    groups = peri_scribe.fires.sources.group_fire_sources(incident_sources)
    assert (
        peri_scribe.fires.incident_history.incident_layer_rows(
            incident_sources,
            groups,
            tmp_path,
        )
        == []
    )


def test_incident_layer_rows_preserves_measurement_confirmation_through_storage(
    incident_sources: peri_scribe.fires.sources.ReadFireSources,
    tmp_path: pathlib.Path,
) -> None:
    timestamp = tests.factories.utc(2026, 9, 2, 0)
    perimeter = dataclasses.replace(
        incident_sources.rows[0],
        attributes={
            "attr_ModifiedOnDateTime_dt": timestamp,
            "attr_ModifiedBySystem": "ics209",
            "attr_ICS209ReportDateTime": timestamp,
            "attr_IncidentSize": 100,
            "attr_TotalIncidentPersonnel": np.int32(50),
        },
    )
    location = dataclasses.replace(
        perimeter,
        source_name=peri_scribe.sources.feeds.WFIGS_INCIDENT_LOCATIONS_FEED.name,
        record=dataclasses.replace(perimeter.record, observed_at=timestamp),
        attributes={"IncidentSize": 200},
    )
    read = dataclasses.replace(incident_sources, rows=(perimeter, location))
    groups = peri_scribe.fires.sources.group_fire_sources(read)
    rows = peri_scribe.fires.incident_history.incident_layer_rows(
        read,
        groups,
        tmp_path,
    )
    path = tmp_path / "history.gpkg"
    peri_scribe.output.write_geopackage(
        path,
        [
            peri_scribe.models.LayerData(
                name=peri_scribe.incidents.LAYER_NAME,
                dataframe=peri_scribe.fires.history.build_dataframe(
                    rows,
                    peri_scribe.fires.incident_history.COLUMNS,
                ),
            ),
        ],
    )
    frame = peri_scribe.fires.derived_layers.read_incident_layer(path)
    updates = peri_scribe.incidents.history(frame.iloc[0:0], frame.iloc[0:0], frame)
    assert {tuple(item.measurements.items()): item.confirmed for item in updates} == {
        (("incident_size", 200.0),): False,
        (("personnel", 50.0),): True,
    }
