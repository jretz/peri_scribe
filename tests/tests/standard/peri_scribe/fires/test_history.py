"""Tests for peri_scribe.fires.history."""

from __future__ import annotations

import datetime
import json
import pathlib

import geopandas
import pytest

import peri_scribe.fires.history
import peri_scribe.fires.sources
import peri_scribe.geo.measurements
import peri_scribe.geo.package
import peri_scribe.models
import tests.helpers.doubles.peri_scribe.fires.history
import tests.helpers.factories.geometry
import tests.helpers.factories.peri_scribe.fires.history
import tests.helpers.factories.peri_scribe.models
import tests.helpers.factories.peri_scribe.perimeters.classification_data
import tests.helpers.factories.peri_scribe.perimeters.versions
import tests.helpers.factories.time


def test_classification_text_returns_value_or_none() -> None:
    assert peri_scribe.fires.history.classification_text(None) is None
    assert (
        peri_scribe.fires.history.classification_text(
            tests.helpers.factories.peri_scribe.perimeters.classification_data.classification(
                peri_scribe.models.BorderClassification.CROSSES_CALIFORNIA_BORDER,
            ),
        )
        == "crosses_california_border"
    )


def test_attributes_json_serializes_missing_and_dates() -> None:
    count = 3
    result = peri_scribe.fires.history.attributes_json({
        "missing": float("nan"),
        "when": datetime.datetime(2026, 8, 16, 0, 10, 45, tzinfo=datetime.UTC),
        "count": count,
    })
    parsed = json.loads(result)
    assert parsed["missing"] is None
    assert parsed["when"] == "2026-08-16T00:10:45+00:00"
    assert parsed["count"] == count


def test_identity_fields_includes_complex_when_present() -> None:
    complex_fire = peri_scribe.models.Fire(
        name="Member",
        status=tests.helpers.factories.peri_scribe.models.ACTIVE,
        identifier="member-id",
        aliases=frozenset({"member-id"}),
    )
    peri_scribe.models.FireComplex(
        name="ROWE CREEK COMPLEX",
        identifier="complex-id",
        fires=frozenset({complex_fire}),
    )
    fields = peri_scribe.fires.history.identity_fields(complex_fire, None)
    assert fields["complex_name"] == "ROWE CREEK COMPLEX"
    assert fields["complex_identifier"] == "complex-id"
    assert fields["fire_name"] == "Member"


def test_perimeter_row_builds_fields_and_geometry() -> None:
    geometry = tests.helpers.factories.geometry.polygon((0, 0), (1, 0), (1, 1), (0, 0))
    area = 100
    version = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        geometry=geometry,
        observation_time=tests.helpers.factories.time.utc(2026, 8, 16, 0, 10),
        attributes={"area_acres": area, "GlobalID": "abc"},
    )
    row = peri_scribe.fires.history.perimeter_row(
        tests.helpers.factories.peri_scribe.models.fire(),
        None,
        version,
    )
    assert row["geometry"] == geometry
    assert row["area_acres"] == pytest.approx(area)
    assert row["source_globalid"] == "abc"
    assert row["source"] == "firis_perimeter"


def test_perimeter_row_falls_back_to_modified_time() -> None:
    geometry = tests.helpers.factories.geometry.polygon((0, 0), (1, 0), (1, 1), (0, 0))
    modified_time = tests.helpers.factories.time.utc(2026, 8, 17, 23, 18)
    version = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        geometry=geometry,
        snapshot_time=tests.helpers.factories.time.utc(2026, 8, 17, 1, 42),
        attributes={"EditDate": modified_time},
    )
    row = peri_scribe.fires.history.perimeter_row(
        tests.helpers.factories.peri_scribe.models.fire(),
        None,
        version,
    )
    assert row["observation_time"] == modified_time


def test_perimeter_row_preserves_attributes_without_geometry() -> None:
    observation = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        attributes={"GlobalID": "unmapped"},
    )
    row = peri_scribe.fires.history.perimeter_row(
        tests.helpers.factories.peri_scribe.models.fire(),
        None,
        observation,
    )
    assert row["geometry"] is None
    assert row["source_globalid"] == "unmapped"
    assert peri_scribe.geo.measurements.AREA_COLUMN not in row
    assert peri_scribe.geo.measurements.EXTERIOR_COLUMN not in row


