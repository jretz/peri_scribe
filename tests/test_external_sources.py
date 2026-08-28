"""Tests for peri_scribe.external_sources."""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import io
import json
import pathlib
import tempfile
import types
import typing
import zipfile

import geopandas
import pandas as pd
import pyproj
import pytest
import shapely.geometry
import us

import peri_scribe.exceptions
import peri_scribe.external_sources
import peri_scribe.feed_types
import peri_scribe.geo_data
import peri_scribe.models
import peri_scribe.output
import peri_scribe.snapshots
from tests.main_stubs import SAMPLE_LAST_EDIT_TIMESTAMP


YEAR_DIRECTORY = pathlib.Path("/data/2026")
WEB_MERCATOR_WKID = 3857


class FakeResponse:
    """Stand-in for a requests response with a fixed body."""

    def __init__(self, body: bytes) -> None:
        self.body = body

    def raise_for_status(self) -> None:
        """No-op; the response is treated as successful."""

    @property
    def text(self) -> str:
        """The response body decoded as text."""
        return self.body.decode("utf-8")

    def iter_content(self, chunk_size: int) -> typing.Iterator[bytes]:
        """Yield the body in chunks of *chunk_size* bytes.

        Args:
            chunk_size: The number of bytes per chunk.

        Yields:
            The body chunks.
        """
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset : offset + chunk_size]


def archive_zip_bytes(
    *,
    filename: str,
    dataframe: geopandas.GeoDataFrame,
    driver: str,
) -> bytes:
    """Build an in-memory zip holding *dataframe* written with *driver*.

    Args:
        filename: The output filename the driver writes, and the prefix matching the
            files the zip holds.
        dataframe: The data to archive.
        driver: The OGR driver to write the data with.

    Returns:
        The zip archive's bytes.
    """
    with tempfile.TemporaryDirectory() as directory:
        path = pathlib.Path(directory) / filename
        dataframe.to_file(path, driver=driver)
        stem = path.stem
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for file_path in sorted(path.parent.iterdir()):
                if file_path.stem == stem:
                    archive.writestr(file_path.name, file_path.read_bytes())
        return buffer.getvalue()


def building_dataframe() -> geopandas.GeoDataFrame:
    """Return a small footprint dataframe for a conversion test.

    Returns:
        Two building footprint polygons with OBJECTID attributes.
    """
    return geopandas.GeoDataFrame(
        {"OBJECTID": [1, 2]},
        geometry=[
            shapely.geometry.box(0.0, 0.0, 2.0, 2.0),
            shapely.geometry.box(10.0, 10.0, 12.0, 12.0),
        ],
        crs="EPSG:4326",
    )


def buildings_page_html(links: dict[str, str]) -> str:
    """Render a GitHub-style page whose "Download links" table holds *links*.

    The page mirrors the README rendering GitHub serves for the repository page: a
    "Download links" heading followed by a table whose rows link each state to its
    archive, bracketed by other headings and a link so the parser must select the
    right table.

    Args:
        links: The state-to-archive-URL pairs the table should hold.

    Returns:
        The page's HTML.
    """
    rows = "\n".join(
        (
            f'<tr><td align="left"><a href="{url}" rel="nofollow">'
            f"{state}</a></td>"
            '<td align="center">1</td><td align="right">1 MiB</td></tr>'
        )
        for state, url in links.items()
    )
    heading = (
        '<div class="markdown-heading" dir="auto"><h2 tabindex="-1" '
        'class="heading-element" dir="auto">Download links</h2>'
        '<a id="user-content-download-links" class="anchor" '
        'href="#download-links"></a></div>'
    )
    table = (
        "<markdown-accessiblity-table><table><thead><tr>"
        '<th align="left">State or district</th>'
        '<th align="center">Number of Buildings</th>'
        '<th align="right">Unzipped size</th>'
        "</tr></thead><tbody>"
        f"{rows}</tbody></table></markdown-accessiblity-table>"
    )
    return (
        '<!DOCTYPE html><html lang="en"><body>'
        '<div class="markdown-heading" dir="auto"><h2 tabindex="-1" '
        'class="heading-element" dir="auto">Introduction</h2>'
        '<a id="user-content-introduction" class="anchor" '
        'href="#introduction"></a></div>'
        '<p dir="auto">See the <a href="https://example.com/other">region</a>.</p>'
        f"{heading}{table}"
        '<div class="markdown-heading" dir="auto"><h2 tabindex="-1" '
        'class="heading-element" dir="auto">Contributing</h2>'
        '<a id="user-content-contributing" class="anchor" '
        'href="#contributing"></a></div>'
        "</body></html>"
    )


def per_state_template_source() -> peri_scribe.external_sources.ExternalSource:
    """Return the buildings source without its page, using a URL template.

    The real buildings source reads its per-state links from the repository page;
    the generic download path (a ``{state}`` URL template) is exercised with this
    source so that download and conversion failures can be tested directly.

    Returns:
        A per-state download source named after the buildings source.
    """
    return dataclasses.replace(
        peri_scribe.external_sources.BUILDINGS_SOURCE,
        states=("California",),
        state_urls=None,
        url="https://example.com/legacy/{state}.geojson.zip",
    )


