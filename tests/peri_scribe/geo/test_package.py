"""Tests for peri_scribe.geo.package."""

from __future__ import annotations

import datetime
import pathlib
import re
import typing

import geopandas
import pandas as pd
import pyproj
import pytest
import shapely.geometry

import peri_scribe.exceptions
import peri_scribe.geo.package
import peri_scribe.geo.reading
import peri_scribe.models
import peri_scribe.output
import peri_scribe.sources.feed_types
import tests.factories
import tests.peri_scribe.geo.package_helpers


def test_read_geopackage_reads_records_from_every_layer(
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
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
                geometry=[shapely.geometry.Point(0, 0), shapely.geometry.Point(1, 1)],
            ),
            "Fires_Two_0": geopandas.GeoDataFrame(
                {"IncidentName": ["Creek Fire"], "ActiveFireCandidate": [1]},
                geometry=[shapely.geometry.Point(2, 2)],
            ),
        },
    )
    contents = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg"))
    records = [row.record for row in contents.rows]
    assert [record.name for record in records] == ["Park Fire", "ALTA", "Creek Fire"]
    assert [record.status for record in records] == [
        tests.factories.ACTIVE,
        tests.factories.INACTIVE,
        tests.factories.ACTIVE,
    ]
    assert [record.names for record in records] == [
        frozenset({"park fire"}),
        frozenset({"alta"}),
        frozenset({"creek fire"}),
    ]


