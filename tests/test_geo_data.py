import datetime
import pathlib
import re
import time
import typing

import arcgis.features
import geopandas
import pandas as pd
import pyproj
import pytest
import requests
import shapely
import shapely.geometry
import structlog

import peri_scribe.exceptions
import peri_scribe.feed_types
import peri_scribe.geo_data
import peri_scribe.models
import peri_scribe.retry
from tests.conftest import (
    LOOSE_429_ERROR_PAYLOAD,
    RATE_LIMIT_ERROR_PAYLOAD,
    RATE_LIMIT_RETRY_AFTER_SECONDS,
    SAMPLE_FEED_NAME,
    WGS84_WKID,
    LayerStub,
)


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


def test_fire_records_yields_records_from_every_layer(
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
    records = list(peri_scribe.geo_data.fire_records(pathlib.Path("fires.gpkg")))
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


def test_fire_records_is_a_generator(
    configured_feeds: list[peri_scribe.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_single_layer(
        stub_geo_package,
        "Fires_One_0",
        "Polygon",
        wgs84_dataframe({
            "incident_name": ["Park Fire", "ALTA"],
            "displayStatus": ["Active", "Inactive"],
        }),
    )
    records = peri_scribe.geo_data.fire_records(pathlib.Path("fires.gpkg"))
    assert next(records).name == "Park Fire"
    assert next(records).name == "ALTA"


def test_fire_records_omits_rows_without_status(
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
    assert [
        record.name
        for record in peri_scribe.geo_data.fire_records(pathlib.Path("fires.gpkg"))
    ] == [
        "Park Fire",
    ]


def test_fire_records_names_blank_rows_from_mission(
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
    records = list(peri_scribe.geo_data.fire_records(pathlib.Path("fires.gpkg")))
    assert [record.name for record in records] == ["WOODS", "Woodside"]


def test_fire_records_omits_rows_with_no_name_at_all(
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
    assert list(peri_scribe.geo_data.fire_records(pathlib.Path("fires.gpkg"))) == []


def test_fire_records_raises_for_layer_without_configured_feed(
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
        list(peri_scribe.geo_data.fire_records(pathlib.Path("fires.gpkg")))


def test_fire_status_from_classifies_active_and_inactive() -> None:
    assert peri_scribe.geo_data.fire_status_from("Active") is ACTIVE
    assert peri_scribe.geo_data.fire_status_from("inactive") is INACTIVE
    assert peri_scribe.geo_data.fire_status_from(1) is ACTIVE
    assert peri_scribe.geo_data.fire_status_from(0) is INACTIVE
    assert peri_scribe.geo_data.fire_status_from("TRUE") is ACTIVE
    assert peri_scribe.geo_data.fire_status_from("false") is INACTIVE


def test_fire_status_from_returns_none_for_blank_values() -> None:
    assert peri_scribe.geo_data.fire_status_from(None) is None
    assert peri_scribe.geo_data.fire_status_from("") is None
    assert peri_scribe.geo_data.fire_status_from("   ") is None


def test_fire_status_from_raises_for_unknown_value() -> None:
    with pytest.raises(ValueError, match="Unknown fire status value"):
        peri_scribe.geo_data.fire_status_from("Approved")


def test_fire_records_reads_normalized_identifiers(
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
    records = list(peri_scribe.geo_data.fire_records(pathlib.Path("fires.gpkg")))
    assert [record.identifiers for record in records] == [
        frozenset({"e3094e35-8b33-4a82-be4b-d2e83652c29f"}),
        frozenset(),
    ]


def test_fire_records_reads_geometry_and_observation_time(
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
    record = next(peri_scribe.geo_data.fire_records(pathlib.Path("fires.gpkg")))
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


def test_fire_records_reads_mission_and_point_of_origin(
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
    record = next(peri_scribe.geo_data.fire_records(pathlib.Path("fires.gpkg")))
    assert record.mission == "2026-NVCCD-030683"
    assert record.point_of_origin_state == "US-CA"
    assert record.point_of_origin_fips == "06035"


def test_is_missing_detects_none() -> None:
    assert peri_scribe.geo_data.is_missing(None) is True


def test_is_missing_detects_nan() -> None:
    assert peri_scribe.geo_data.is_missing(float("nan")) is True


def test_is_missing_treats_strings_as_present() -> None:
    assert peri_scribe.geo_data.is_missing("") is False


def test_is_missing_treats_non_scalar_values_as_present() -> None:
    assert peri_scribe.geo_data.is_missing([1, 2]) is False


def test_normalize_identifier() -> None:
    assert peri_scribe.geo_data.normalize_identifier(None) is None
    assert peri_scribe.geo_data.normalize_identifier(float("nan")) is None
    assert peri_scribe.geo_data.normalize_identifier("") is None
    assert peri_scribe.geo_data.normalize_identifier("   ") is None
    assert (
        peri_scribe.geo_data.normalize_identifier(
            "{286B7F1D-8945-4A5D-9D81-5235C18AF1FE}",
        )
        == "286b7f1d-8945-4a5d-9d81-5235c18af1fe"
    )
    assert (
        peri_scribe.geo_data.normalize_identifier(
            " 2026-CACDD-007101 ",
        )
        == "2026-cacdd-007101"
    )


def test_is_complex_child_from() -> None:
    assert peri_scribe.geo_data.is_complex_child_from(1) is True
    assert peri_scribe.geo_data.is_complex_child_from("TRUE") is True
    assert peri_scribe.geo_data.is_complex_child_from("yes") is True
    assert peri_scribe.geo_data.is_complex_child_from(0) is False
    assert peri_scribe.geo_data.is_complex_child_from("false") is False
    assert peri_scribe.geo_data.is_complex_child_from("no") is False
    assert peri_scribe.geo_data.is_complex_child_from(None) is False
    assert peri_scribe.geo_data.is_complex_child_from("") is False
    with pytest.raises(ValueError, match="Unknown complex child value"):
        peri_scribe.geo_data.is_complex_child_from("maybe")


def test_fire_name_from_returns_stripped_name_or_none() -> None:
    assert peri_scribe.geo_data.fire_name_from("  Park Fire ") == "Park Fire"
    assert peri_scribe.geo_data.fire_name_from(None) is None
    assert peri_scribe.geo_data.fire_name_from(float("nan")) is None
    assert peri_scribe.geo_data.fire_name_from("   ") is None


def test_mission_name_from_parses_unit_name_and_tail() -> None:
    assert peri_scribe.geo_data.mission_name_from(
        "CA-LNU-RUMSEY-UPDATED-N40Y",
    ) == peri_scribe.models.MissionName(
        name="RUMSEY-UPDATED",
        base_name="RUMSEY",
    )
    assert peri_scribe.geo_data.mission_name_from(
        "NV-CCD-BUG-N57B",
    ) == peri_scribe.models.MissionName(name="BUG", base_name="BUG")


def test_mission_name_from_handles_bare_names() -> None:
    assert peri_scribe.geo_data.mission_name_from(
        "BUG",
    ) == peri_scribe.models.MissionName(name="BUG", base_name="BUG")
    assert peri_scribe.geo_data.mission_name_from("BORDER 6") == (
        peri_scribe.models.MissionName(name="BORDER 6", base_name="BORDER 6")
    )


def test_mission_name_from_returns_none_for_blank() -> None:
    assert peri_scribe.geo_data.mission_name_from(None) is None
    assert peri_scribe.geo_data.mission_name_from(float("nan")) is None
    assert peri_scribe.geo_data.mission_name_from("   ") is None


def test_mission_name_from_returns_none_without_a_fire_name() -> None:
    assert peri_scribe.geo_data.mission_name_from("CA-LNU-N40Y") is None


def test_observation_time_from_parses_datetime_and_iso() -> None:
    naive = datetime.datetime(2026, 8, 9, 1, 28, 25)
    assert peri_scribe.geo_data.observation_time_from(naive) == (
        datetime.datetime(2026, 8, 9, 1, 28, 25, tzinfo=datetime.UTC)
    )
    assert peri_scribe.geo_data.observation_time_from("2026-08-09T01:28:25") == (
        datetime.datetime(2026, 8, 9, 1, 28, 25, tzinfo=datetime.UTC)
    )


def test_observation_time_from_returns_none_for_blank_or_invalid() -> None:
    assert peri_scribe.geo_data.observation_time_from(None) is None
    assert peri_scribe.geo_data.observation_time_from(float("nan")) is None
    assert peri_scribe.geo_data.observation_time_from("not a date") is None
    assert peri_scribe.geo_data.observation_time_from(12345) is None


def test_complex_memberships_yields_complex_children(
    configured_feeds_with_identifiers: list[peri_scribe.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_single_layer(
        stub_geo_package,
        "Fires_Two_0",
        "Point",
        pd.DataFrame({
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
    assert list(
        peri_scribe.geo_data.complex_memberships(pathlib.Path("fires.gpkg")),
    ) == [
        peri_scribe.models.ComplexMembership(
            fire_identifier="1b0219ee-5298-4fef-9927-c2666d9d53fc",
            complex_identifier="b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3",
            complex_name="ROWE CREEK COMPLEX",
        ),
    ]


def test_complex_memberships_skips_layers_without_complex_columns(
    configured_feeds_with_identifiers: list[peri_scribe.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_single_layer(
        stub_geo_package,
        "Fires_One_0",
        "Polygon",
        pd.DataFrame({
            "incident_name": ["Bug"],
            "displayStatus": ["Active"],
            "incident_number": ["some-id"],
        }),
    )
    assert (
        list(
            peri_scribe.geo_data.complex_memberships(pathlib.Path("fires.gpkg")),
        )
        == []
    )


def test_complex_memberships_skips_rows_not_marked_as_complex_children(
    configured_feeds_with_identifiers: list[peri_scribe.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_single_layer(
        stub_geo_package,
        "Fires_Two_0",
        "Point",
        pd.DataFrame({
            "IncidentName": ["Creek Fire"],
            "ActiveFireCandidate": [1],
            "IrwinID": ["some-id"],
            "CpxID": ["{B8431C26-6A9B-4EF0-88D8-F7EA9A3F56C3}"],
            "CpxName": ["ROWE CREEK COMPLEX"],
            "IsCpxChild": [0],
        }),
    )
    assert (
        list(
            peri_scribe.geo_data.complex_memberships(pathlib.Path("fires.gpkg")),
        )
        == []
    )


def test_complex_memberships_omits_rows_with_blank_values(
    configured_feeds_with_identifiers: list[peri_scribe.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_single_layer(
        stub_geo_package,
        "Fires_Two_0",
        "Point",
        pd.DataFrame({
            "IncidentName": ["A", "B"],
            "ActiveFireCandidate": [1, 1],
            "IrwinID": ["", "id-b"],
            "CpxID": ["{B8431C26-6A9B-4EF0-88D8-F7EA9A3F56C3}", ""],
            "CpxName": ["", "ROWE CREEK COMPLEX"],
            "IsCpxChild": [1, 1],
        }),
    )
    assert (
        list(
            peri_scribe.geo_data.complex_memberships(pathlib.Path("fires.gpkg")),
        )
        == []
    )


def test_complex_memberships_raises_for_layer_without_configured_feed(
    configured_feeds_with_identifiers: list[peri_scribe.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_geo_package(
        pd.DataFrame({"name": ["Mystery_Layer_0"], "geometry_type": ["Point"]}),
        {
            "Mystery_Layer_0": pd.DataFrame({
                "IncidentName": ["Creek Fire"],
                "ActiveFireCandidate": [1],
                "IrwinID": ["some-id"],
                "CpxID": ["some-complex"],
                "CpxName": ["SOME COMPLEX"],
                "IsCpxChild": [1],
            }),
        },
    )
    with pytest.raises(
        peri_scribe.exceptions.UnknownLayerError,
        match=re.escape("layer Mystery_Layer_0 in fires.gpkg"),
    ):
        list(peri_scribe.geo_data.complex_memberships(pathlib.Path("fires.gpkg")))


def test_extract_geometries_without_shape_column() -> None:
    dataframe = pd.DataFrame({"name": ["a", "b"]})
    attributes, geometries, geometry_warning = peri_scribe.geo_data.extract_geometries(
        dataframe,
    )
    assert geometry_warning == (
        "  warning: all features lack geometry; writing the layer with NULL geometry"
    )
    assert geometries == [None, None]
    assert list(attributes.columns) == ["name"]


def test_extract_geometries_with_shape_column(
    feature_set_with_geometry: arcgis.features.FeatureSet,
) -> None:
    attributes, geometries, geometry_warning = peri_scribe.geo_data.extract_geometries(
        feature_set_with_geometry.sdf,
    )
    assert geometry_warning is None
    assert "SHAPE" not in attributes.columns
    assert geometries == [
        shapely.geometry.Point(1.0, 2.0),
        shapely.geometry.Point(3.0, 4.0),
    ]


def test_geo_data_frame_from_builds_native_crs_dataframe() -> None:
    dataframe = pd.DataFrame({"name": ["a", "b"]})
    geometries: list[shapely.Geometry | None] = [
        shapely.geometry.Point(1.0, 2.0),
        shapely.geometry.Point(3.0, 4.0),
    ]
    result = peri_scribe.geo_data.geo_data_frame_from(
        dataframe,
        geometries,
        WGS84_WKID,
    )
    assert result.crs == pyproj.CRS.from_epsg(WGS84_WKID)
    assert result.geometry.name == peri_scribe.models.GEOMETRY_COLUMN_NAME
    assert list(result["name"]) == ["a", "b"]
    assert list(result.geometry) == geometries


def test_geo_data_frame_from_allows_null_geometries() -> None:
    dataframe = pd.DataFrame({"name": ["a"]})
    geometries: list[shapely.Geometry | None] = [None]
    result = peri_scribe.geo_data.geo_data_frame_from(
        dataframe,
        geometries,
        WGS84_WKID,
    )
    assert list(result.geometry) == [None]


def test_dataframe_for_layer_raises_no_features_error_when_feed_is_empty(
    feed: peri_scribe.feed_types.Feed,
) -> None:
    layer = LayerStub(properties={})
    feature_set = arcgis.features.FeatureSet([])
    with pytest.raises(
        peri_scribe.exceptions.NoFeaturesError,
        match=f"Feed {SAMPLE_FEED_NAME} returned no features; no output was written",
    ):
        peri_scribe.geo_data.dataframe_for_layer(feed, layer, feature_set)


def test_dataframe_for_layer_builds_geo_data_frame(
    feed: peri_scribe.feed_types.Feed,
    feature_set_with_geometry: arcgis.features.FeatureSet,
) -> None:
    layer = LayerStub(properties={"spatialReference": {"wkid": WGS84_WKID}})
    result = peri_scribe.geo_data.dataframe_for_layer(
        feed,
        layer,
        feature_set_with_geometry,
    )
    assert result.crs == pyproj.CRS.from_epsg(WGS84_WKID)
    assert result.geometry.name == peri_scribe.models.GEOMETRY_COLUMN_NAME
    assert list(result["name"]) == ["a", "b"]
    assert list(result.geometry) == [
        shapely.geometry.Point(1.0, 2.0),
        shapely.geometry.Point(3.0, 4.0),
    ]


def test_dataframe_for_layer_warns_when_features_lack_geometry(
    feed: peri_scribe.feed_types.Feed,
) -> None:
    layer = LayerStub(properties={"spatialReference": {"wkid": WGS84_WKID}})
    feature_set = arcgis.features.FeatureSet(
        [
            arcgis.features.Feature(attributes={"name": "a"}),
            arcgis.features.Feature(attributes={"name": "b"}),
        ],
    )
    with structlog.testing.capture_logs() as captured:
        result = peri_scribe.geo_data.dataframe_for_layer(feed, layer, feature_set)
    assert len(captured) == 1
    assert captured[0]["log_level"] == "warning"
    assert "all features lack geometry" in captured[0]["event"]
    assert list(result.geometry) == [None, None]


class QueryStub:
    """Callable that returns or raises successive outcomes from a list."""

    def __init__(self, outcomes: list[arcgis.features.FeatureSet | Exception]) -> None:
        self.outcomes = list(outcomes)
        self.call_count = 0

    def query(self) -> arcgis.features.FeatureSet:
        outcome = self.outcomes[self.call_count]
        self.call_count += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_query_with_retry_succeeds_on_first_attempt(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    outcomes: list[arcgis.features.FeatureSet | Exception] = [
        feature_set_with_geometry,
    ]
    layer = QueryStub(outcomes)
    result = peri_scribe.geo_data.query_with_retry(
        SAMPLE_FEED_NAME,
        layer,  # ty: ignore
    )
    assert result is feature_set_with_geometry
    assert sleep_calls == []


def test_query_with_retry_retries_on_429_with_retry_after(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    rate_limit_error = ValueError(RATE_LIMIT_ERROR_PAYLOAD)
    outcomes: list[arcgis.features.FeatureSet | Exception] = [
        rate_limit_error,
        feature_set_with_geometry,
    ]
    layer = QueryStub(outcomes)
    result = peri_scribe.geo_data.query_with_retry(
        SAMPLE_FEED_NAME,
        layer,  # ty: ignore
    )
    assert result is feature_set_with_geometry
    assert sleep_calls == [60.0]


def test_query_with_retry_retries_on_loose_429(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    loose_429_error = ValueError(LOOSE_429_ERROR_PAYLOAD)
    outcomes: list[arcgis.features.FeatureSet | Exception] = [
        loose_429_error,
        feature_set_with_geometry,
    ]
    layer = QueryStub(outcomes)
    result = peri_scribe.geo_data.query_with_retry(
        SAMPLE_FEED_NAME,
        layer,  # ty: ignore
    )
    assert result is feature_set_with_geometry
    assert sleep_calls == [
        float(peri_scribe.retry.FALLBACK_RETRY_SECONDS),
    ]


def test_query_with_retry_exhausts_retries_and_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    rate_limit_error = ValueError(RATE_LIMIT_ERROR_PAYLOAD)
    max_retries = peri_scribe.retry.DEFAULT_MAX_RETRIES
    outcomes: list[arcgis.features.FeatureSet | Exception] = [rate_limit_error] * (
        max_retries + 2
    )
    layer = QueryStub(outcomes)
    with pytest.raises(ValueError, match=re.escape(str(RATE_LIMIT_ERROR_PAYLOAD))):
        peri_scribe.geo_data.query_with_retry(
            SAMPLE_FEED_NAME,
            layer,  # ty: ignore
        )
    # Sleep called once per retry (max_retries times), not for the final failure.
    assert sleep_calls == [60.0] * max_retries


def test_query_with_retry_fails_immediately_on_non_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    generic_error = RuntimeError("something else broke")
    outcomes: list[arcgis.features.FeatureSet | Exception] = [generic_error]
    layer = QueryStub(outcomes)
    with pytest.raises(RuntimeError, match="something else broke"):
        peri_scribe.geo_data.query_with_retry(
            SAMPLE_FEED_NAME,
            layer,  # ty: ignore
        )
    assert sleep_calls == []


def test_query_with_retry_retries_on_transient_error(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    transient_error = requests.exceptions.ConnectionError(
        "Connection broken: IncompleteRead(…)",
    )
    outcomes: list[arcgis.features.FeatureSet | Exception] = [
        transient_error,
        feature_set_with_geometry,
    ]
    layer = QueryStub(outcomes)
    result = peri_scribe.geo_data.query_with_retry(
        SAMPLE_FEED_NAME,
        layer,  # ty: ignore
    )
    assert result is feature_set_with_geometry
    # First transient error on attempt 1 → backoff = 2.0s
    assert sleep_calls == [peri_scribe.retry.BACKOFF_BASE_SECONDS]


def test_query_with_retry_exhausts_transient_retries_and_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    transient_error = requests.exceptions.ConnectionError(
        "Connection broken: IncompleteRead(…)",
    )
    retries = 3
    outcomes: list[arcgis.features.FeatureSet | Exception] = [transient_error] * (
        retries + 2
    )
    layer = QueryStub(outcomes)
    with pytest.raises(requests.exceptions.ConnectionError, match="Connection broken"):
        peri_scribe.geo_data.query_with_retry(
            SAMPLE_FEED_NAME,
            layer,  # ty: ignore
            max_retries=retries,
        )
    # Backoff for attempts 1, 2, 3 doubles from the base constant each time.
    assert sleep_calls == [
        peri_scribe.retry.BACKOFF_BASE_SECONDS * 2**attempt
        for attempt in range(retries)
    ]


def test_query_with_retry_logs_rate_limit_reason(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    rate_limit_error = ValueError(RATE_LIMIT_ERROR_PAYLOAD)
    outcomes: list[arcgis.features.FeatureSet | Exception] = [
        rate_limit_error,
        feature_set_with_geometry,
    ]
    layer = QueryStub(outcomes)
    with structlog.testing.capture_logs() as captured:
        peri_scribe.geo_data.query_with_retry(
            SAMPLE_FEED_NAME,
            layer,  # ty: ignore
        )
    assert captured[0]["event"] == "Rate-limited; retrying after server-suggested delay"
    assert captured[0]["attempt"] == 1
    assert captured[0]["retry_seconds"] == RATE_LIMIT_RETRY_AFTER_SECONDS


def test_query_with_retry_logs_transient_reason(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    transient_error = requests.exceptions.ConnectionError(
        "Connection broken: IncompleteRead(…)",
    )
    outcomes: list[arcgis.features.FeatureSet | Exception] = [
        transient_error,
        feature_set_with_geometry,
    ]
    layer = QueryStub(outcomes)
    with structlog.testing.capture_logs() as captured:
        peri_scribe.geo_data.query_with_retry(
            SAMPLE_FEED_NAME,
            layer,  # ty: ignore
        )
    assert captured[0]["event"] == "Transient network error; retrying after backoff"
    assert captured[0]["attempt"] == 1
    assert captured[0]["retry_seconds"] == peri_scribe.retry.BACKOFF_BASE_SECONDS


class IdQueryStub:
    """Layer stand-in returning a fixed object-id query result."""

    def __init__(self, result: dict[str, object]) -> None:
        self.result = result

    def query(self, **_parameters: object) -> dict[str, object]:
        return self.result


def test_query_object_ids_with_retry_returns_object_ids() -> None:
    layer = IdQueryStub({"objectIds": [3, 4]})
    result = peri_scribe.geo_data.query_object_ids_with_retry(
        SAMPLE_FEED_NAME,
        layer,  # ty: ignore
        where="1=1",
    )
    assert result == [3, 4]


def test_query_object_ids_with_retry_raises_without_object_ids() -> None:
    layer = IdQueryStub({"count": 0})
    with pytest.raises(
        peri_scribe.exceptions.NoFeaturesError,
        match="no object ids",
    ):
        peri_scribe.geo_data.query_object_ids_with_retry(
            SAMPLE_FEED_NAME,
            layer,  # ty: ignore
            where="1=1",
        )


def test_read_layer_dataframe_reads_feed_layer(
    monkeypatch: pytest.MonkeyPatch,
    feed: peri_scribe.feed_types.Feed,
) -> None:
    sentinel = object()
    calls: list[tuple[pathlib.Path, str]] = []
    monkeypatch.setattr(
        peri_scribe.geo_data.geopandas,
        "read_file",
        lambda path, layer: calls.append((path, layer)) or sentinel,
    )
    path = pathlib.Path("/fires.gpkg")
    assert peri_scribe.geo_data.read_layer_dataframe(path, feed) is sentinel
    assert calls == [(path, SAMPLE_FEED_NAME)]


def test_fire_row_records_yields_full_rows(
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
    rows = list(peri_scribe.geo_data.fire_row_records(pathlib.Path("fires.gpkg")))
    assert len(rows) == 1
    assert rows[0].object_id == object_id
    assert rows[0].source_name == "Fires_One_0"
    assert rows[0].record.name == "Park Fire"
    assert rows[0].attributes["area_acres"] == area_acres
    assert "geometry" not in rows[0].attributes


def test_fire_row_records_omits_missing_object_id(
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
    rows = list(peri_scribe.geo_data.fire_row_records(pathlib.Path("fires.gpkg")))
    assert rows[0].object_id is None


def test_object_id_from_returns_none_for_missing_value() -> None:
    assert peri_scribe.geo_data.object_id_from(
        pd.Series({"OBJECTID": float("nan")}),
    ) is None


def test_row_attributes_excludes_geometry_column() -> None:
    row = pd.Series({
        "OBJECTID": 1,
        "geometry": shapely.geometry.Point(0, 0),
    })
    assert peri_scribe.geo_data.row_attributes(row, "geometry") == {"OBJECTID": 1}


def test_fire_row_records_raises_for_unknown_layer(
    configured_feeds: list[peri_scribe.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_geo_package(
        pd.DataFrame({"name": ["Unknown_0"], "geometry_type": ["Point"]}),
        {
            "Unknown_0": geopandas.GeoDataFrame(
                {
                    "incident_name": ["Park Fire"],
                    "displayStatus": ["Active"],
                },
                geometry=[shapely.geometry.Point(0, 0)],
            ),
        },
    )
    with pytest.raises(peri_scribe.exceptions.UnknownLayerError):
        list(peri_scribe.geo_data.fire_row_records(pathlib.Path("fires.gpkg")))


def test_fire_row_records_skips_rows_without_status(
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
    rows = list(peri_scribe.geo_data.fire_row_records(pathlib.Path("fires.gpkg")))
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
    assert peri_scribe.geo_data.observation_time_from(aware) == aware.astimezone(
        datetime.UTC,
    )