def test_point_row_builds_fields_and_geometry() -> None:
    geometry = tests.helpers.factories.geometry.point(0, 0)
    incident_size = 100
    modified_time = tests.helpers.factories.time.utc(2026, 8, 17, 1)
    version = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        source_kind=tests.helpers.factories.peri_scribe.perimeters.classification_data.WFIGS_LOCATION,
        geometry=geometry,
        observation_time=modified_time,
        snapshot_time=tests.helpers.factories.time.utc(2026, 8, 17, 6),
        attributes={"IncidentSize": incident_size},
    )
    row = peri_scribe.fires.history.point_row(
        tests.helpers.factories.peri_scribe.models.fire(),
        None,
        version,
    )
    assert row["geometry"] == geometry
    assert row["incident_size"] == pytest.approx(incident_size)
    assert row["observation_time"] == modified_time
    assert row["source"] == "wfigs_location"


def test_point_row_falls_back_to_snapshot_time() -> None:
    geometry = tests.helpers.factories.geometry.point(0, 0)
    snapshot_time = tests.helpers.factories.time.utc(2026, 8, 17, 6)
    version = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        source_kind=tests.helpers.factories.peri_scribe.perimeters.classification_data.WFIGS_LOCATION,
        geometry=geometry,
        snapshot_time=snapshot_time,
        attributes={"IncidentSize": 100},
    )
    row = peri_scribe.fires.history.point_row(
        tests.helpers.factories.peri_scribe.models.fire(),
        None,
        version,
    )
    assert row["observation_time"] == snapshot_time


def test_build_dataframe_builds_geodataframe() -> None:
    geometry = tests.helpers.factories.geometry.point(0, 0)
    rows: list[dict[str, object]] = [{"fire_name": "Bug", "geometry": geometry}]
    dataframe = peri_scribe.fires.history.build_dataframe(
        rows,
        ["fire_name", "geometry"],
    )
    assert isinstance(dataframe, geopandas.GeoDataFrame)
    assert (
        dataframe.crs.to_epsg()
        == tests.helpers.factories.peri_scribe.fires.history.OUTPUT_WKID
    )
    assert list(dataframe.geometry) == [geometry]


def test_history_rows_for_fire_builds_perimeter_and_point_rows() -> None:
    sources_directory = pathlib.Path("data/2026/sources")
    perimeter_path = (
        sources_directory
        / tests.helpers.factories.peri_scribe.fires.history.FIRIS_FEED_NAME
        / "000___"
        / "000000,lastEdit=1786929991427.gpkg"
    )
    point_path = (
        sources_directory
        / tests.helpers.factories.peri_scribe.fires.history.WFIGS_LOCATION_FEED_NAME
        / "000___"
        / "000000,lastEdit=1786955463975.gpkg"
    )
    perimeter_row_record = peri_scribe.geo.package.FireRowRecord(
        record=tests.helpers.factories.peri_scribe.models.fire_record(
            "Bug",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifiers=frozenset({"2026-nvccd-030683"}),
            geometry=tests.helpers.factories.geometry.polygon(
                (0, 0),
                (1, 0),
                (1, 1),
                (0, 0),
            ),
            observed_at=tests.helpers.factories.time.utc(2026, 8, 16, 0, 10),
        ),
        object_id=1,
        source_name=tests.helpers.factories.peri_scribe.fires.history.FIRIS_FEED_NAME,
        attributes={"area_acres": 100},
    )
    point_row_record = peri_scribe.geo.package.FireRowRecord(
        record=tests.helpers.factories.peri_scribe.models.fire_record(
            "Bug",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifiers=frozenset({"2026-nvccd-030683"}),
            geometry=tests.helpers.factories.geometry.point(0, 0),
        ),
        object_id=1,
        source_name=tests.helpers.factories.peri_scribe.fires.history.WFIGS_LOCATION_FEED_NAME,
        attributes={"IncidentSize": 100},
    )
    perimeter_rows, point_rows = peri_scribe.fires.history.history_rows_for_fire(
        tests.helpers.factories.peri_scribe.models.fire(),
        (0, 1),
        [perimeter_row_record, point_row_record],
        [perimeter_path, point_path],
        sources_directory=sources_directory,
        classification=None,
    )
    assert len(perimeter_rows) == 1
    assert len(point_rows) == 1
    assert perimeter_rows[0]["area_acres"] == pytest.approx(100)
    assert point_rows[0]["incident_size"] == pytest.approx(100)


