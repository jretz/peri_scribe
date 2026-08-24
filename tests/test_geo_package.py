"""Tests for peri_scribe.geo_package."""

from __future__ import annotations

import datetime
import pathlib
import re
import typing

import geopandas
import pandas as pd
import pytest
import shapely
import shapely.geometry

import peri_scribe.exceptions
import peri_scribe.feed_types
import peri_scribe.geo_package
import peri_scribe.models
from tests.conftest import SAMPLE_FEED_NAME


ACTIVE = peri_scribe.models.FireStatus.ACTIVE
INACTIVE = peri_scribe.models.FireStatus.INACTIVE


def stub_single_layer(
    stub_geo_package: typing.Callable[
        [pd.DataFrame, dict[str, pd.DataFrame]],
        None,
    ],
    layer_name: str,
    geometry_type: str,
    dataframe: pd.DataFrame,
) -> None:
    """Point the GeoPackage reader at a single layer.

    Args:
        stub_geo_package: The fixture installing in-memory GeoPackage reads.
        layer_name: The layer's name, matching a configured feed.
        geometry_type: The layer's reported geometry type.
        dataframe: The layer's rows.
    """
    stub_geo_package(
        pd.DataFrame({"name": [layer_name], "geometry_type": [geometry_type]}),
        {layer_name: dataframe},
    )


def wgs84_dataframe(
    columns: dict[str, list[object]],
    geometry: list[shapely.Geometry | None] | None = None,
) -> geopandas.GeoDataFrame:
    """Build an unprojected GeoDataFrame with the given columns.

    Args:
        columns: The attribute columns.
        geometry: The feature geometries; defaults to two WGS84 points.

    Returns:
        The GeoDataFrame, without an explicit CRS.
    """
    if geometry is None:
        geometry = [
            shapely.geometry.Point(0, 0),
            shapely.geometry.Point(1, 1),
        ]
    return geopandas.GeoDataFrame(columns, geometry=geometry)


