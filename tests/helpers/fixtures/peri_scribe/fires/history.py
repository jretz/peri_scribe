"""Isolate history tests with explicit fixtures."""

from __future__ import annotations

import pathlib

import pytest
import shapely

import peri_scribe.fires.sources
import peri_scribe.geo.package
import tests.helpers.factories.peri_scribe.models
import tests.helpers.factories.time


@pytest.fixture
def history_inputs(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> list[peri_scribe.fires.sources.ReadFireSources]:
    """Exercise real derivation and file I/O with isolated source-reader inputs.

    Args:
        tmp_path: The isolated year directory for source paths and derived output.
        monkeypatch: The fixture used to replace the source reader.

    Returns:
        A replaceable source read for two independently changing fires.
    """
    feed = "CA_Perimeters_NIFC_FIRIS_public_view_0"
    rows = tuple(
        peri_scribe.geo.package.FireRowRecord(
            record=tests.helpers.factories.peri_scribe.models.fire_record(
                name,
                tests.helpers.factories.peri_scribe.models.ACTIVE,
                {name.casefold()},
                geometry=geometry,
                observed_at=tests.helpers.factories.time.utc(2026, 9, 1 + index, 0),
            ),
            source_name=feed,
            object_id=index,
            attributes={
                "area_acres": 100.0,
                "attr_ModifiedOnDateTime_dt": tests.helpers.factories.time.utc(
                    2026,
                    9,
                    1 + index,
                    0,
                ),
                "attr_IncidentSize": 100.0,
                "attr_EstimatedCostToDate": 1000.0,
            },
        )
        for index, (name, geometry) in enumerate([
            ("First", shapely.box(-120, 40, -119.99, 40.01)),
            ("Second", shapely.box(-121, 40, -120.99, 40.01)),
            ("First", shapely.box(-120, 40, -119.98, 40.02)),
        ])
    )
    inputs = [
        peri_scribe.fires.sources.ReadFireSources(
            rows=rows,
            paths=tuple(
                tmp_path / "sources" / feed / "000___" / f"{index:06d},lastEdit=1.gpkg"
                for index in range(len(rows))
            ),
            memberships=(),
        ),
    ]
    monkeypatch.setattr(
        peri_scribe.fires.sources,
        "read_fire_sources",
        lambda _directory: inputs[0],
    )
    return inputs