def test_history_rows_for_fire_drops_implausibly_small_perimeter() -> None:
    sources_directory = pathlib.Path("data/2026/sources")
    perimeter_path = (
        sources_directory
        / tests.helpers.factories.peri_scribe.fires.history.FIRIS_FEED_NAME
        / "000___"
        / "000000,lastEdit=1786929991427.gpkg"
    )
    tiny = tests.helpers.factories.geometry.polygon(
        (0, 0),
        (0.0001, 0),
        (0.0001, 0.0001),
        (0, 0),
    )
    perimeter_row_record = peri_scribe.geo.package.FireRowRecord(
        record=tests.helpers.factories.peri_scribe.models.fire_record(
            "Bug",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifiers=frozenset({"2026-nvccd-030683"}),
            geometry=tiny,
            observed_at=tests.helpers.factories.time.utc(2026, 8, 16, 0, 10),
        ),
        object_id=1,
        source_name=tests.helpers.factories.peri_scribe.fires.history.FIRIS_FEED_NAME,
        attributes={"area_acres": 1000},
    )
    perimeter_rows, _point_rows = peri_scribe.fires.history.history_rows_for_fire(
        tests.helpers.factories.peri_scribe.models.fire(),
        (0,),
        [perimeter_row_record],
        [perimeter_path],
        sources_directory=sources_directory,
        classification=None,
    )
    assert perimeter_rows == []


def test_history_layer_rows_skips_complex_parents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record_groups = peri_scribe.fires.sources.FireRecordGroups(
        records=(),
        record_paths=(),
        fires=(tests.helpers.factories.peri_scribe.models.fire(),),
        groups=((),),
        complex_identifiers=frozenset(),
    )
    monkeypatch.setattr(
        peri_scribe.fires.sources,
        "fire_is_complex_parent",
        lambda *_args: True,
    )
    perimeter_rows, point_rows = peri_scribe.fires.history.history_layer_rows(
        record_groups,
        {},
        [],
        [],
        pathlib.Path("data/2026/sources"),
    )
    assert perimeter_rows == []
    assert point_rows == []


def test_history_layer_rows_collects_rows_in_fire_order() -> None:
    record_groups, rows, paths, sources_directory = (
        tests.helpers.factories.peri_scribe.fires.history.grouped_history_input()
    )
    perimeter_rows, point_rows = peri_scribe.fires.history.history_layer_rows(
        record_groups,
        {},
        rows,
        paths,
        sources_directory,
    )
    assert [row["fire_identifier"] for row in perimeter_rows] == [
        "2026-cacdd-000001",
        "2026-cacdd-000003",
    ]
    assert [row["fire_identifier"] for row in point_rows] == [
        "2026-cacdd-000001",
        "2026-cacdd-000002",
        "2026-cacdd-000003",
    ]


def test_history_layer_rows_parallel_matches_single_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record_groups, rows, paths, sources_directory = (
        tests.helpers.factories.peri_scribe.fires.history.grouped_history_input()
    )
    monkeypatch.setattr(peri_scribe.fires.history, "HISTORY_ROW_WORKER_COUNT", 1)
    single_perimeter_rows, single_point_rows = (
        peri_scribe.fires.history.history_layer_rows(
            record_groups,
            {},
            rows,
            paths,
            sources_directory,
        )
    )
    monkeypatch.setattr(peri_scribe.fires.history, "HISTORY_ROW_WORKER_COUNT", 4)
    parallel_perimeter_rows, parallel_point_rows = (
        peri_scribe.fires.history.history_layer_rows(
            record_groups,
            {},
            rows,
            paths,
            sources_directory,
        )
    )
    assert parallel_perimeter_rows == single_perimeter_rows
    assert parallel_point_rows == single_point_rows


def test_history_layer_rows_propagates_worker_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record_groups, rows, paths, sources_directory = (
        tests.helpers.factories.peri_scribe.fires.history.grouped_history_input()
    )
    real_history_rows_for_fire = peri_scribe.fires.history.history_rows_for_fire

    failing_history_rows_for_fire = (
        tests.helpers.doubles.peri_scribe.fires.history.make_failing_history_reader(
            real_history_rows_for_fire=real_history_rows_for_fire,
        )
    )

    monkeypatch.setattr(
        peri_scribe.fires.history,
        "history_rows_for_fire",
        failing_history_rows_for_fire,
    )
    with pytest.raises(RuntimeError, match="perimeter failure"):
        peri_scribe.fires.history.history_layer_rows(
            record_groups,
            {},
            rows,
            paths,
            sources_directory,
        )