def sample_arcgis_dataframe() -> geopandas.GeoDataFrame:
    """Return a small WGS84 dataframe for an ArcGIS fetch test.

    Returns:
        Two point features with OBJECTID attributes in WGS84.
    """
    return geopandas.GeoDataFrame(
        {"OBJECTID": [1, 2]},
        geometry=[
            shapely.geometry.Point(1.0, 2.0),
            shapely.geometry.Point(3.0, 4.0),
        ],
        crs="EPSG:4326",
    )


def install_arcgis_query_stubs(
    monkeypatch: pytest.MonkeyPatch,
    dataframe: geopandas.GeoDataFrame,
) -> None:
    """Point the ArcGIS query pipeline at a fake layer returning *dataframe*.

    Args:
        monkeypatch: The monkeypatch fixture.
        dataframe: The GeoDataFrame the fake pipeline returns.
    """
    monkeypatch.setattr(peri_scribe.external_sources.arcgis.gis, "GIS", object)
    monkeypatch.setattr(
        peri_scribe.external_sources.arcgis.features,
        "FeatureLayer",
        lambda _url, _gis: object(),
    )
    feature_set = types.SimpleNamespace(features=[object()], sdf=None)
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "query_with_retry",
        lambda *_arguments, **_keywords: feature_set,
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "extract_geometries",
        lambda dataframe: (dataframe, [], None),
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "geo_data_frame_from",
        lambda *_arguments: dataframe,
    )
    monkeypatch.setattr(
        peri_scribe.feed_types,
        "observe_layer_last_edit_timestamp",
        lambda _url, _name: SAMPLE_LAST_EDIT_TIMESTAMP,
    )


def test_output_path_places_file_under_source_directory() -> None:
    path = peri_scribe.external_sources.output_path(
        YEAR_DIRECTORY,
        peri_scribe.external_sources.WUI_SOURCE,
    )
    assert path == YEAR_DIRECTORY / "sources" / "wui" / "wui.gpkg"


def test_output_path_names_combined_geopackage() -> None:
    path = peri_scribe.external_sources.output_path(
        YEAR_DIRECTORY,
        peri_scribe.external_sources.BUILDINGS_SOURCE,
    )
    assert path == YEAR_DIRECTORY / "sources" / "buildings" / "buildings.gpkg"


def test_output_path_raises_for_combined_source_with_state() -> None:
    with pytest.raises(ValueError, match="combines its states"):
        peri_scribe.external_sources.output_path(
            YEAR_DIRECTORY,
            peri_scribe.external_sources.BUILDINGS_SOURCE,
            state="California",
        )


def test_output_path_raises_for_live_arcgis_source() -> None:
    with pytest.raises(ValueError, match="stores snapshots"):
        peri_scribe.external_sources.output_path(
            YEAR_DIRECTORY,
            peri_scribe.external_sources.EVACUATIONS_SOURCE,
        )


def test_output_path_names_per_state_geopackage() -> None:
    source = dataclasses.replace(
        peri_scribe.external_sources.WUI_SOURCE,
        states=("California",),
    )
    path = peri_scribe.external_sources.output_path(
        YEAR_DIRECTORY,
        source,
        state="California",
    )
    assert path == YEAR_DIRECTORY / "sources" / "wui" / "California.gpkg"


def test_buildings_source_covers_every_us_state() -> None:
    states = peri_scribe.external_sources.BUILDINGS_SOURCE.states
    assert len(states) == len(us.states.STATES) + 1
    assert "California" in states
    assert "District of Columbia" in states


def test_external_source_names_are_auxiliary_directories() -> None:
    names = {source.name for source in peri_scribe.external_sources.EXTERNAL_SOURCES}
    assert names.issubset(peri_scribe.snapshots.AUXILIARY_DIRECTORY_NAMES)


def test_every_external_source_has_a_retrieval_url() -> None:
    for source in peri_scribe.external_sources.EXTERNAL_SOURCES:
        assert source.url
        assert source.layer_name


def test_fetch_external_source_raises_for_unknown_kind() -> None:
    source = typing.cast(
        "peri_scribe.external_sources.ExternalSource",
        types.SimpleNamespace(kind=object()),
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="Unknown external source kind",
    ):
        peri_scribe.external_sources.fetch_external_source(source, YEAR_DIRECTORY)