def test_read_geopackage_reads_records_from_every_layer(
    configured_feeds: list[peri_scribe.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_geo_package(
        pd.DataFrame({
            "name": ["Fires_One_0", "Fires_Two_0"],
            "geometry_type": ["Polygon", "Point"],
        }),
        {
            "Fires_One_0": geopandas.GeoDataFrame(
                {
                    "incident_name": ["Park Fire", "ALTA"],
                    "displayStatus": ["Active", "Inactive"],
                },
                geometry=[
                    shapely.geometry.Point(0, 0),
                    shapely.geometry.Point(1, 1),
                ],
            ),
            "Fires_Two_0": geopandas.GeoDataFrame(
                {
                    "IncidentName": ["Creek Fire"],
                    "ActiveFireCandidate": [1],
                },
                geometry=[shapely.geometry.Point(2, 2)],
            ),
        },
    )
    contents = peri_scribe.geo_package.read_geopackage(pathlib.Path("fires.gpkg"))
    records = [row.record for row in contents.rows]
    assert [record.name for record in records] == [
        "Park Fire",
        "ALTA",
        "Creek Fire",
    ]
    assert [record.status for record in records] == [ACTIVE, INACTIVE, ACTIVE]
    assert [record.names for record in records] == [
        frozenset({"park fire"}),
        frozenset({"alta"}),
        frozenset({"creek fire"}),
    ]


def test_read_geopackage_omits_rows_without_status(
    configured_feeds: list[peri_scribe.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_single_layer(
        stub_geo_package,
        "Fires_One_0",
        "Polygon",
        wgs84_dataframe({
            "incident_name": ["Park Fire", "ALTA"],
            "displayStatus": ["Active", None],
        }),
    )
    contents = peri_scribe.geo_package.read_geopackage(pathlib.Path("fires.gpkg"))
    assert [row.record.name for row in contents.rows] == [
        "Park Fire",
    ]


def test_read_geopackage_names_blank_rows_from_mission(
    configured_feeds_with_mission: list[peri_scribe.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_single_layer(
        stub_geo_package,
        "Fires_One_0",
        "Polygon",
        wgs84_dataframe({
            "incident_name": [None, "Woodside"],
            "displayStatus": ["Active", "Active"],
            "incident_number": [None, None],
            "mission": ["CA-HUU-WOODS-N40Y", "WOODSIDE"],
            "poly_DateCurrent": [None, None],
        }),
    )
    contents = peri_scribe.geo_package.read_geopackage(pathlib.Path("fires.gpkg"))
    assert [row.record.name for row in contents.rows] == ["WOODS", "Woodside"]


def test_read_geopackage_omits_rows_with_no_name_at_all(
    configured_feeds: list[peri_scribe.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_single_layer(
        stub_geo_package,
        "Fires_One_0",
        "Polygon",
        wgs84_dataframe(
            {
                "incident_name": [None],
                "displayStatus": ["Active"],
            },
            geometry=[shapely.geometry.Point(0, 0)],
        ),
    )
    contents = peri_scribe.geo_package.read_geopackage(pathlib.Path("fires.gpkg"))
    assert contents.rows == ()


def test_read_geopackage_raises_for_layer_without_configured_feed(
    configured_feeds: list[peri_scribe.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_geo_package(
        pd.DataFrame({
            "name": ["Fires_One_0", "Mystery_Layer_0"],
            "geometry_type": ["Polygon", "Point"],
        }),
        {
            "Fires_One_0": geopandas.GeoDataFrame(
                {
                    "incident_name": ["Park Fire"],
                    "displayStatus": ["Active"],
                },
                geometry=[shapely.geometry.Point(0, 0)],
            ),
        },
    )
    with pytest.raises(
        peri_scribe.exceptions.UnknownLayerError,
        match=re.escape("layer Mystery_Layer_0 in fires.gpkg"),
    ):
        peri_scribe.geo_package.read_geopackage(pathlib.Path("fires.gpkg"))


def test_fire_status_from_classifies_active_and_inactive() -> None:
    assert peri_scribe.geo_package.fire_status_from("Active") is ACTIVE
    assert peri_scribe.geo_package.fire_status_from("inactive") is INACTIVE
    assert peri_scribe.geo_package.fire_status_from(1) is ACTIVE
    assert peri_scribe.geo_package.fire_status_from(0) is INACTIVE
    assert peri_scribe.geo_package.fire_status_from("TRUE") is ACTIVE
    assert peri_scribe.geo_package.fire_status_from("false") is INACTIVE


def test_fire_status_from_returns_none_for_blank_values() -> None:
    assert peri_scribe.geo_package.fire_status_from(None) is None
    assert peri_scribe.geo_package.fire_status_from("") is None
    assert peri_scribe.geo_package.fire_status_from("   ") is None


def test_fire_status_from_raises_for_unknown_value() -> None:
    with pytest.raises(ValueError, match="Unknown fire status value"):
        peri_scribe.geo_package.fire_status_from("Approved")


def test_read_geopackage_reads_normalized_identifiers(
    configured_feeds_with_identifiers: list[peri_scribe.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_single_layer(
        stub_geo_package,
        "Fires_One_0",
        "Polygon",
        wgs84_dataframe({
            "incident_name": ["Bug", "BUG"],
            "displayStatus": ["Active", "Inactive"],
            "incident_number": [
                "{E3094E35-8B33-4A82-BE4B-D2E83652C29F}",
                None,
            ],
        }),
    )
    contents = peri_scribe.geo_package.read_geopackage(pathlib.Path("fires.gpkg"))
    assert [row.record.identifiers for row in contents.rows] == [
        frozenset({"e3094e35-8b33-4a82-be4b-d2e83652c29f"}),
        frozenset(),
    ]


def test_read_geopackage_reads_geometry_and_observation_time(
    configured_feeds_with_mission: list[peri_scribe.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_single_layer(
        stub_geo_package,
        "Fires_One_0",
        "Polygon",
        wgs84_dataframe(
            {
                "incident_name": ["Bug"],
                "displayStatus": ["Active"],
                "incident_number": [None],
                "mission": [None],
                "poly_DateCurrent": [datetime.datetime(2026, 8, 9, 1, 28, 25)],
            },
            geometry=[shapely.geometry.Point(0, 0)],
        ),
    )
    contents = peri_scribe.geo_package.read_geopackage(pathlib.Path("fires.gpkg"))
    record = contents.rows[0].record
    assert record.geometry == shapely.geometry.Point(0, 0)
    assert record.observed_at == datetime.datetime(
        2026,
        8,
        9,
        1,
        28,
        25,
        tzinfo=datetime.UTC,
    )


def test_read_geopackage_reads_mission_and_point_of_origin(
    configured_feeds_with_point_of_origin: list[peri_scribe.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_single_layer(
        stub_geo_package,
        "Fires_Two_0",
        "Point",
        wgs84_dataframe(
            {
                "IncidentName": ["Bug"],
                "ActiveFireCandidate": ["Active"],
                "IrwinID": ["2026-nvccd-030683"],
                "mission": ["2026-NVCCD-030683"],
                "POOState": ["US-CA"],
                "POOFips": ["06035"],
            },
            geometry=[shapely.geometry.Point(0, 0)],
        ),
    )
    contents = peri_scribe.geo_package.read_geopackage(pathlib.Path("fires.gpkg"))
    record = contents.rows[0].record
    assert record.mission == "2026-NVCCD-030683"
    assert record.point_of_origin_state == "US-CA"
    assert record.point_of_origin_fips == "06035"


def test_is_missing_detects_none() -> None:
    assert peri_scribe.geo_package.is_missing(None) is True


def test_is_missing_detects_nan() -> None:
    assert peri_scribe.geo_package.is_missing(float("nan")) is True


def test_is_missing_treats_strings_as_present() -> None:
    assert peri_scribe.geo_package.is_missing("") is False


def test_is_missing_treats_non_scalar_values_as_present() -> None:
    assert peri_scribe.geo_package.is_missing([1, 2]) is False


def test_normalize_identifier() -> None:
    assert peri_scribe.geo_package.normalize_identifier(None) is None
    assert peri_scribe.geo_package.normalize_identifier(float("nan")) is None
    assert peri_scribe.geo_package.normalize_identifier("") is None
    assert peri_scribe.geo_package.normalize_identifier("   ") is None
    assert (
        peri_scribe.geo_package.normalize_identifier(
            "{286B7F1D-8945-4A5D-9D81-5235C18AF1FE}",
        )
        == "286b7f1d-8945-4a5d-9d81-5235c18af1fe"
    )
    assert (
        peri_scribe.geo_package.normalize_identifier(
            " 2026-CACDD-007101 ",
        )
        == "2026-cacdd-007101"
    )


def test_is_complex_child_from() -> None:
    assert peri_scribe.geo_package.is_complex_child_from(1) is True
    assert peri_scribe.geo_package.is_complex_child_from("TRUE") is True
    assert peri_scribe.geo_package.is_complex_child_from("yes") is True
    assert peri_scribe.geo_package.is_complex_child_from(0) is False
    assert peri_scribe.geo_package.is_complex_child_from("false") is False
    assert peri_scribe.geo_package.is_complex_child_from("no") is False
    assert peri_scribe.geo_package.is_complex_child_from(None) is False
    assert peri_scribe.geo_package.is_complex_child_from("") is False
    with pytest.raises(ValueError, match="Unknown complex child value"):
        peri_scribe.geo_package.is_complex_child_from("maybe")


def test_fire_name_from_returns_stripped_name_or_none() -> None:
    assert peri_scribe.geo_package.fire_name_from("  Park Fire ") == "Park Fire"
    assert peri_scribe.geo_package.fire_name_from(None) is None
    assert peri_scribe.geo_package.fire_name_from(float("nan")) is None
    assert peri_scribe.geo_package.fire_name_from("   ") is None


def test_mission_name_from_parses_unit_name_and_tail() -> None:
    assert peri_scribe.geo_package.mission_name_from(
        "CA-LNU-RUMSEY-UPDATED-N40Y",
    ) == peri_scribe.models.MissionName(
        name="RUMSEY-UPDATED",
        base_name="RUMSEY",
    )
    assert peri_scribe.geo_package.mission_name_from(
        "NV-CCD-BUG-N57B",
    ) == peri_scribe.models.MissionName(name="BUG", base_name="BUG")


def test_mission_name_from_handles_bare_names() -> None:
    assert peri_scribe.geo_package.mission_name_from(
        "BUG",
    ) == peri_scribe.models.MissionName(name="BUG", base_name="BUG")
    assert peri_scribe.geo_package.mission_name_from("BORDER 6") == (
        peri_scribe.models.MissionName(name="BORDER 6", base_name="BORDER 6")
    )


def test_mission_name_from_returns_none_for_blank() -> None:
    assert peri_scribe.geo_package.mission_name_from(None) is None
    assert peri_scribe.geo_package.mission_name_from(float("nan")) is None
    assert peri_scribe.geo_package.mission_name_from("   ") is None


def test_mission_name_from_returns_none_without_a_fire_name() -> None:
    assert peri_scribe.geo_package.mission_name_from("CA-LNU-N40Y") is None


def test_observation_time_from_parses_datetime_and_iso() -> None:
    naive = datetime.datetime(2026, 8, 9, 1, 28, 25)
    assert peri_scribe.geo_package.observation_time_from(naive) == (
        datetime.datetime(2026, 8, 9, 1, 28, 25, tzinfo=datetime.UTC)
    )
    assert peri_scribe.geo_package.observation_time_from("2026-08-09T01:28:25") == (
        datetime.datetime(2026, 8, 9, 1, 28, 25, tzinfo=datetime.UTC)
    )


def test_observation_time_from_returns_none_for_blank_or_invalid() -> None:
    assert peri_scribe.geo_package.observation_time_from(None) is None
    assert peri_scribe.geo_package.observation_time_from(float("nan")) is None
    assert peri_scribe.geo_package.observation_time_from("not a date") is None
    assert peri_scribe.geo_package.observation_time_from(12345) is None


def test_read_geopackage_reads_complex_memberships(
    configured_feeds_with_identifiers: list[peri_scribe.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_single_layer(
        stub_geo_package,
        "Fires_Two_0",
        "Point",
        wgs84_dataframe({
            "IncidentName": ["0445 CROSSWHITE", "ROWE CREEK COMPLEX"],
            "ActiveFireCandidate": [1, 1],
            "IrwinID": [
                "{1B0219EE-5298-4FEF-9927-C2666D9D53FC}",
                "{B8431C26-6A9B-4EF0-88D8-F7EA9A3F56C3}",
            ],
            "CpxID": ["{B8431C26-6A9B-4EF0-88D8-F7EA9A3F56C3}", None],
            "CpxName": ["ROWE CREEK COMPLEX", None],
            "IsCpxChild": [1, 0],
        }),
    )
    contents = peri_scribe.geo_package.read_geopackage(pathlib.Path("fires.gpkg"))
    assert contents.memberships == (
        peri_scribe.models.ComplexMembership(
            fire_identifier="1b0219ee-5298-4fef-9927-c2666d9d53fc",
            complex_identifier="b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3",
            complex_name="ROWE CREEK COMPLEX",
        ),
    )


def test_read_geopackage_reads_no_memberships_without_complex_columns(
    configured_feeds_with_identifiers: list[peri_scribe.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_single_layer(
        stub_geo_package,
        "Fires_One_0",
        "Polygon",
        wgs84_dataframe(
            {
                "incident_name": ["Bug"],
                "displayStatus": ["Active"],
                "incident_number": ["some-id"],
            },
            geometry=[shapely.geometry.Point(0, 0)],
        ),
    )
    contents = peri_scribe.geo_package.read_geopackage(pathlib.Path("fires.gpkg"))
    assert contents.memberships == ()


def test_read_geopackage_skips_rows_not_marked_as_complex_children(
    configured_feeds_with_identifiers: list[peri_scribe.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_single_layer(
        stub_geo_package,
        "Fires_Two_0",
        "Point",
        wgs84_dataframe(
            {
                "IncidentName": ["Creek Fire"],
                "ActiveFireCandidate": [1],
                "IrwinID": ["some-id"],
                "CpxID": ["{B8431C26-6A9B-4EF0-88D8-F7EA9A3F56C3}"],
                "CpxName": ["ROWE CREEK COMPLEX"],
                "IsCpxChild": [0],
            },
            geometry=[shapely.geometry.Point(0, 0)],
        ),
    )
    contents = peri_scribe.geo_package.read_geopackage(pathlib.Path("fires.gpkg"))
    assert contents.memberships == ()


def test_read_geopackage_omits_memberships_with_blank_values(
    configured_feeds_with_identifiers: list[peri_scribe.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_single_layer(
        stub_geo_package,
        "Fires_Two_0",
        "Point",
        wgs84_dataframe({
            "IncidentName": ["A", "B"],
            "ActiveFireCandidate": [1, 1],
            "IrwinID": ["", "id-b"],
            "CpxID": ["{B8431C26-6A9B-4EF0-88D8-F7EA9A3F56C3}", ""],
            "CpxName": ["", "ROWE CREEK COMPLEX"],
            "IsCpxChild": [1, 1],
        }),
    )
    contents = peri_scribe.geo_package.read_geopackage(pathlib.Path("fires.gpkg"))
    assert contents.memberships == ()


def test_read_layer_reads_named_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = geopandas.GeoDataFrame(
        {"fire_name": ["Bug"]},
        geometry=[shapely.geometry.Point(0, 0)],
        crs="EPSG:4326",
    )
    calls: list[tuple[pathlib.Path, str]] = []

    def read_file(read_path: pathlib.Path, *, layer: str) -> geopandas.GeoDataFrame:
        calls.append((read_path, layer))
        return frame

    monkeypatch.setattr(
        peri_scribe.geo_package.geopandas,
        "read_file",
        read_file,
    )
    path = pathlib.Path("/derived/full.gpkg")
    assert peri_scribe.geo_package.read_layer(path, "perimeter_history") is frame
    assert calls == [(path, "perimeter_history")]


def test_numeric_value_returns_none_for_bool() -> None:
    value = True
    assert peri_scribe.geo_package.numeric_value(value) is None


def test_numeric_value_parses_strings() -> None:
    assert peri_scribe.geo_package.numeric_value("12.5") == pytest.approx(12.5)


def test_numeric_value_returns_none_for_unparsable_string() -> None:
    assert peri_scribe.geo_package.numeric_value("soon") is None


def test_numeric_value_returns_none_for_other_types() -> None:
    assert peri_scribe.geo_package.numeric_value({"a": 1}) is None


def test_geometries_describe_same_shape_accepts_re_serialized_geometry() -> None:
    ring = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
    reversed_ring = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]
    assert peri_scribe.geo_package.geometries_describe_same_shape(
        shapely.geometry.Polygon(ring),
        shapely.geometry.Polygon(reversed_ring),
    )


def test_geometries_describe_same_shape_accepts_single_part_multi_polygon() -> None:
    polygon = shapely.geometry.Polygon(
        [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)],
    )
    assert peri_scribe.geo_package.geometries_describe_same_shape(
        polygon,
        shapely.geometry.MultiPolygon([polygon]),
    )


def test_geometries_describe_same_shape_rejects_different_shapes() -> None:
    first = shapely.geometry.Polygon(
        [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)],
    )
    different = shapely.geometry.Polygon(
        [(0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0), (0.0, 0.0)],
    )
    assert not peri_scribe.geo_package.geometries_describe_same_shape(
        first,
        different,
    )


def test_geometries_describe_same_shape_treats_missing_geometries() -> None:
    assert peri_scribe.geo_package.geometries_describe_same_shape(None, None)
    assert not peri_scribe.geo_package.geometries_describe_same_shape(
        None,
        shapely.geometry.Point(0, 0),
    )
    assert not peri_scribe.geo_package.geometries_describe_same_shape(
        shapely.geometry.Point(0, 0),
        None,
    )


def test_geometries_describe_same_shape_treats_empty_geometries() -> None:
    empty = shapely.geometry.Polygon()
    assert peri_scribe.geo_package.geometries_describe_same_shape(empty, empty)
    assert not peri_scribe.geo_package.geometries_describe_same_shape(
        empty,
        shapely.geometry.Point(0, 0),
    )


def test_read_layer_dataframe_reads_feed_layer(
    monkeypatch: pytest.MonkeyPatch,
    feed: peri_scribe.feed_types.Feed,
) -> None:
    sentinel = object()
    calls: list[tuple[pathlib.Path, str]] = []
    monkeypatch.setattr(
        peri_scribe.geo_package.geopandas,
        "read_file",
        lambda path, layer: calls.append((path, layer)) or sentinel,
    )
    path = pathlib.Path("/fires.gpkg")
    assert peri_scribe.geo_package.read_layer_dataframe(path, feed) is sentinel
    assert calls == [(path, SAMPLE_FEED_NAME)]


def test_read_geopackage_reads_full_rows(
    configured_feeds: list[peri_scribe.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    object_id = 7
    area_acres = 12
    stub_geo_package(
        pd.DataFrame({"name": ["Fires_One_0"], "geometry_type": ["Point"]}),
        {
            "Fires_One_0": geopandas.GeoDataFrame(
                {
                    "incident_name": ["Park Fire"],
                    "displayStatus": ["Active"],
                    "OBJECTID": [object_id],
                    "area_acres": [area_acres],
                },
                geometry=[shapely.geometry.Point(0, 0)],
            ),
        },
    )
    rows = peri_scribe.geo_package.read_geopackage(pathlib.Path("fires.gpkg")).rows
    assert len(rows) == 1
    assert rows[0].object_id == object_id
    assert rows[0].source_name == "Fires_One_0"
    assert rows[0].record.name == "Park Fire"
    assert rows[0].attributes["area_acres"] == area_acres
    assert "geometry" not in rows[0].attributes


def test_read_geopackage_reads_missing_object_id(
    configured_feeds: list[peri_scribe.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_geo_package(
        pd.DataFrame({"name": ["Fires_One_0"], "geometry_type": ["Point"]}),
        {
            "Fires_One_0": geopandas.GeoDataFrame(
                {
                    "incident_name": ["Park Fire"],
                    "displayStatus": ["Active"],
                },
                geometry=[shapely.geometry.Point(0, 0)],
            ),
        },
    )
    rows = peri_scribe.geo_package.read_geopackage(pathlib.Path("fires.gpkg")).rows
    assert rows[0].object_id is None


def test_object_id_from_returns_none_for_missing_value() -> None:
    assert (
        peri_scribe.geo_package.object_id_from(
            pd.Series({"OBJECTID": float("nan")}),
        )
        is None
    )


def test_row_attributes_excludes_geometry_column() -> None:
    row = pd.Series({
        "OBJECTID": 1,
        "geometry": shapely.geometry.Point(0, 0),
    })
    assert peri_scribe.geo_package.row_attributes(row, "geometry") == {"OBJECTID": 1}


def test_read_geopackage_skips_rows_without_status(
    configured_feeds: list[peri_scribe.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_geo_package(
        pd.DataFrame({"name": ["Fires_One_0"], "geometry_type": ["Point"]}),
        {
            "Fires_One_0": geopandas.GeoDataFrame(
                {
                    "incident_name": ["Park Fire", "No Status"],
                    "displayStatus": ["Active", None],
                },
                geometry=[
                    shapely.geometry.Point(0, 0),
                    shapely.geometry.Point(1, 1),
                ],
            ),
        },
    )
    rows = peri_scribe.geo_package.read_geopackage(pathlib.Path("fires.gpkg")).rows
    assert [row.record.name for row in rows] == ["Park Fire"]


def test_observation_time_from_preserves_aware_datetime() -> None:
    aware = datetime.datetime(
        2026,
        8,
        16,
        0,
        10,
        45,
        tzinfo=datetime.timezone(datetime.timedelta(hours=1)),
    )
    assert peri_scribe.geo_package.observation_time_from(aware) == aware.astimezone(
        datetime.UTC,
    )
