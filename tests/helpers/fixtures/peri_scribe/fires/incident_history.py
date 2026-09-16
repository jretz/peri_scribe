"""Isolate incident history tests with explicit fixtures."""

from __future__ import annotations

import pathlib

import pytest

import peri_scribe.fires.sources
import peri_scribe.geo.package
import tests.helpers.factories.geometry
import tests.helpers.factories.peri_scribe.models
import tests.helpers.factories.time


@pytest.fixture
def incident_sources(
    tmp_path: pathlib.Path,
) -> peri_scribe.fires.sources.ReadFireSources:
    """Expose report changes that a geometry-only history would discard.

    Args:
        tmp_path: The isolated base for synthetic source provenance paths.

    Returns:
        Two snapshots with identical polygon evidence and different incident costs and
        modification times; no snapshot files need to be written.
    """
    feed = "WFIGS_Interagency_Perimeters_Current_0"
    rows = tuple(
        peri_scribe.geo.package.FireRowRecord(
            record=tests.helpers.factories.peri_scribe.models.fire_record(
                "Example",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
                {"example"},
                geometry=tests.helpers.factories.geometry.square(0.01),
                observed_at=tests.helpers.factories.time.utc(2026, 9, 1, 0),
            ),
            source_name=feed,
            object_id=1,
            attributes={
                "attr_IncidentSize": 100,
                "attr_EstimatedCostToDate": day * 1000,
                "attr_ModifiedOnDateTime_dt": tests.helpers.factories.time.utc(
                    2026,
                    9,
                    day,
                    0,
                ),
            },
        )
        for day in (2, 3)
    )
    return peri_scribe.fires.sources.ReadFireSources(
        rows=rows,
        paths=tuple(
            tmp_path / feed / "000___" / f"{index:06d},lastEdit=1.gpkg"
            for index in range(2)
        ),
        memberships=(),
    )
