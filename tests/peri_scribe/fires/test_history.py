"""Tests for peri_scribe.fires.history."""

from __future__ import annotations

import datetime
import json
import pathlib

import geopandas
import numpy as np
import pytest

import peri_scribe.fires.classification
import peri_scribe.fires.files
import peri_scribe.fires.history
import peri_scribe.fires.sources
import peri_scribe.geo.package
import peri_scribe.models
import peri_scribe.output
import tests.factories


FIRIS_FEED_NAME = "CA_Perimeters_NIFC_FIRIS_public_view_0"
WFIGS_LOCATION_FEED_NAME = "WFIGS_Incident_Locations_Current_0"

OUTPUT_WKID = 4326

ITEM_VALUE = 7


def test_classification_text_returns_value_or_none() -> None:
    assert peri_scribe.fires.history.classification_text(None) is None
    assert (
        peri_scribe.fires.history.classification_text(
            tests.factories.classification(
                peri_scribe.models.BorderClassification.CROSSES_CALIFORNIA_BORDER,
            ),
        )
        == "crosses_california_border"
    )


def test_attributes_json_serializes_missing_and_dates() -> None:
    count = 3
    result = peri_scribe.fires.history.attributes_json(
        {
            "missing": float("nan"),
            "when": datetime.datetime(2026, 8, 16, 0, 10, 45, tzinfo=datetime.UTC),
            "count": count,
        },
    )
    parsed = json.loads(result)
    assert parsed["missing"] is None
    assert parsed["when"] == "2026-08-16T00:10:45+00:00"
    assert parsed["count"] == count


def test_json_safe_value_converts_nested_and_numpy_values() -> None:
    assert peri_scribe.fires.history.json_safe_value({"nested": [1, 2]}) == {
        "nested": [1, 2],
    }
    assert (
        peri_scribe.fires.history.json_safe_value(
            np.int64(ITEM_VALUE),
        )
        == ITEM_VALUE
    )