def testfetch_arcgis_source_writes_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.external_sources.EVACUATIONS_SOURCE
    monkeypatch.setattr(
        peri_scribe.external_sources.arcgis.gis,
        "GIS",
        object,
    )
    layers: list[str] = []
    monkeypatch.setattr(
        peri_scribe.external_sources.arcgis.features,
        "FeatureLayer",
        lambda url, _gis: layers.append(url) or object(),
    )
    queries: list[tuple[str, dict[str, object]]] = []
    feature_set = types.SimpleNamespace(features=[object()], sdf=None)

    def query(
        name: str,
        _layer: object,
        *,
        parameters: dict[str, object],
    ) -> object:
        queries.append((name, parameters))
        return feature_set

    monkeypatch.setattr(
        peri_scribe.geo_data,
        "query_with_retry",
        query,
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "extract_geometries",
        lambda dataframe: (dataframe, [], None),
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "geo_data_frame_from",
        lambda *_arguments: [object()],
    )
    writes: list[tuple[pathlib.Path, list[peri_scribe.models.LayerData]]] = []
    monkeypatch.setattr(
        peri_scribe.output,
        "write_geopackage",
        lambda path, layer_data: writes.append((path, layer_data)),
    )
    monkeypatch.setattr(
        peri_scribe.feed_types,
        "observe_layer_last_edit_timestamp",
        lambda _url, _name: SAMPLE_LAST_EDIT_TIMESTAMP,
    )
    monkeypatch.setattr(
        pathlib.Path,
        "mkdir",
        lambda *_arguments, **_keywords: None,
    )

    result = peri_scribe.external_sources.fetch_external_source(source, YEAR_DIRECTORY)
    expected = (
        YEAR_DIRECTORY
        / "sources"
        / "evacuations"
        / "000___"
        / f"000000,lastEdit={SAMPLE_LAST_EDIT_TIMESTAMP}.gpkg"
    )
    assert result == (expected,)
    assert layers == [source.url]
    assert queries == [
        (
            "evacuations",
            {"where": "1=1", "out_sr": peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID},
        ),
    ]
    assert len(writes) == 1
    written_path, layer_data = writes[0]
    assert written_path == expected
    assert [layer.name for layer in layer_data] == ["evacuations"]


def testfetch_arcgis_source_passes_where_clause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.external_sources.RED_FLAG_WARNINGS_SOURCE
    monkeypatch.setattr(
        peri_scribe.external_sources.arcgis.gis,
        "GIS",
        object,
    )
    monkeypatch.setattr(
        peri_scribe.external_sources.arcgis.features,
        "FeatureLayer",
        lambda _url, _gis: object(),
    )
    queries: list[dict[str, object]] = []
    feature_set = types.SimpleNamespace(features=[object()], sdf=None)

    def query(
        _name: str,
        _layer: object,
        *,
        parameters: dict[str, object],
    ) -> object:
        queries.append(parameters)
        return feature_set

    monkeypatch.setattr(
        peri_scribe.geo_data,
        "query_with_retry",
        query,
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "extract_geometries",
        lambda dataframe: (dataframe, [], None),
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "geo_data_frame_from",
        lambda *_arguments: [object()],
    )
    monkeypatch.setattr(
        peri_scribe.output,
        "write_geopackage",
        lambda _path, _layer_data: None,
    )
    monkeypatch.setattr(
        peri_scribe.feed_types,
        "observe_layer_last_edit_timestamp",
        lambda _url, _name: SAMPLE_LAST_EDIT_TIMESTAMP,
    )
    monkeypatch.setattr(
        pathlib.Path,
        "mkdir",
        lambda *_arguments, **_keywords: None,
    )

    peri_scribe.external_sources.fetch_external_source(source, YEAR_DIRECTORY)
    assert queries == [
        {
            "where": "Event IN ('Red Flag Warning', 'Fire Weather Watch')",
            "out_sr": peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID,
        },
    ]


def testfetch_arcgis_source_raises_when_no_features(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.external_sources.EVACUATIONS_SOURCE
    monkeypatch.setattr(
        peri_scribe.external_sources.arcgis.gis,
        "GIS",
        object,
    )
    monkeypatch.setattr(
        peri_scribe.external_sources.arcgis.features,
        "FeatureLayer",
        lambda _url, _gis: object(),
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "query_with_retry",
        lambda *_arguments, **_keywords: types.SimpleNamespace(features=[]),
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="returned no features",
    ):
        peri_scribe.external_sources.fetch_external_source(source, YEAR_DIRECTORY)


def testfetch_arcgis_source_raises_when_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.external_sources.EVACUATIONS_SOURCE

    def fail(_url: str, _gis: object) -> typing.Never:
        message = "boom"
        raise RuntimeError(message)

    monkeypatch.setattr(
        peri_scribe.external_sources.arcgis.gis,
        "GIS",
        object,
    )
    monkeypatch.setattr(
        peri_scribe.external_sources.arcgis.features,
        "FeatureLayer",
        fail,
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="Failed to fetch external source evacuations: boom",
    ):
        peri_scribe.external_sources.fetch_external_source(source, YEAR_DIRECTORY)


def testfetch_arcgis_source_logs_geometry_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.external_sources.EVACUATIONS_SOURCE
    monkeypatch.setattr(
        peri_scribe.external_sources.arcgis.gis,
        "GIS",
        object,
    )
    monkeypatch.setattr(
        peri_scribe.external_sources.arcgis.features,
        "FeatureLayer",
        lambda _url, _gis: object(),
    )
    feature_set = types.SimpleNamespace(features=[object()], sdf=None)
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "query_with_retry",
        lambda *_arguments, **_keywords: feature_set,
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "extract_geometries",
        lambda dataframe: (dataframe, [], "warning text"),
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "geo_data_frame_from",
        lambda *_arguments: [object()],
    )
    monkeypatch.setattr(
        peri_scribe.output,
        "write_geopackage",
        lambda _path, _layer_data: None,
    )
    monkeypatch.setattr(
        peri_scribe.feed_types,
        "observe_layer_last_edit_timestamp",
        lambda _url, _name: SAMPLE_LAST_EDIT_TIMESTAMP,
    )
    monkeypatch.setattr(
        pathlib.Path,
        "mkdir",
        lambda *_arguments, **_keywords: None,
    )
    warnings: list[str] = []
    monkeypatch.setattr(
        peri_scribe.external_sources.logger,
        "warning",
        warnings.append,
    )
    peri_scribe.external_sources.fetch_external_source(source, YEAR_DIRECTORY)
    assert warnings == ["warning text"]


