"""Tests for peri_scribe.sources.external_sources."""

from __future__ import annotations

import dataclasses
import pathlib
import types
import typing

import arcgis.features
import geopandas
import pandas as pd
import pyproj
import pytest
import shapely.geometry
import us

import peri_scribe.exceptions
import peri_scribe.geo.data
import peri_scribe.models
import peri_scribe.output
import peri_scribe.sources.downloading
import peri_scribe.sources.external_sources
import peri_scribe.sources.snapshots
import tests.factories
import tests.peri_scribe.sources.external_source_helpers
import tests.peri_scribe.sources.external_sources_helpers


def test_output_path_places_single_file_under_sources() -> None:
    source = dataclasses.replace(
        peri_scribe.sources.external_sources.BUILDINGS_SOURCE,
        states=(),
        combine=False,
        compact_database=False,
    )
    path = peri_scribe.sources.external_sources.output_path(
        tests.peri_scribe.sources.external_sources_helpers.YEAR_DIRECTORY,
        source,
    )
    assert (
        path
        == tests.peri_scribe.sources.external_sources_helpers.YEAR_DIRECTORY
        / "sources"
        / "buildings.gpkg"
    )


def test_output_path_names_compact_buildings_database() -> None:
    path = peri_scribe.sources.external_sources.output_path(
        tests.peri_scribe.sources.external_sources_helpers.YEAR_DIRECTORY,
        peri_scribe.sources.external_sources.BUILDINGS_SOURCE,
    )
    assert (
        path
        == tests.peri_scribe.sources.external_sources_helpers.YEAR_DIRECTORY
        / "sources"
        / "buildings.sqlite"
    )


def test_output_path_raises_for_combined_source_with_state() -> None:
    source = dataclasses.replace(
        peri_scribe.sources.external_sources.BUILDINGS_SOURCE,
        states=("California", "Texas"),
        combine=True,
        compact_database=False,
    )
    with pytest.raises(ValueError, match="combines its states"):
        peri_scribe.sources.external_sources.output_path(
            tests.peri_scribe.sources.external_sources_helpers.YEAR_DIRECTORY,
            source,
            state="California",
        )


def test_output_path_names_live_arcgis_source() -> None:
    path = peri_scribe.sources.external_sources.output_path(
        tests.peri_scribe.sources.external_sources_helpers.YEAR_DIRECTORY,
        peri_scribe.sources.external_sources.EVACUATIONS_SOURCE,
    )
    assert (
        path
        == tests.peri_scribe.sources.external_sources_helpers.YEAR_DIRECTORY
        / "sources"
        / "evacuations.gpkg"
    )


def test_output_path_names_per_state_geopackage() -> None:
    source = dataclasses.replace(
        peri_scribe.sources.external_sources.BUILDINGS_SOURCE,
        states=("California",),
        combine=False,
        compact_database=False,
    )
    path = peri_scribe.sources.external_sources.output_path(
        tests.peri_scribe.sources.external_sources_helpers.YEAR_DIRECTORY,
        source,
        state="California",
    )
    assert (
        path
        == tests.peri_scribe.sources.external_sources_helpers.YEAR_DIRECTORY
        / "sources"
        / "buildings"
        / "California.gpkg"
    )


def test_buildings_source_covers_every_us_state() -> None:
    states = peri_scribe.sources.external_sources.BUILDINGS_SOURCE.states
    assert len(states) == len(us.states.STATES) + 1
    assert "California" in states
    assert "District of Columbia" in states


def test_every_external_source_has_a_retrieval_url() -> None:
    for source in peri_scribe.sources.external_sources.EXTERNAL_SOURCES:
        assert source.url
        if not source.compact_database:
            assert source.layer_name


def test_fetch_external_source_raises_for_unknown_kind() -> None:
    source = typing.cast(
        "peri_scribe.sources.external_sources.ExternalSource",
        types.SimpleNamespace(compact_database=False, kind=object()),
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="Unknown external source kind",
    ):
        peri_scribe.sources.external_sources.fetch_external_source(
            source,
            tests.peri_scribe.sources.external_sources_helpers.YEAR_DIRECTORY,
        )