def test_identity_fields_includes_complex_when_present() -> None:
    complex_fire = peri_scribe.models.Fire(
        name="Member",
        status=tests.factories.ACTIVE,
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
    geometry = tests.factories.polygon((0, 0), (1, 0), (1, 1), (0, 0))
    area_in_acres = 100
    version = tests.factories.observation(
        geometry=geometry,
        observation_time=tests.factories.utc(2026, 8, 16, 0, 10),
        attributes={"area_acres": area_in_acres, "GlobalID": "abc"},
    )
    row = peri_scribe.fires.history.perimeter_row(tests.factories.fire(), None, version)
    assert row["geometry"] == geometry
    assert row["area_acres"] == pytest.approx(area_in_acres)
    assert row["source_globalid"] == "abc"
    assert row["source"] == "firis_perimeter"


def test_perimeter_row_falls_back_to_modified_time() -> None:
    geometry = tests.factories.polygon((0, 0), (1, 0), (1, 1), (0, 0))
    modified_time = tests.factories.utc(2026, 8, 17, 23, 18)
    version = tests.factories.observation(
        geometry=geometry,
        snapshot_time=tests.factories.utc(2026, 8, 17, 1, 42),
        attributes={"EditDate": modified_time},
    )
    row = peri_scribe.fires.history.perimeter_row(tests.factories.fire(), None, version)
    assert row["observation_time"] == modified_time


def test_point_row_builds_fields_and_geometry() -> None:
    geometry = tests.factories.point(0, 0)
    incident_size = 100
    modified_time = tests.factories.utc(2026, 8, 17, 1, 0)
    version = tests.factories.observation(
        source_kind=tests.factories.WFIGS_LOCATION,
        geometry=geometry,
        observation_time=modified_time,
        snapshot_time=tests.factories.utc(2026, 8, 17, 6, 0),
        attributes={"IncidentSize": incident_size},
    )
    row = peri_scribe.fires.history.point_row(tests.factories.fire(), None, version)
    assert row["geometry"] == geometry
    assert row["incident_size"] == pytest.approx(incident_size)
    assert row["observation_time"] == modified_time
    assert row["source"] == "wfigs_location"


def test_point_row_falls_back_to_snapshot_time() -> None:
    geometry = tests.factories.point(0, 0)
    snapshot_time = tests.factories.utc(2026, 8, 17, 6, 0)
    version = tests.factories.observation(
        source_kind=tests.factories.WFIGS_LOCATION,
        geometry=geometry,
        snapshot_time=snapshot_time,
        attributes={"IncidentSize": 100},
    )
    row = peri_scribe.fires.history.point_row(tests.factories.fire(), None, version)
    assert row["observation_time"] == snapshot_time


def test_build_dataframe_builds_geodataframe() -> None:
    geometry = tests.factories.point(0, 0)
    rows: list[dict[str, object]] = [{"fire_name": "Bug", "geometry": geometry}]
    dataframe = peri_scribe.fires.history.build_dataframe(
        rows,
        ["fire_name", "geometry"],
    )
    assert isinstance(dataframe, geopandas.GeoDataFrame)
    assert dataframe.crs.to_epsg() == OUTPUT_WKID
    assert list(dataframe.geometry) == [geometry]


def test_history_rows_for_fire_builds_perimeter_and_point_rows() -> None:
    sources_directory = pathlib.Path("data/2026/sources")
    perimeter_path = (
        sources_directory
        / FIRIS_FEED_NAME
        / "000___"
        / "000000,lastEdit=1786929991427.gpkg"
    )
    point_path = (
        sources_directory
        / WFIGS_LOCATION_FEED_NAME
        / "000___"
        / "000000,lastEdit=1786955463975.gpkg"
    )
    perimeter_row_record = peri_scribe.geo.package.FireRowRecord(
        record=tests.factories.fire_record(
            "Bug",
            tests.factories.ACTIVE,
            identifiers=frozenset({"2026-nvccd-030683"}),
            geometry=tests.factories.polygon((0, 0), (1, 0), (1, 1), (0, 0)),
            observed_at=tests.factories.utc(2026, 8, 16, 0, 10),
        ),
        object_id=1,
        source_name=FIRIS_FEED_NAME,
        attributes={"area_acres": 100},
    )
    point_row_record = peri_scribe.geo.package.FireRowRecord(
        record=tests.factories.fire_record(
            "Bug",
            tests.factories.ACTIVE,
            identifiers=frozenset({"2026-nvccd-030683"}),
            geometry=tests.factories.point(0, 0),
        ),
        object_id=1,
        source_name=WFIGS_LOCATION_FEED_NAME,
        attributes={"IncidentSize": 100},
    )
    perimeter_rows, point_rows = peri_scribe.fires.history.history_rows_for_fire(
        tests.factories.fire(),
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
        / FIRIS_FEED_NAME
        / "000___"
        / "000000,lastEdit=1786929991427.gpkg"
    )
    tiny = tests.factories.polygon((0, 0), (0.0001, 0), (0.0001, 0.0001), (0, 0))
    perimeter_row_record = peri_scribe.geo.package.FireRowRecord(
        record=tests.factories.fire_record(
            "Bug",
            tests.factories.ACTIVE,
            identifiers=frozenset({"2026-nvccd-030683"}),
            geometry=tiny,
            observed_at=tests.factories.utc(2026, 8, 16, 0, 10),
        ),
        object_id=1,
        source_name=FIRIS_FEED_NAME,
        attributes={"area_acres": 1000},
    )
    perimeter_rows, _point_rows = peri_scribe.fires.history.history_rows_for_fire(
        tests.factories.fire(),
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
        fires=(tests.factories.fire(),),
        groups=((),),
        complex_identifiers=frozenset(),
    )
    monkeypatch.setattr(
        peri_scribe.fires.sources,
        "fire_is_complex_parent",
        lambda *_arguments: True,
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


def grouped_history_input() -> tuple[
    peri_scribe.fires.sources.FireRecordGroups,
    list[peri_scribe.geo.package.FireRowRecord],
    list[pathlib.Path],
    pathlib.Path,
]:
    """Return grouped history inputs covering perimeter and point-only fires.

    Returns:
        The record groups, the fire rows, the rows' source paths, and the source
        directory.
    """
    sources_directory = pathlib.Path("data/2026/sources")
    perimeter_path = (
        sources_directory
        / FIRIS_FEED_NAME
        / "000___"
        / "000000,lastEdit=1786929991427.gpkg"
    )
    point_path = (
        sources_directory
        / WFIGS_LOCATION_FEED_NAME
        / "000___"
        / "000000,lastEdit=1786955463975.gpkg"
    )
    perimeter_records = [
        tests.factories.fire_record(
            name,
            tests.factories.ACTIVE,
            identifiers=frozenset({identifier}),
            geometry=tests.factories.polygon((0, 0), (1, 0), (1, 1), (0, 0)),
            observed_at=tests.factories.utc(2026, 8, 16, 0, 10),
        )
        for name, identifier in (
            ("Ant", "2026-cacdd-000001"),
            ("Crab", "2026-cacdd-000003"),
        )
    ]
    point_records = [
        tests.factories.fire_record(
            name,
            tests.factories.ACTIVE,
            identifiers=frozenset({identifier}),
            geometry=tests.factories.point(0, 0),
        )
        for name, identifier in (
            ("Ant", "2026-cacdd-000001"),
            ("Bee", "2026-cacdd-000002"),
            ("Crab", "2026-cacdd-000003"),
        )
    ]
    rows = [
        peri_scribe.geo.package.FireRowRecord(
            record=perimeter_records[0],
            object_id=1,
            source_name=FIRIS_FEED_NAME,
            attributes={"area_acres": 100},
        ),
        peri_scribe.geo.package.FireRowRecord(
            record=point_records[0],
            object_id=1,
            source_name=WFIGS_LOCATION_FEED_NAME,
            attributes={"IncidentSize": 100},
        ),
        peri_scribe.geo.package.FireRowRecord(
            record=point_records[1],
            object_id=1,
            source_name=WFIGS_LOCATION_FEED_NAME,
            attributes={"IncidentSize": 100},
        ),
        peri_scribe.geo.package.FireRowRecord(
            record=perimeter_records[1],
            object_id=1,
            source_name=FIRIS_FEED_NAME,
            attributes={"area_acres": 100},
        ),
        peri_scribe.geo.package.FireRowRecord(
            record=point_records[2],
            object_id=1,
            source_name=WFIGS_LOCATION_FEED_NAME,
            attributes={"IncidentSize": 100},
        ),
    ]
    paths = [perimeter_path, point_path, point_path, perimeter_path, point_path]
    record_groups = peri_scribe.fires.sources.FireRecordGroups(
        records=tuple(row.record for row in rows),
        record_paths=tuple(paths),
        fires=(
            tests.factories.fire(name="Ant", identifier="2026-cacdd-000001"),
            tests.factories.fire(name="Bee", identifier="2026-cacdd-000002"),
            tests.factories.fire(name="Crab", identifier="2026-cacdd-000003"),
        ),
        groups=((0, 1), (2,), (3, 4)),
        complex_identifiers=frozenset(),
    )
    return record_groups, rows, paths, sources_directory


def test_history_layer_rows_collects_rows_in_fire_order() -> None:
    record_groups, rows, paths, sources_directory = grouped_history_input()
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
    record_groups, rows, paths, sources_directory = grouped_history_input()
    monkeypatch.setattr(
        peri_scribe.fires.history,
        "HISTORY_ROW_WORKER_COUNT",
        1,
    )
    single_perimeter_rows, single_point_rows = (
        peri_scribe.fires.history.history_layer_rows(
            record_groups,
            {},
            rows,
            paths,
            sources_directory,
        )
    )
    monkeypatch.setattr(
        peri_scribe.fires.history,
        "HISTORY_ROW_WORKER_COUNT",
        4,
    )
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
    record_groups, rows, paths, sources_directory = grouped_history_input()
    real_history_rows_for_fire = peri_scribe.fires.history.history_rows_for_fire

    def failing_history_rows_for_fire(
        fire: peri_scribe.models.Fire,
        group: tuple[int, ...],
        full_rows: list[peri_scribe.geo.package.FireRowRecord],
        full_paths: list[pathlib.Path],
        *,
        sources_directory: pathlib.Path,
        classification: peri_scribe.models.FireClassification | None,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        if fire.identifier == "2026-cacdd-000003":
            message = "perimeter failure"
            raise RuntimeError(message)
        return real_history_rows_for_fire(
            fire,
            group,
            full_rows,
            full_paths,
            sources_directory=sources_directory,
            classification=classification,
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


def test_history_geopackage_path_names_output() -> None:
    assert peri_scribe.fires.files.history_geopackage_path(
        pathlib.Path("data/2026"),
    ) == pathlib.Path("data/2026/derived/history_of_full_geography.gpkg")


def test_write_history_of_full_geography_writes_two_layers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record_groups = peri_scribe.fires.sources.FireRecordGroups(
        records=(),
        record_paths=(),
        fires=(tests.factories.fire(),),
        groups=((),),
        complex_identifiers=frozenset(),
    )
    read = peri_scribe.fires.sources.ReadFireSources(
        rows=(),
        paths=(),
        memberships=(),
    )
    monkeypatch.setattr(
        peri_scribe.fires.sources,
        "read_fire_sources",
        lambda _directory: read,
    )
    monkeypatch.setattr(
        peri_scribe.fires.sources,
        "group_fire_sources",
        lambda _read: record_groups,
    )
    monkeypatch.setattr(
        peri_scribe.fires.classification,
        "classify_fire_sources",
        lambda *_arguments: {},
    )
    monkeypatch.setattr(
        pathlib.Path,
        "mkdir",
        lambda *_arguments, **_keywords: None,
    )
    written: list[tuple[pathlib.Path, list[peri_scribe.models.LayerData]]] = []
    monkeypatch.setattr(
        peri_scribe.output,
        "write_geopackage",
        lambda path, layers: written.append((path, layers)),
    )
    result = peri_scribe.fires.files.write_history_of_full_geography(
        pathlib.Path("data/2026"),
    )
    assert result == pathlib.Path("data/2026/derived/history_of_full_geography.gpkg")
    assert len(written) == 1
    _path, layers = written[0]
    assert [layer.name for layer in layers] == [
        peri_scribe.fires.files.PERIMETER_LAYER_NAME,
        peri_scribe.fires.files.POINT_LAYER_NAME,
    ]