def testfetch_arcgis_source_skips_when_content_unchanged(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.external_sources.EVACUATIONS_SOURCE
    install_arcgis_query_stubs(monkeypatch, sample_arcgis_dataframe())

    first = peri_scribe.external_sources.fetch_external_source(source, tmp_path)
    assert len(first) == 1
    assert first[0].name == f"000000,lastEdit={SAMPLE_LAST_EDIT_TIMESTAMP}.gpkg"
    second = peri_scribe.external_sources.fetch_external_source(source, tmp_path)
    assert second == first
    snapshots = list((tmp_path / "sources" / "evacuations").rglob("*.gpkg"))
    assert len(snapshots) == 1


def testfetch_arcgis_source_writes_new_snapshot_when_content_changed(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.external_sources.EVACUATIONS_SOURCE
    install_arcgis_query_stubs(monkeypatch, sample_arcgis_dataframe())
    first = peri_scribe.external_sources.fetch_external_source(source, tmp_path)[0]
    changed = sample_arcgis_dataframe()
    changed.loc[0, "OBJECTID"] = 99
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "geo_data_frame_from",
        lambda *_arguments: changed,
    )
    second = peri_scribe.external_sources.fetch_external_source(source, tmp_path)[0]
    assert second != first
    assert second.name == f"000001,lastEdit={SAMPLE_LAST_EDIT_TIMESTAMP}.gpkg"
    snapshot_names = {
        path.name for path in (tmp_path / "sources" / "evacuations").rglob("*.gpkg")
    }
    assert snapshot_names == {
        f"000000,lastEdit={SAMPLE_LAST_EDIT_TIMESTAMP}.gpkg",
        f"000001,lastEdit={SAMPLE_LAST_EDIT_TIMESTAMP}.gpkg",
    }


def testfetch_arcgis_source_writes_snapshot_when_latest_unreadable(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.external_sources.EVACUATIONS_SOURCE
    install_arcgis_query_stubs(monkeypatch, sample_arcgis_dataframe())
    first = peri_scribe.external_sources.fetch_external_source(source, tmp_path)[0]
    first.write_bytes(b"not a geopackage")
    second = peri_scribe.external_sources.fetch_external_source(source, tmp_path)[0]
    assert second != first
    assert second.name == f"000001,lastEdit={SAMPLE_LAST_EDIT_TIMESTAMP}.gpkg"


def testfetch_arcgis_source_uses_current_time_when_timestamp_unobservable(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.external_sources.EVACUATIONS_SOURCE
    install_arcgis_query_stubs(monkeypatch, sample_arcgis_dataframe())
    monkeypatch.setattr(
        peri_scribe.feed_types,
        "observe_layer_last_edit_timestamp",
        lambda _url, _name: None,
    )
    monkeypatch.setattr(
        peri_scribe.external_sources.time,
        "time_ns",
        lambda: 1_700_000_000_123_456_789,
    )
    result = peri_scribe.external_sources.fetch_external_source(source, tmp_path)[0]
    assert result.name == "000000,lastEdit=1700000000123.gpkg"


def testdownload_links_parses_github_page_table() -> None:
    links = {
        "California": (
            "https://minedbuildings.z5.web.core.windows.net/legacy/"
            "usbuildings-v2/California.geojson.zip"
        ),
        "New Hampshire": (
            "https://minedbuildings.z5.web.core.windows.net/legacy/"
            "usbuildings-v2/NewHampshire.geojson.zip"
        ),
    }
    page = buildings_page_html(links)
    assert peri_scribe.external_sources.download_links(page) == links


def testdownload_links_matches_downloads_links_heading() -> None:
    page = buildings_page_html(
        {"California": "https://example.com/California.geojson.zip"},
    ).replace("Download links", "Downloads links")
    assert peri_scribe.external_sources.download_links(page) == {
        "California": "https://example.com/California.geojson.zip",
    }


def testbuildings_state_urls_reads_repo_page_every_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    links = {
        state: f"https://example.com/{state.replace(' ', '')}.geojson.zip"
        for state in peri_scribe.external_sources.BUILDINGS_STATES
    }
    urls: list[str] = []
    monkeypatch.setattr(
        peri_scribe.external_sources.requests,
        "get",
        lambda url, **_kwargs: (
            urls.append(url) or FakeResponse(buildings_page_html(links).encode("utf-8"))
        ),
    )

    result = peri_scribe.external_sources.buildings_state_urls()
    assert urls == ["https://github.com/microsoft/USBuildingFootprints"]
    assert result == links
    assert result["New Hampshire"] == ("https://example.com/NewHampshire.geojson.zip")


def testbuildings_state_urls_raises_when_page_has_nodownload_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.external_sources.requests,
        "get",
        lambda _url, **_kwargs: FakeResponse(b"<html><body><p>hi</p></body></html>"),
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="No download links found",
    ):
        peri_scribe.external_sources.buildings_state_urls()


def testbuildings_state_urls_raises_when_a_state_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = buildings_page_html(
        {"California": "https://example.com/California.geojson.zip"},
    )
    monkeypatch.setattr(
        peri_scribe.external_sources.requests,
        "get",
        lambda _url, **_kwargs: FakeResponse(page.encode("utf-8")),
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="No download link for Alabama",
    ):
        peri_scribe.external_sources.buildings_state_urls()


def testbuildings_state_urls_raises_when_page_cannot_be_downloaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_url: str, **_kwargs: object) -> typing.Never:
        message = "boom"
        raise peri_scribe.external_sources.requests.exceptions.RequestException(
            message,
        )

    monkeypatch.setattr(
        peri_scribe.external_sources.requests,
        "get",
        fail,
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match=(
            r"Failed to download https://github\.com/microsoft/USBuildingFootprints: "
            r"boom"
        ),
    ):
        peri_scribe.external_sources.buildings_state_urls()


def test_fetch_buildings_combines_state_centroids_into_single_geopackage(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = dataclasses.replace(
        peri_scribe.external_sources.BUILDINGS_SOURCE,
        states=("California", "Texas"),
    )
    links = {
        state: (
            "https://minedbuildings.z5.web.core.windows.net/legacy/"
            f"usbuildings-v2/{state.replace(' ', '')}.geojson.zip"
        )
        for state in peri_scribe.external_sources.BUILDINGS_STATES
    }
    page = buildings_page_html(links)
    archive = archive_zip_bytes(
        filename="California.geojson",
        dataframe=building_dataframe(),
        driver="GeoJSON",
    )
    urls: list[str] = []

    def get(url: str, **_kwargs: object) -> FakeResponse:
        urls.append(url)
        if url == peri_scribe.external_sources.BUILDINGS_SOURCE.url:
            return FakeResponse(page.encode("utf-8"))
        return FakeResponse(archive)

    monkeypatch.setattr(
        peri_scribe.external_sources.requests,
        "get",
        get,
    )

    result = peri_scribe.external_sources.fetch_external_source(source, tmp_path)
    output = peri_scribe.external_sources.output_path(tmp_path, source)
    assert result == (output,)
    assert urls == [
        peri_scribe.external_sources.BUILDINGS_SOURCE.url,
        links["California"],
        links["Texas"],
    ]
    directory = peri_scribe.external_sources.source_directory_path(tmp_path, source)
    assert sorted(path.name for path in directory.iterdir()) == ["buildings.gpkg"]

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
        peri_scribe.external_sources.BUILDINGS_SOURCE,
        states=("California",),
    )
    links = {
        state: (
            "https://minedbuildings.z5.web.core.windows.net/legacy/"
            f"usbuildings-v2/{state.replace(' ', '')}.geojson.zip"
        )
        for state in peri_scribe.external_sources.BUILDINGS_STATES
    }
    page = buildings_page_html(links)
    archive = archive_zip_bytes(
        filename="California.geojson",
        dataframe=building_dataframe(),
        driver="GeoJSON",
    )
    urls: list[str] = []

    def get(url: str, **_kwargs: object) -> FakeResponse:
        urls.append(url)
        if url == peri_scribe.external_sources.BUILDINGS_SOURCE.url:
            return FakeResponse(page.encode("utf-8"))
        return FakeResponse(archive)

    monkeypatch.setattr(
        peri_scribe.external_sources.requests,
        "get",
        get,
    )

    first = peri_scribe.external_sources.fetch_external_source(source, tmp_path)
    second = peri_scribe.external_sources.fetch_external_source(source, tmp_path)
    assert second == first
    assert urls == [
        peri_scribe.external_sources.BUILDINGS_SOURCE.url,
        links["California"],
    ]


def test_fetch_buildings_combines_projected_centroids_into_wgs84(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = dataclasses.replace(
        peri_scribe.external_sources.BUILDINGS_SOURCE,
        states=("California",),
        state_urls=None,
        url="https://example.com/legacy/{state}.geojson.zip",
        geodata_suffix=".shp",
    )
    dataframe = geopandas.GeoDataFrame(
        {"OBJECTID": [1]},
        geometry=[shapely.geometry.box(0.0, 0.0, 2.0, 2.0)],
        crs=f"EPSG:{WEB_MERCATOR_WKID}",
    )
    archive = archive_zip_bytes(
        filename="California.shp",
        dataframe=dataframe,
        driver="ESRI Shapefile",
    )
    monkeypatch.setattr(
        peri_scribe.external_sources.requests,
        "get",
        lambda _url, **_kwargs: FakeResponse(archive),
    )

    result = peri_scribe.external_sources.fetch_external_source(source, tmp_path)
    output = peri_scribe.external_sources.output_path(tmp_path, source)
    assert result == (output,)
    converted = geopandas.read_file(output, layer="buildings")
    assert list(converted.columns) == ["geometry"]
    assert converted.geometry.geom_type.iloc[0] == "Point"
    assert converted.crs.to_epsg() == peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID
    lon, lat = pyproj.Transformer.from_crs(
        WEB_MERCATOR_WKID,
        4326,
        always_xy=True,
    ).transform(1.0, 1.0)
    assert converted.geometry.iloc[0].x == pytest.approx(lon, abs=1e-12)
    assert converted.geometry.iloc[0].y == pytest.approx(lat, abs=1e-12)


def wui_dataframe() -> geopandas.GeoDataFrame:
    """Return a small WUI dataframe for a file-geodatabase conversion test.

    Returns:
        Two polygon features with CLASS attributes in WGS84.
    """
    return geopandas.GeoDataFrame(
        {"CLASS": ["WUI1", "WUI2"]},
        geometry=[
            shapely.geometry.box(0.0, 0.0, 1.0, 1.0),
            shapely.geometry.box(5.0, 5.0, 6.0, 6.0),
        ],
        crs="EPSG:4326",
    )


def wui_archive_zip_bytes() -> bytes:
    """Build an in-memory zip holding a file geodatabase directory.

    Returns:
        The zip archive's bytes, containing a ``.gdb`` directory with one file.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "US_WUI_block_1990_2020_change_v4.gdb/a00000001.gdbtable",
            b"",
        )
    return buffer.getvalue()


def install_wui_read_stub(
    monkeypatch: pytest.MonkeyPatch,
    read_paths: list[pathlib.Path],
) -> None:
    """Serve a stand-in GeoDataFrame when the WUI geodatabase is read.

    The local GDAL build cannot write a real file geodatabase, so the conversion is
    exercised by standing in for the read of the ``.gdb`` directory while all other
    reads (including the test's own assertions) use the real reader.

    Args:
        monkeypatch: The monkeypatch fixture.
        read_paths: Receives each path read as a file geodatabase.
    """
    real_read_file = peri_scribe.external_sources.geopandas.read_file

    def fake_read_file(
        path: object,
        *,
        max_features: int | None = None,
        skip_features: int = 0,
        **_kwargs: object,
    ) -> object:
        geodata_path = pathlib.Path(str(path))
        if geodata_path.name.endswith(".gdb"):
            read_paths.append(geodata_path)
            dataframe = wui_dataframe()
            if max_features is not None:
                dataframe = dataframe.iloc[skip_features : skip_features + max_features]
            return dataframe
        return real_read_file(geodata_path, **_kwargs)

    monkeypatch.setattr(
        peri_scribe.external_sources.geopandas,
        "read_file",
        fake_read_file,
    )


def test_fetch_wui_converts_file_geodatabase_archive_to_geopackage(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.external_sources.WUI_SOURCE
    read_paths: list[pathlib.Path] = []
    install_wui_read_stub(monkeypatch, read_paths)
    archive = wui_archive_zip_bytes()
    monkeypatch.setattr(
        peri_scribe.external_sources.requests,
        "get",
        lambda _url, **_kwargs: FakeResponse(archive),
    )

    result = peri_scribe.external_sources.fetch_external_source(source, tmp_path)
    output = peri_scribe.external_sources.output_path(tmp_path, source)
    assert result == (output,)
    assert read_paths
    assert read_paths[0].name == "US_WUI_block_1990_2020_change_v4.gdb"
    directory = peri_scribe.external_sources.source_directory_path(tmp_path, source)
    assert not (directory / "US_WUI_block_1990_2020_change_v4_gdb.zip").exists()
    converted = geopandas.read_file(output, layer="wui")
    assert list(converted.geometry.geom_type) == ["Polygon", "Polygon"]
    assert list(converted["CLASS"]) == ["WUI1", "WUI2"]


def testdownload_source_raises_when_geodata_cannot_be_read(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = per_state_template_source()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("California.geojson", "not valid geojson {{{ ")
    monkeypatch.setattr(
        peri_scribe.external_sources.requests,
        "get",
        lambda _url, **_kwargs: FakeResponse(buffer.getvalue()),
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="Failed to read",
    ):
        peri_scribe.external_sources.fetch_external_source(source, tmp_path)


def testdownload_source_raises_when_download_fails(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = per_state_template_source()

    def fail(_url: str, **_kwargs: object) -> typing.Never:
        message = "boom"
        raise peri_scribe.external_sources.requests.exceptions.RequestException(
            message,
        )

    monkeypatch.setattr(
        peri_scribe.external_sources.requests,
        "get",
        fail,
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="Failed to download",
    ):
        peri_scribe.external_sources.fetch_external_source(source, tmp_path)


def testdownload_source_raises_when_not_a_zip(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = per_state_template_source()
    monkeypatch.setattr(
        peri_scribe.external_sources.requests,
        "get",
        lambda _url, **_kwargs: FakeResponse(b"not a zip"),
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="is not a zip file",
    ):
        peri_scribe.external_sources.fetch_external_source(source, tmp_path)


def testdownload_source_raises_when_archive_has_no_geodata(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = per_state_template_source()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "hi")
    monkeypatch.setattr(
        peri_scribe.external_sources.requests,
        "get",
        lambda _url, **_kwargs: FakeResponse(buffer.getvalue()),
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match=r"No \.geojson data found",
    ):
        peri_scribe.external_sources.fetch_external_source(source, tmp_path)


def testdownload_source_skips_when_output_present(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = per_state_template_source()
    archive = archive_zip_bytes(
        filename="California.geojson",
        dataframe=building_dataframe(),
        driver="GeoJSON",
    )
    calls: list[str] = []
    monkeypatch.setattr(
        peri_scribe.external_sources.requests,
        "get",
        lambda url, **_kwargs: calls.append(url) or FakeResponse(archive),
    )

    first = peri_scribe.external_sources.fetch_external_source(source, tmp_path)
    assert len(calls) == 1
    second = peri_scribe.external_sources.fetch_external_source(source, tmp_path)
    assert second == first
    assert len(calls) == 1


def testdownload_source_skips_when_single_archive_output_present(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.external_sources.WUI_SOURCE
    install_wui_read_stub(monkeypatch, [])
    archive = wui_archive_zip_bytes()
    calls: list[str] = []
    monkeypatch.setattr(
        peri_scribe.external_sources.requests,
        "get",
        lambda url, **_kwargs: calls.append(url) or FakeResponse(archive),
    )

    first = peri_scribe.external_sources.fetch_external_source(source, tmp_path)
    assert len(calls) == 1
    second = peri_scribe.external_sources.fetch_external_source(source, tmp_path)
    assert second == first
    assert len(calls) == 1


def test_geojson_feature_chunks_streams_features_in_chunks(
    tmp_path: pathlib.Path,
) -> None:
    dataframe = geopandas.GeoDataFrame(
        {"OBJECTID": [1, 2, 3, 4, 5]},
        geometry=[shapely.geometry.Point(index, 0) for index in range(5)],
        crs="EPSG:4326",
    )
    path = tmp_path / "features.geojson"
    dataframe.to_file(path, driver="GeoJSON")

    chunks = list(
        peri_scribe.external_sources.geojson_feature_chunks(
            path,
            chunk_size=2,
        ),
    )

    assert [len(chunk) for chunk in chunks] == [2, 2, 1]
    assert [chunk.iloc[0]["OBJECTID"] for chunk in chunks] == [1, 3, 5]
    assert all(
        chunk.crs.to_epsg() == peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID
        for chunk in chunks
    )


def test_geojson_feature_chunks_keeps_missing_geometry(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "features.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"OBJECTID": 1},
                        "geometry": None,
                    },
                ],
            },
        ),
    )

    chunks = list(
        peri_scribe.external_sources.geojson_feature_chunks(
            path,
            chunk_size=2,
        ),
    )

    assert len(chunks) == 1
    assert chunks[0].geometry.iloc[0] is None


def test_geojson_chunk_dataframe_unions_property_columns() -> None:
    frame = peri_scribe.external_sources.geojson_chunk_dataframe(
        [
            shapely.geometry.Point(0.0, 0.0),
            shapely.geometry.Point(1.0, 1.0),
        ],
        [{"a": 1}, {"b": 2}],
    )

    assert list(frame.columns) == ["a", "b", "geometry"]
    assert frame.iloc[0]["a"] == pytest.approx(1)
    assert bool(pd.isna(frame.iloc[1]["a"]))


def test_geodata_chunks_reads_non_geojson_in_chunks(
    tmp_path: pathlib.Path,
) -> None:
    dataframe = geopandas.GeoDataFrame(
        {"a": [1, 2, 3]},
        geometry=[shapely.geometry.Point(index, 0) for index in range(3)],
        crs="EPSG:4326",
    )
    path = tmp_path / "features.gpkg"
    dataframe.to_file(path, layer="features")

    chunks = list(
        peri_scribe.external_sources.geodata_chunks(
            path,
            chunk_size=2,
        ),
    )

    assert [len(chunk) for chunk in chunks] == [2, 1]
    assert [chunk.iloc[0]["a"] for chunk in chunks] == [1, 3]


def test_convert_to_geopackage_streams_centroids_in_chunks(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.external_sources,
        "CONVERSION_CHUNK_SIZE",
        2,
    )
    dataframe = geopandas.GeoDataFrame(
        {"OBJECTID": [1, 2, 3, 4, 5]},
        geometry=[
            shapely.geometry.box(index, index, index + 1, index + 1)
            for index in range(5)
        ],
        crs="EPSG:4326",
    )
    geodata_path = tmp_path / "California.geojson"
    dataframe.to_file(geodata_path, driver="GeoJSON")
    output = tmp_path / "buildings.gpkg"

    peri_scribe.external_sources.convert_to_geopackage(
        geodata_path,
        output,
        "buildings",
        centroids=True,
        keep_attributes=False,
    )

    converted = geopandas.read_file(output, layer="buildings")
    assert list(converted.columns) == ["geometry"]
    assert list(converted.geometry.geom_type) == ["Point"] * 5
    assert sorted(converted.geometry.x) == pytest.approx(
        [0.5, 1.5, 2.5, 3.5, 4.5],
    )


def test_convert_to_geopackage_keeps_attributes_across_chunks(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.external_sources,
        "CONVERSION_CHUNK_SIZE",
        2,
    )
    dataframe = geopandas.GeoDataFrame(
        {"OBJECTID": [1, 2, 3]},
        geometry=[
            shapely.geometry.box(index, index, index + 1, index + 1)
            for index in range(3)
        ],
        crs="EPSG:4326",
    )
    geodata_path = tmp_path / "California.geojson"
    dataframe.to_file(geodata_path, driver="GeoJSON")
    output = tmp_path / "out.gpkg"

    peri_scribe.external_sources.convert_to_geopackage(
        geodata_path,
        output,
        "out",
        centroids=False,
        keep_attributes=True,
    )

    converted = geopandas.read_file(output, layer="out")
    assert list(converted["OBJECTID"]) == [1, 2, 3]
    assert list(converted.geometry.geom_type) == ["Polygon"] * 3


def test_convert_to_geopackage_writes_empty_layer_for_empty_source(
    tmp_path: pathlib.Path,
) -> None:
    geodata_path = tmp_path / "empty.geojson"
    geodata_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": []}),
    )
    output = tmp_path / "buildings.gpkg"

    peri_scribe.external_sources.convert_to_geopackage(
        geodata_path,
        output,
        "buildings",
        centroids=True,
        keep_attributes=False,
    )

    assert output.is_file()
    assert geopandas.read_file(output, layer="buildings").empty


def test_dataframe_digest_ignores_row_order() -> None:
    dataframe = sample_arcgis_dataframe()
    reversed_dataframe = dataframe.iloc[::-1].reset_index(drop=True)
    digest = peri_scribe.external_sources.dataframe_digest
    assert digest(dataframe) == digest(reversed_dataframe)


def test_dataframe_digest_differs_for_different_geometry() -> None:
    first = sample_arcgis_dataframe()
    second = sample_arcgis_dataframe()
    second.loc[0, "geometry"] = shapely.geometry.Point(9.0, 9.0)
    digest = peri_scribe.external_sources.dataframe_digest
    assert digest(first) != digest(second)


def test_dataframe_digest_treats_missing_values_equally() -> None:
    def frame(missing: object) -> geopandas.GeoDataFrame:
        return geopandas.GeoDataFrame(
            {"value": pd.array([1, missing], dtype=object)},
            geometry=[
                shapely.geometry.Point(0.0, 0.0),
                shapely.geometry.Point(1.0, 1.0),
            ],
            crs="EPSG:4326",
        )

    digest = peri_scribe.external_sources.dataframe_digest
    baseline = digest(frame(None))
    assert digest(frame(float("nan"))) == baseline
    assert digest(frame(pd.NA)) == baseline
    assert digest(frame(pd.NaT)) == baseline


def test_dataframe_digest_covers_every_attribute_kind() -> None:
    dataframe = geopandas.GeoDataFrame(
        {
            "a": ["x", "y"],
            "b": [True, False],
            "c": [1.5, 2.5],
            "d": [1, 2],
            "e": [
                datetime.datetime(2026, 1, 1),
                datetime.datetime(2026, 1, 2),
            ],
            "f": [b"\x01", b"\x02"],
            "g": [
                shapely.geometry.Point(5.0, 5.0),
                shapely.geometry.Point(6.0, 6.0),
            ],
            "h": [{"k": 1}, {"k": 2}],
        },
        geometry=[
            shapely.geometry.Point(0.0, 0.0),
            shapely.geometry.Point(1.0, 1.0),
        ],
        crs="EPSG:4326",
    )
    digest = peri_scribe.external_sources.dataframe_digest(dataframe)
    assert isinstance(digest, str)
    assert len(digest) == len(hashlib.sha256(b"x").hexdigest())