def test_fetch_arcgis_source_writes_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    source = peri_scribe.sources.external_sources.EVACUATIONS_SOURCE
    monkeypatch.setattr(peri_scribe.sources.external_sources.arcgis.gis, "GIS", object)
    layers: list[str] = []
    monkeypatch.setattr(
        peri_scribe.sources.external_sources.arcgis.features,
        "FeatureLayer",
        lambda url, _gis: layers.append(url) or object(),
    )
    queries: list[tuple[str, dict[str, object]]] = []
    feature_set = types.SimpleNamespace(features=[object()], sdf=None)

    query = (
        tests.peri_scribe.sources.external_sources_helpers.make_named_query_recorder(
            queries=queries,
            feature_set=feature_set,
        )
    )

    monkeypatch.setattr(peri_scribe.geo.data, "query_with_retry", query)
    monkeypatch.setattr(
        peri_scribe.geo.data,
        "extract_geometries",
        lambda dataframe: (dataframe, [], None),
    )
    monkeypatch.setattr(
        peri_scribe.geo.data,
        "geo_data_frame_from",
        lambda *_arguments: (
            tests.peri_scribe.sources.external_source_helpers.sample_arcgis_dataframe()
        ),
    )
    writes: list[tuple[pathlib.Path, list[peri_scribe.models.LayerData]]] = []
    monkeypatch.setattr(
        peri_scribe.output,
        "write_geopackage",
        lambda path, layer_data: writes.append((path, layer_data)),
    )
    replacements: list[tuple[pathlib.Path, pathlib.Path]] = []
    monkeypatch.setattr(
        pathlib.Path,
        "replace",
        lambda source, destination: replacements.append((source, destination)),
    )
    monkeypatch.setattr(pathlib.Path, "mkdir", lambda *_arguments, **_keywords: None)

    result = peri_scribe.sources.external_sources.fetch_external_source(
        source,
        tests.peri_scribe.sources.external_sources_helpers.YEAR_DIRECTORY,
    )
    expected = (
        tests.peri_scribe.sources.external_sources_helpers.YEAR_DIRECTORY
        / "sources"
        / "evacuations.gpkg"
    )
    assert result == (expected,)
    assert layers == [source.url]
    assert queries == [
        (
            "evacuations",
            {
                "where": "1=1",
                "out_sr": peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID,
                "order_by_fields": "OBJECTID",
            },
        ),
    ]
    assert len(writes) == 1
    written_path, layer_data = writes[0]
    assert written_path == expected.with_name("evacuations.tmp.gpkg")
    assert replacements == [(written_path, expected)]
    assert [layer.name for layer in layer_data] == ["evacuations"]


def test_fetch_arcgis_source_passes_where_clause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = dataclasses.replace(
        peri_scribe.sources.external_sources.EVACUATIONS_SOURCE,
        where="Event IN ('Red Flag Warning', 'Fire Weather Watch')",
    )
    monkeypatch.setattr(peri_scribe.sources.external_sources.arcgis.gis, "GIS", object)
    monkeypatch.setattr(
        peri_scribe.sources.external_sources.arcgis.features,
        "FeatureLayer",
        lambda _url, _gis: object(),
    )
    queries: list[dict[str, object]] = []
    feature_set = types.SimpleNamespace(features=[object()], sdf=None)

    query = (
        tests.peri_scribe.sources.external_sources_helpers.make_query_filter_recorder(
            queries=queries,
            feature_set=feature_set,
        )
    )

    monkeypatch.setattr(peri_scribe.geo.data, "query_with_retry", query)
    monkeypatch.setattr(
        peri_scribe.geo.data,
        "extract_geometries",
        lambda dataframe: (dataframe, [], None),
    )
    monkeypatch.setattr(
        peri_scribe.geo.data,
        "geo_data_frame_from",
        lambda *_arguments: (
            tests.peri_scribe.sources.external_source_helpers.sample_arcgis_dataframe()
        ),
    )
    monkeypatch.setattr(
        peri_scribe.output,
        "write_geopackage",
        lambda _path, _layer_data: None,
    )
    monkeypatch.setattr(pathlib.Path, "replace", lambda _source, _destination: None)
    monkeypatch.setattr(pathlib.Path, "mkdir", lambda *_arguments, **_keywords: None)

    peri_scribe.sources.external_sources.fetch_external_source(
        source,
        tests.peri_scribe.sources.external_sources_helpers.YEAR_DIRECTORY,
    )
    assert queries == [
        {
            "where": "Event IN ('Red Flag Warning', 'Fire Weather Watch')",
            "out_sr": peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID,
            "order_by_fields": "OBJECTID",
        },
    ]