def test_read_geopackage_omits_rows_without_status(
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    tests.peri_scribe.geo.package_helpers.stub_single_layer(
        stub_geo_package,
        "Fires_One_0",
        "Polygon",
        tests.peri_scribe.geo.package_helpers.wgs84_dataframe({
            "incident_name": ["Park Fire", "ALTA"],
            "displayStatus": ["Active", None],
        }),
    )
    contents = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg"))
    assert [row.record.name for row in contents.rows] == ["Park Fire"]


def test_read_geopackage_names_blank_rows_from_mission(
    configured_feeds_with_mission: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    tests.peri_scribe.geo.package_helpers.stub_single_layer(
        stub_geo_package,
        "Fires_One_0",
        "Polygon",
        tests.peri_scribe.geo.package_helpers.wgs84_dataframe({
            "incident_name": [None, "Woodside"],
            "displayStatus": ["Active", "Active"],
            "incident_number": [None, None],
            "mission": ["CA-HUU-WOODS-N40Y", "WOODSIDE"],
            "poly_DateCurrent": [None, None],
        }),
    )
    contents = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg"))
    assert [row.record.name for row in contents.rows] == ["WOODS", "Woodside"]


def test_read_geopackage_omits_rows_with_no_name_at_all(
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    tests.peri_scribe.geo.package_helpers.stub_single_layer(
        stub_geo_package,
        "Fires_One_0",
        "Polygon",
        tests.peri_scribe.geo.package_helpers.wgs84_dataframe(
            {"incident_name": [None], "displayStatus": ["Active"]},
            geometry=[shapely.geometry.Point(0, 0)],
        ),
    )
    contents = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg"))
    assert contents.rows == ()


def test_read_geopackage_raises_for_layer_without_configured_feed(
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_geo_package(
        pd.DataFrame({
            "name": ["Fires_One_0", "Mystery_Layer_0"],
            "geometry_type": ["Polygon", "Point"],
        }),
        {
            "Fires_One_0": geopandas.GeoDataFrame(
                {"incident_name": ["Park Fire"], "displayStatus": ["Active"]},
                geometry=[shapely.geometry.Point(0, 0)],
            ),
        },
    )
    with pytest.raises(
        peri_scribe.exceptions.UnknownLayerError,
        match=re.escape("layer Mystery_Layer_0 in fires.gpkg"),
    ):
        peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg"))


def test_read_geopackage_reads_normalized_identifiers(
    configured_feeds_with_identifiers: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    tests.peri_scribe.geo.package_helpers.stub_single_layer(
        stub_geo_package,
        "Fires_One_0",
        "Polygon",
        tests.peri_scribe.geo.package_helpers.wgs84_dataframe({
            "incident_name": ["Bug", "BUG"],
            "displayStatus": ["Active", "Inactive"],
            "incident_number": ["{E3094E35-8B33-4A82-BE4B-D2E83652C29F}", None],
        }),
    )
    contents = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg"))
    assert [row.record.identifiers for row in contents.rows] == [
        frozenset({"e3094e35-8b33-4a82-be4b-d2e83652c29f"}),
        frozenset(),
    ]


def test_read_geopackage_reads_geometry_and_observation_time(
    configured_feeds_with_mission: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    tests.peri_scribe.geo.package_helpers.stub_single_layer(
        stub_geo_package,
        "Fires_One_0",
        "Polygon",
        tests.peri_scribe.geo.package_helpers.wgs84_dataframe(
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
    contents = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg"))
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
    configured_feeds_with_point_of_origin: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    tests.peri_scribe.geo.package_helpers.stub_single_layer(
        stub_geo_package,
        "Fires_Two_0",
        "Point",
        tests.peri_scribe.geo.package_helpers.wgs84_dataframe(
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
    contents = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg"))
    record = contents.rows[0].record
    assert record.mission == "2026-NVCCD-030683"
    assert record.point_of_origin_state == "US-CA"
    assert record.point_of_origin_fips == "06035"


def test_read_geopackage_reads_complex_memberships(
    configured_feeds_with_identifiers: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    tests.peri_scribe.geo.package_helpers.stub_single_layer(
        stub_geo_package,
        "Fires_Two_0",
        "Point",
        tests.peri_scribe.geo.package_helpers.wgs84_dataframe({
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
    contents = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg"))
    assert contents.memberships == (
        peri_scribe.models.ComplexMembership(
            fire_identifier="1b0219ee-5298-4fef-9927-c2666d9d53fc",
            complex_identifier="b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3",
            complex_name="ROWE CREEK COMPLEX",
        ),
    )


def test_read_geopackage_reads_no_memberships_without_complex_columns(
    configured_feeds_with_identifiers: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    tests.peri_scribe.geo.package_helpers.stub_single_layer(
        stub_geo_package,
        "Fires_One_0",
        "Polygon",
        tests.peri_scribe.geo.package_helpers.wgs84_dataframe(
            {
                "incident_name": ["Bug"],
                "displayStatus": ["Active"],
                "incident_number": ["some-id"],
            },
            geometry=[shapely.geometry.Point(0, 0)],
        ),
    )
    contents = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg"))
    assert contents.memberships == ()


def test_read_geopackage_skips_rows_not_marked_as_complex_children(
    configured_feeds_with_identifiers: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    tests.peri_scribe.geo.package_helpers.stub_single_layer(
        stub_geo_package,
        "Fires_Two_0",
        "Point",
        tests.peri_scribe.geo.package_helpers.wgs84_dataframe(
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
    contents = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg"))
    assert contents.memberships == ()


def test_read_geopackage_omits_memberships_with_blank_values(
    configured_feeds_with_identifiers: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    tests.peri_scribe.geo.package_helpers.stub_single_layer(
        stub_geo_package,
        "Fires_Two_0",
        "Point",
        tests.peri_scribe.geo.package_helpers.wgs84_dataframe({
            "IncidentName": ["A", "B"],
            "ActiveFireCandidate": [1, 1],
            "IrwinID": ["", "id-b"],
            "CpxID": ["{B8431C26-6A9B-4EF0-88D8-F7EA9A3F56C3}", ""],
            "CpxName": ["", "ROWE CREEK COMPLEX"],
            "IsCpxChild": [1, 1],
        }),
    )
    contents = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg"))
    assert contents.memberships == ()


def test_read_geopackage_reads_full_rows(
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    object_id = 7
    area = 12
    stub_geo_package(
        pd.DataFrame({"name": ["Fires_One_0"], "geometry_type": ["Point"]}),
        {
            "Fires_One_0": geopandas.GeoDataFrame(
                {
                    "incident_name": ["Park Fire"],
                    "displayStatus": ["Active"],
                    "OBJECTID": [object_id],
                    "area_acres": [area],
                },
                geometry=[shapely.geometry.Point(0, 0)],
            ),
        },
    )
    rows = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg")).rows
    assert len(rows) == 1
    assert rows[0].object_id == object_id
    assert rows[0].source_name == "Fires_One_0"
    assert rows[0].record.name == "Park Fire"
    assert rows[0].attributes["area_acres"] == area
    assert "geometry" not in rows[0].attributes


def test_read_geopackage_reads_missing_object_id(
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_geo_package(
        pd.DataFrame({"name": ["Fires_One_0"], "geometry_type": ["Point"]}),
        {
            "Fires_One_0": geopandas.GeoDataFrame(
                {"incident_name": ["Park Fire"], "displayStatus": ["Active"]},
                geometry=[shapely.geometry.Point(0, 0)],
            ),
        },
    )
    rows = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg")).rows
    assert rows[0].object_id is None


def test_read_geopackage_skips_rows_without_status(
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
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
                geometry=[shapely.geometry.Point(0, 0), shapely.geometry.Point(1, 1)],
            ),
        },
    )
    rows = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg")).rows
    assert [row.record.name for row in rows] == ["Park Fire"]


def test_read_geopackage_cached_round_trips_memberships(
    tmp_path: pathlib.Path,
    configured_feeds_with_identifiers: list[peri_scribe.sources.feed_types.Feed],
) -> None:
    feed = configured_feeds_with_identifiers[1]
    path = tmp_path / "sources" / feed.name / "000___" / "000000,lastEdit=0.gpkg"
    path.parent.mkdir(parents=True, exist_ok=True)
    dataframe = tests.peri_scribe.geo.package_helpers.wgs84_dataframe({
        "IncidentName": ["0445 CROSSWHITE", "ROWE CREEK COMPLEX"],
        "ActiveFireCandidate": [1, 1],
        "IrwinID": [
            "{1B0219EE-5298-4FEF-9927-C2666D9D53FC}",
            "{B8431C26-6A9B-4EF0-88D8-F7EA9A3F56C3}",
        ],
        "CpxID": ["{B8431C26-6A9B-4EF0-88D8-F7EA9A3F56C3}", None],
        "CpxName": ["ROWE CREEK COMPLEX", None],
        "IsCpxChild": [1, 0],
    })
    dataframe.crs = pyproj.CRS.from_epsg(4326)
    peri_scribe.output.write_geopackage(
        path,
        [peri_scribe.models.LayerData(name=feed.name, dataframe=dataframe)],
    )
    direct = peri_scribe.geo.package.read_geopackage(path)
    cached = peri_scribe.geo.reading.read_geopackage_cached(path)
    # The records' fixed fields and the memberships round-trip exactly; the attribute
    # bags round-trip with normalized values (numpy scalars become Python values and
    # missing values become None).
    assert [row.record for row in cached.rows] == [row.record for row in direct.rows]
    assert cached.memberships == direct.memberships
    assert [row.attributes.keys() for row in cached.rows] == [
        row.attributes.keys() for row in direct.rows
    ]