def test_fetch_arcgis_source_raises_when_no_features(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.sources.external_sources.EVACUATIONS_SOURCE
    monkeypatch.setattr(peri_scribe.sources.external_sources.arcgis.gis, "GIS", object)
    monkeypatch.setattr(
        peri_scribe.sources.external_sources.arcgis.features,
        "FeatureLayer",
        lambda _url, _gis: object(),
    )
    monkeypatch.setattr(
        peri_scribe.geo.data,
        "query_with_retry",
        lambda *_arguments, **_keywords: types.SimpleNamespace(features=[]),
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="returned no features",
    ):
        peri_scribe.sources.external_sources.fetch_external_source(
            source,
            tests.peri_scribe.sources.external_sources_helpers.YEAR_DIRECTORY,
        )


def test_fetch_arcgis_source_raises_when_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.sources.external_sources.EVACUATIONS_SOURCE

    fail = tests.factories.raising_stub(RuntimeError("boom"))

    monkeypatch.setattr(peri_scribe.sources.external_sources.arcgis.gis, "GIS", object)
    monkeypatch.setattr(
        peri_scribe.sources.external_sources.arcgis.features,
        "FeatureLayer",
        fail,
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="Failed to fetch external source evacuations: boom",
    ):
        peri_scribe.sources.external_sources.fetch_external_source(
            source,
            tests.peri_scribe.sources.external_sources_helpers.YEAR_DIRECTORY,
        )


def test_fetch_arcgis_source_logs_geometry_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.sources.external_sources.EVACUATIONS_SOURCE
    monkeypatch.setattr(peri_scribe.sources.external_sources.arcgis.gis, "GIS", object)
    monkeypatch.setattr(
        peri_scribe.sources.external_sources.arcgis.features,
        "FeatureLayer",
        lambda _url, _gis: object(),
    )
    feature_set = types.SimpleNamespace(features=[object()], sdf=None)
    monkeypatch.setattr(
        peri_scribe.geo.data,
        "query_with_retry",
        lambda *_arguments, **_keywords: feature_set,
    )
    monkeypatch.setattr(
        peri_scribe.geo.data,
        "extract_geometries",
        lambda dataframe: (dataframe, [], "warning text"),
    )
    monkeypatch.setattr(
        peri_scribe.geo.data,
        "geo_data_frame_from",
        lambda *_arguments: (
            tests.peri_scribe.sources.external_source_helpers.sample_arcgis_dataframe()
        ),
    )
    monkeypatch.setattr(
        peri_scribe.output,
        "write_geopackage",
        lambda _path, _layer_data: None,
    )
    monkeypatch.setattr(pathlib.Path, "replace", lambda _source, _destination: None)
    monkeypatch.setattr(pathlib.Path, "mkdir", lambda *_arguments, **_keywords: None)
    warnings: list[str] = []
    monkeypatch.setattr(peri_scribe.geo.data.logger, "warning", warnings.append)
    peri_scribe.sources.external_sources.fetch_external_source(
        source,
        tests.peri_scribe.sources.external_sources_helpers.YEAR_DIRECTORY,
    )
    assert warnings == ["warning text"]


def test_fetch_arcgis_source_skips_when_content_unchanged(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.sources.external_sources.EVACUATIONS_SOURCE
    tests.peri_scribe.sources.external_sources_helpers.install_arcgis_query_stubs(
        monkeypatch,
        tests.peri_scribe.sources.external_source_helpers.sample_arcgis_dataframe(),
    )

    first = peri_scribe.sources.external_sources.fetch_external_source(source, tmp_path)
    assert len(first) == 1
    assert first[0].name == "evacuations.gpkg"
    assert first[0].parent.name == "sources"
    second = peri_scribe.sources.external_sources.fetch_external_source(
        source,
        tmp_path,
    )
    assert second == first
    snapshots = list((tmp_path / "sources").rglob("*.gpkg"))
    assert len(snapshots) == 1


def test_fetch_arcgis_source_replaces_current_version_when_content_changed(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.sources.external_sources.EVACUATIONS_SOURCE
    tests.peri_scribe.sources.external_sources_helpers.install_arcgis_query_stubs(
        monkeypatch,
        tests.peri_scribe.sources.external_source_helpers.sample_arcgis_dataframe(),
    )
    first = peri_scribe.sources.external_sources.fetch_external_source(
        source,
        tmp_path,
    )[0]
    changed = (
        tests.peri_scribe.sources.external_source_helpers.sample_arcgis_dataframe()
    )
    changed.loc[0, "OBJECTID"] = 99
    monkeypatch.setattr(
        peri_scribe.geo.data,
        "geo_data_frame_from",
        lambda *_arguments: changed,
    )
    second = peri_scribe.sources.external_sources.fetch_external_source(
        source,
        tmp_path,
    )[0]
    assert second == first
    stored = geopandas.read_file(second, layer="evacuations")
    assert stored["OBJECTID"].tolist() == [99, 2]
    snapshot_names = {path.name for path in (tmp_path / "sources").rglob("*.gpkg")}
    assert snapshot_names == {"evacuations.gpkg"}


def test_fetch_arcgis_source_replaces_unreadable_current_version(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.sources.external_sources.EVACUATIONS_SOURCE
    tests.peri_scribe.sources.external_sources_helpers.install_arcgis_query_stubs(
        monkeypatch,
        tests.peri_scribe.sources.external_source_helpers.sample_arcgis_dataframe(),
    )
    first = peri_scribe.sources.external_sources.fetch_external_source(
        source,
        tmp_path,
    )[0]
    first.write_bytes(b"not a geopackage")
    second = peri_scribe.sources.external_sources.fetch_external_source(
        source,
        tmp_path,
    )[0]
    assert second == first
    stored = geopandas.read_file(second, layer="evacuations")
    assert len(stored) == len(
        tests.peri_scribe.sources.external_source_helpers.sample_arcgis_dataframe(),
    )


def test_fetch_arcgis_source_keeps_current_version_when_fetch_fails(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.sources.external_sources.EVACUATIONS_SOURCE
    tests.peri_scribe.sources.external_sources_helpers.install_arcgis_query_stubs(
        monkeypatch,
        tests.peri_scribe.sources.external_source_helpers.sample_arcgis_dataframe(),
    )
    first = peri_scribe.sources.external_sources.fetch_external_source(
        source,
        tmp_path,
    )[0]
    assert first.name == "evacuations.gpkg"

    fail = tests.factories.raising_stub(RuntimeError("boom"))

    monkeypatch.setattr(
        peri_scribe.sources.external_sources.arcgis.features,
        "FeatureLayer",
        fail,
    )
    warnings: list[str] = []
    monkeypatch.setattr(
        peri_scribe.sources.external_sources.logger,
        "warning",
        lambda message, **_keywords: warnings.append(message),
    )
    second = peri_scribe.sources.external_sources.fetch_external_source(
        source,
        tmp_path,
    )
    assert second == (first,)
    assert any("keeping current data" in message for message in warnings)
    stored = geopandas.read_file(first, layer="evacuations")
    assert len(stored) == len(
        tests.peri_scribe.sources.external_source_helpers.sample_arcgis_dataframe(),
    )


def test_buildings_state_urls_reads_repo_page_every_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    links = {
        state: f"https://example.com/{state.replace(' ', '')}.geojson.zip"
        for state in peri_scribe.sources.external_sources.BUILDINGS_STATES
    }
    urls: list[str] = []
    monkeypatch.setattr(
        peri_scribe.sources.downloading.requests,
        "get",
        lambda url, **_kwargs: (
            urls.append(url)
            or tests.peri_scribe.sources.external_source_helpers.FakeResponse(
                tests.peri_scribe.sources.external_source_helpers.buildings_page_html(
                    links,
                ).encode("utf-8"),
            )
        ),
    )

    result = peri_scribe.sources.external_sources.buildings_state_urls()
    assert urls == ["https://github.com/microsoft/USBuildingFootprints"]
    assert result == links
    assert result["New Hampshire"] == ("https://example.com/NewHampshire.geojson.zip")


def test_buildings_state_urls_raises_when_page_has_nodownload_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.sources.downloading.requests,
        "get",
        lambda _url, **_kwargs: (
            tests.peri_scribe.sources.external_source_helpers.FakeResponse(
                b"<html><body><p>hi</p></body></html>",
            )
        ),
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="No download links found",
    ):
        peri_scribe.sources.external_sources.buildings_state_urls()


def test_buildings_state_urls_raises_when_a_state_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = tests.peri_scribe.sources.external_source_helpers.buildings_page_html({
        "California": "https://example.com/California.geojson.zip",
    })
    monkeypatch.setattr(
        peri_scribe.sources.downloading.requests,
        "get",
        lambda _url, **_kwargs: (
            tests.peri_scribe.sources.external_source_helpers.FakeResponse(
                page.encode("utf-8"),
            )
        ),
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="No download link for Alabama",
    ):
        peri_scribe.sources.external_sources.buildings_state_urls()


def test_buildings_state_urls_raises_when_page_cannot_be_downloaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fail = tests.factories.raising_stub(
        peri_scribe.sources.downloading.requests.exceptions.RequestException("boom"),
    )

    monkeypatch.setattr(peri_scribe.sources.downloading.requests, "get", fail)
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match=(
            r"Failed to download https://github\.com/microsoft/USBuildingFootprints: "
            r"boom"
        ),
    ):
        peri_scribe.sources.external_sources.buildings_state_urls()


def test_fetch_buildings_combines_state_centroids_into_single_geopackage(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = dataclasses.replace(
        peri_scribe.sources.external_sources.BUILDINGS_SOURCE,
        states=("California", "Texas"),
        combine=True,
        stream=True,
        centroids=True,
        keep_attributes=False,
        compact_database=False,
    )
    links = {
        state: (
            "https://minedbuildings.z5.web.core.windows.net/legacy/"
            f"usbuildings-v2/{state.replace(' ', '')}.geojson.zip"
        )
        for state in peri_scribe.sources.external_sources.BUILDINGS_STATES
    }
    page = tests.peri_scribe.sources.external_source_helpers.buildings_page_html(links)
    archive = tests.peri_scribe.sources.external_source_helpers.archive_zip_bytes(
        filename="California.geojson",
        dataframe=(
            tests.peri_scribe.sources.external_source_helpers.building_dataframe()
        ),
        driver="GeoJSON",
    )
    urls: list[str] = []

    get = tests.peri_scribe.sources.external_sources_helpers.make_building_responder(
        urls=urls,
        page=page,
        archive=archive,
    )

    monkeypatch.setattr(peri_scribe.sources.downloading.requests, "get", get)

    result = peri_scribe.sources.external_sources.fetch_external_source(
        source,
        tmp_path,
    )
    output = peri_scribe.sources.external_sources.output_path(tmp_path, source)
    assert result == (output,)
    assert urls == [
        peri_scribe.sources.external_sources.BUILDINGS_SOURCE.url,
        links["California"],
        links["Texas"],
    ]
    second = peri_scribe.sources.external_sources.fetch_external_source(
        source,
        tmp_path,
    )
    assert second == result
    assert urls == [
        peri_scribe.sources.external_sources.BUILDINGS_SOURCE.url,
        links["California"],
        links["Texas"],
    ]
    sources = peri_scribe.sources.snapshots.sources_directory_path(tmp_path)
    assert sorted(path.name for path in sources.iterdir()) == ["buildings.gpkg"]

    converted = geopandas.read_file(output, layer="buildings")
    assert list(converted.columns) == ["geometry"]
    assert list(converted.geometry.geom_type) == ["Point"] * 4
    assert converted.crs.to_epsg() == peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID
    assert sorted(converted.geometry.x) == pytest.approx(
        [1.0, 1.0, 11.0, 11.0],
        abs=1e-2,
    )
    assert sorted(converted.geometry.y) == pytest.approx(
        [1.0, 1.0, 11.0, 11.0],
        abs=1e-2,
    )


def test_fetch_buildings_skips_page_when_combined_output_present(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = dataclasses.replace(
        peri_scribe.sources.external_sources.BUILDINGS_SOURCE,
        states=("California",),
        combine=True,
        stream=True,
        centroids=True,
        keep_attributes=False,
        compact_database=False,
    )
    links = {
        state: (
            "https://minedbuildings.z5.web.core.windows.net/legacy/"
            f"usbuildings-v2/{state.replace(' ', '')}.geojson.zip"
        )
        for state in peri_scribe.sources.external_sources.BUILDINGS_STATES
    }
    page = tests.peri_scribe.sources.external_source_helpers.buildings_page_html(links)
    archive = tests.peri_scribe.sources.external_source_helpers.archive_zip_bytes(
        filename="California.geojson",
        dataframe=(
            tests.peri_scribe.sources.external_source_helpers.building_dataframe()
        ),
        driver="GeoJSON",
    )
    urls: list[str] = []

    get = tests.peri_scribe.sources.external_sources_helpers.make_building_responder(
        urls=urls,
        page=page,
        archive=archive,
    )

    monkeypatch.setattr(peri_scribe.sources.downloading.requests, "get", get)

    first = peri_scribe.sources.external_sources.fetch_external_source(source, tmp_path)
    second = peri_scribe.sources.external_sources.fetch_external_source(
        source,
        tmp_path,
    )
    assert second == first
    assert urls == [
        peri_scribe.sources.external_sources.BUILDINGS_SOURCE.url,
        links["California"],
    ]


def test_fetch_buildings_combines_projected_centroids_into_wgs84(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = dataclasses.replace(
        peri_scribe.sources.external_sources.BUILDINGS_SOURCE,
        states=("California",),
        state_urls=None,
        url="https://example.com/legacy/{state}.geojson.zip",
        geodata_suffix=".shp",
        stream=False,
        combine=True,
        centroids=True,
        keep_attributes=False,
        compact_database=False,
    )
    spatial_reference = (
        f"EPSG:{tests.peri_scribe.sources.external_sources_helpers.WEB_MERCATOR_WKID}"
    )
    dataframe = geopandas.GeoDataFrame(
        {"OBJECTID": [1]},
        geometry=[shapely.geometry.box(0.0, 0.0, 2.0, 2.0)],
        crs=spatial_reference,
    )
    archive = tests.peri_scribe.sources.external_source_helpers.archive_zip_bytes(
        filename="California.shp",
        dataframe=dataframe,
        driver="ESRI Shapefile",
    )
    monkeypatch.setattr(
        peri_scribe.sources.downloading.requests,
        "get",
        lambda _url, **_kwargs: (
            tests.peri_scribe.sources.external_source_helpers.FakeResponse(archive)
        ),
    )

    result = peri_scribe.sources.external_sources.fetch_external_source(
        source,
        tmp_path,
    )
    output = peri_scribe.sources.external_sources.output_path(tmp_path, source)
    assert result == (output,)
    second = peri_scribe.sources.external_sources.fetch_external_source(
        source,
        tmp_path,
    )
    assert second == result
    converted = geopandas.read_file(output, layer="buildings")
    assert list(converted.columns) == ["geometry"]
    assert converted.geometry.geom_type.iloc[0] == "Point"
    assert converted.crs.to_epsg() == peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID
    lon, lat = pyproj.Transformer.from_crs(
        tests.peri_scribe.sources.external_sources_helpers.WEB_MERCATOR_WKID,
        4326,
        always_xy=True,
    ).transform(1.0, 1.0)
    assert converted.geometry.iloc[0].x == pytest.approx(lon, abs=1e-12)
    assert converted.geometry.iloc[0].y == pytest.approx(lat, abs=1e-12)


def test_fetch_arcgis_source_skips_identical_millisecond_dates_after_storage(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feature_set = arcgis.features.FeatureSet(
        features=[
            arcgis.features.Feature(
                attributes={
                    "OBJECTID": 1,
                    "EditDate": 1788906635576,
                    "STATUS": "Evacuation Order",
                },
                geometry={"x": -121.0, "y": 40.0},
            ),
        ],
        fields=[
            {"name": "OBJECTID", "type": "esriFieldTypeOID"},
            {"name": "EditDate", "type": "esriFieldTypeDate"},
            {"name": "STATUS", "type": "esriFieldTypeString"},
        ],
        spatial_reference={"wkid": 4326},
    )
    monkeypatch.setattr(peri_scribe.sources.external_sources.arcgis.gis, "GIS", object)
    monkeypatch.setattr(
        peri_scribe.sources.external_sources.arcgis.features,
        "FeatureLayer",
        lambda *_arguments: object(),
    )
    monkeypatch.setattr(
        peri_scribe.geo.data,
        "query_with_retry",
        lambda *_arguments, **_keywords: feature_set,
    )
    source = peri_scribe.sources.external_sources.EVACUATIONS_SOURCE
    first = peri_scribe.sources.external_sources.fetch_arcgis_source(source, tmp_path)
    stamp = first.stat()
    content = first.read_bytes()
    second = peri_scribe.sources.external_sources.fetch_arcgis_source(source, tmp_path)
    assert second == first
    assert second.stat().st_mtime_ns == stamp.st_mtime_ns
    assert second.read_bytes() == content
    stored = geopandas.read_file(second, layer="evacuations")
    assert stored.iloc[0]["EditDate"] == pd.Timestamp("2026-09-08 22:30:35.576")


@pytest.mark.parametrize("column", ["CreationDate", "EditDate", "STATUS", "geometry"])
def test_fetch_arcgis_source_preserves_real_changes_after_date_normalization(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    column: str,
) -> None:
    dataframe = tests.factories.geo_frame(
        {
            "OBJECTID": [1],
            "CreationDate": [pd.Timestamp("2026-09-08 22:30:35.575999")],
            "EditDate": [pd.Timestamp("2026-09-08 22:30:35.575999")],
            "STATUS": ["Evacuation Order"],
        },
        [shapely.geometry.Point(-121.0, 40.0)],
    )
    tests.peri_scribe.sources.external_sources_helpers.install_arcgis_query_stubs(
        monkeypatch,
        dataframe,
    )
    source = peri_scribe.sources.external_sources.EVACUATIONS_SOURCE
    output = peri_scribe.sources.external_sources.fetch_arcgis_source(source, tmp_path)
    before = geopandas.read_file(output, layer="evacuations")
    changed = dataframe.copy()
    changed.loc[0, column] = {
        "CreationDate": pd.Timestamp("2026-09-08 22:30:36"),
        "EditDate": pd.Timestamp("2026-09-08 22:30:36"),
        "STATUS": "Evacuation Warning",
        "geometry": shapely.geometry.Point(-122.0, 40.0),
    }[column]
    tests.peri_scribe.sources.external_sources_helpers.install_arcgis_query_stubs(
        monkeypatch,
        changed,
    )
    peri_scribe.sources.external_sources.fetch_arcgis_source(source, tmp_path)
    after = geopandas.read_file(output, layer="evacuations")
    assert before.iloc[0][column] != after.iloc[0][column]


@pytest.mark.parametrize("initial_fraction", ["000", "576"])
def test_fetch_arcgis_source_skips_alternating_evacuation_date_precision(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    initial_fraction: str,
) -> None:
    dataframe = tests.factories.geo_frame(
        {
            "OBJECTID": [1, 2],
            "CreationDate": pd.to_datetime([
                f"2026-09-08 22:30:35.{initial_fraction}",
                None,
            ]),
            "EditDate": pd.to_datetime([
                f"2026-09-13 17:40:33.{initial_fraction}",
                None,
            ]),
            "STATUS": ["Evacuation Order", "Evacuation Warning"],
        },
        [shapely.geometry.Point(-121.0, 40.0), shapely.geometry.Point(-122.0, 40.0)],
    )
    source = peri_scribe.sources.external_sources.EVACUATIONS_SOURCE
    tests.peri_scribe.sources.external_sources_helpers.install_arcgis_query_stubs(
        monkeypatch,
        dataframe,
    )
    output = peri_scribe.sources.external_sources.fetch_arcgis_source(source, tmp_path)
    stamp = output.stat().st_mtime_ns
    content = output.read_bytes()
    for fraction in ("000", "576", "577", "000", "575"):
        fresh = dataframe.iloc[::-1].copy()
        fresh.loc[0, "CreationDate"] = pd.Timestamp(f"2026-09-08 22:30:35.{fraction}")
        fresh.loc[0, "EditDate"] = pd.Timestamp(f"2026-09-13 17:40:33.{fraction}")
        tests.peri_scribe.sources.external_sources_helpers.install_arcgis_query_stubs(
            monkeypatch,
            fresh,
        )
        peri_scribe.sources.external_sources.fetch_arcgis_source(source, tmp_path)
        assert output.stat().st_mtime_ns == stamp
        assert output.read_bytes() == content


def test_fetch_arcgis_source_keeps_millisecond_comparisons_for_other_sources(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataframe = tests.factories.geo_frame(
        {"EditDate": [pd.Timestamp("2026-09-08 22:30:35.576")]},
        [shapely.geometry.Point(-121.0, 40.0)],
    )
    source = peri_scribe.sources.external_sources.MAJOR_CITIES_SOURCE
    tests.peri_scribe.sources.external_sources_helpers.install_arcgis_query_stubs(
        monkeypatch,
        dataframe,
    )
    output = peri_scribe.sources.external_sources.fetch_arcgis_source(source, tmp_path)
    changed = dataframe.copy()
    changed.loc[0, "EditDate"] = pd.Timestamp("2026-09-08 22:30:35.577")
    tests.peri_scribe.sources.external_sources_helpers.install_arcgis_query_stubs(
        monkeypatch,
        changed,
    )
    peri_scribe.sources.external_sources.fetch_arcgis_source(source, tmp_path)
    stored = geopandas.read_file(output, layer=source.layer_name)
    assert stored.iloc[0]["EditDate"] == changed.iloc[0]["EditDate"]


def test_evacuation_comparison_frame_preserves_original_and_other_fields() -> None:
    dates = pd.Series(pd.to_datetime(["2026-09-08T22:30:35.576Z", None]))
    dataframe = tests.factories.geo_frame(
        {"EditDate": dates, "Expires": dates, "STATUS": ["Order", None]},
        [shapely.geometry.Point(-121.0, 40.0), None],
    )
    normalized = peri_scribe.sources.external_sources.evacuation_comparison_frame(
        dataframe,
    )
    assert normalized.iloc[0]["EditDate"] == pd.Timestamp("2026-09-08T22:30:35Z")
    assert pd.isna(normalized.iloc[1]["EditDate"])
    assert dataframe["EditDate"].equals(dates)
    assert normalized["Expires"].equals(dates)
    assert normalized["STATUS"].equals(dataframe["STATUS"])
    assert normalized.geometry.equals(dataframe.geometry)


def test_normalize_arcgis_datetimes_preserves_missing_and_timezone_values() -> None:
    dates = pd.Series(pd.to_datetime(["2026-09-08T22:30:35.575999Z", None]))
    dataframe = tests.factories.geo_frame(
        {"EditDate": dates, "STATUS": ["Order", None]},
        [shapely.geometry.Point(-121.0, 40.0), None],
    )
    normalized = peri_scribe.sources.external_sources.normalize_arcgis_datetimes(
        dataframe,
    )
    assert normalized.iloc[0]["EditDate"] == pd.Timestamp("2026-09-08T22:30:35.576Z")
    assert pd.isna(normalized.iloc[1]["EditDate"])
    assert dataframe.iloc[0]["EditDate"] == dates.iloc[0]
    assert normalized["STATUS"].equals(dataframe["STATUS"])
    assert normalized.geometry.equals(dataframe.geometry)
