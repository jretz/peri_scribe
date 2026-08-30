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
        stream=False,
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


def test_output_path_places_single_file_under_sources() -> None:
    source = dataclasses.replace(
        peri_scribe.external_sources.BUILDINGS_SOURCE,
        states=(),
        combine=False,
    )
    path = peri_scribe.external_sources.output_path(
        YEAR_DIRECTORY,
        source,
    )
    assert path == YEAR_DIRECTORY / "sources" / "buildings.gpkg"


def test_output_path_names_combined_geopackage() -> None:
    path = peri_scribe.external_sources.output_path(
        YEAR_DIRECTORY,
        peri_scribe.external_sources.BUILDINGS_SOURCE,
    )
    assert path == YEAR_DIRECTORY / "sources" / "buildings.gpkg"


def test_output_path_raises_for_combined_source_with_state() -> None:
    with pytest.raises(ValueError, match="combines its states"):
        peri_scribe.external_sources.output_path(
            YEAR_DIRECTORY,
            peri_scribe.external_sources.BUILDINGS_SOURCE,
            state="California",
        )


def test_output_path_names_live_arcgis_source() -> None:
    path = peri_scribe.external_sources.output_path(
        YEAR_DIRECTORY,
        peri_scribe.external_sources.EVACUATIONS_SOURCE,
    )
    assert path == YEAR_DIRECTORY / "sources" / "evacuations.gpkg"


def test_output_path_names_per_state_geopackage() -> None:
    source = dataclasses.replace(
        peri_scribe.external_sources.BUILDINGS_SOURCE,
        states=("California",),
        combine=False,
    )
    path = peri_scribe.external_sources.output_path(
        YEAR_DIRECTORY,
        source,
        state="California",
    )
    assert path == YEAR_DIRECTORY / "sources" / "buildings" / "California.gpkg"


def test_buildings_source_covers_every_us_state() -> None:
    states = peri_scribe.external_sources.BUILDINGS_SOURCE.states
    assert len(states) == len(us.states.STATES) + 1
    assert "California" in states
    assert "District of Columbia" in states


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
    replacements: list[tuple[pathlib.Path, pathlib.Path]] = []
    monkeypatch.setattr(
        pathlib.Path,
        "replace",
        lambda source, destination: replacements.append((source, destination)),
    )
    monkeypatch.setattr(
        pathlib.Path,
        "mkdir",
        lambda *_arguments, **_keywords: None,
    )

    result = peri_scribe.external_sources.fetch_external_source(source, YEAR_DIRECTORY)
    expected = YEAR_DIRECTORY / "sources" / "evacuations.gpkg"
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
    assert written_path == expected.with_name("evacuations.tmp.gpkg")
    assert replacements == [(written_path, expected)]
    assert [layer.name for layer in layer_data] == ["evacuations"]


def testfetch_arcgis_source_passes_where_clause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = dataclasses.replace(
        peri_scribe.external_sources.EVACUATIONS_SOURCE,
        where="Event IN ('Red Flag Warning', 'Fire Weather Watch')",
    )
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
        pathlib.Path,
        "replace",
        lambda _source, _destination: None,
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
        pathlib.Path,
        "replace",
        lambda _source, _destination: None,
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
    assert first[0].name == "evacuations.gpkg"
    assert first[0].parent.name == "sources"
    second = peri_scribe.external_sources.fetch_external_source(source, tmp_path)
    assert second == first
    snapshots = list((tmp_path / "sources").rglob("*.gpkg"))
    assert len(snapshots) == 1


def testfetch_arcgis_source_replaces_current_version_when_content_changed(
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
    assert second == first
    stored = geopandas.read_file(second, layer="evacuations")
    assert stored["OBJECTID"].tolist() == [99, 2]
    snapshot_names = {
        path.name for path in (tmp_path / "sources").rglob("*.gpkg")
    }
    assert snapshot_names == {"evacuations.gpkg"}


def testfetch_arcgis_source_replaces_unreadable_current_version(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.external_sources.EVACUATIONS_SOURCE
    install_arcgis_query_stubs(monkeypatch, sample_arcgis_dataframe())
    first = peri_scribe.external_sources.fetch_external_source(source, tmp_path)[0]
    first.write_bytes(b"not a geopackage")
    second = peri_scribe.external_sources.fetch_external_source(source, tmp_path)[0]
    assert second == first
    stored = geopandas.read_file(second, layer="evacuations")
    assert len(stored) == len(sample_arcgis_dataframe())


def testfetch_arcgis_source_keeps_current_version_when_fetch_fails(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.external_sources.EVACUATIONS_SOURCE
    install_arcgis_query_stubs(monkeypatch, sample_arcgis_dataframe())
    first = peri_scribe.external_sources.fetch_external_source(source, tmp_path)[0]
    assert first.name == "evacuations.gpkg"

    def fail(_url: str, _gis: object) -> typing.Never:
        message = "boom"
        raise RuntimeError(message)

    monkeypatch.setattr(
        peri_scribe.external_sources.arcgis.features,
        "FeatureLayer",
        fail,
    )
    warnings: list[str] = []
    monkeypatch.setattr(
        peri_scribe.external_sources.logger,
        "warning",
        lambda message, **_keywords: warnings.append(message),
    )
    second = peri_scribe.external_sources.fetch_external_source(source, tmp_path)
    assert second == (first,)
    assert any("keeping current data" in message for message in warnings)
    stored = geopandas.read_file(first, layer="evacuations")
    assert len(stored) == len(sample_arcgis_dataframe())


def testfetch_arcgis_source_adopts_newest_legacy_snapshot(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.external_sources.EVACUATIONS_SOURCE
    directory = tmp_path / "sources" / "evacuations"
    legacy_directory = directory / "000___"
    legacy_directory.mkdir(parents=True)
    for serial in (0, 1):
        legacy_name = f"00000{serial},lastEdit={SAMPLE_LAST_EDIT_TIMESTAMP}.gpkg"
        path = legacy_directory / legacy_name
        peri_scribe.output.write_geopackage(
            path,
            [
                peri_scribe.models.LayerData(
                    name="evacuations",
                    dataframe=sample_arcgis_dataframe(),
                ),
            ],
        )
    newest = sample_arcgis_dataframe()
    newest.loc[0, "OBJECTID"] = 99
    newest_path = (
        legacy_directory / f"000002,lastEdit={SAMPLE_LAST_EDIT_TIMESTAMP}.gpkg"
    )
    peri_scribe.output.write_geopackage(
        newest_path,
        [
            peri_scribe.models.LayerData(
                name="evacuations",
                dataframe=newest,
            ),
        ],
    )

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
    warnings: list[str] = []
    monkeypatch.setattr(
        peri_scribe.external_sources.logger,
        "warning",
        lambda message, **_keywords: warnings.append(message),
    )
    result = peri_scribe.external_sources.fetch_external_source(source, tmp_path)
    output = tmp_path / "sources" / "evacuations.gpkg"
    assert result == (output,)
    assert any("keeping current data" in message for message in warnings)
    assert geopandas.read_file(output, layer="evacuations")["OBJECTID"].tolist() == [
        99,
        2,
    ]
    assert not legacy_directory.exists()


def testfetch_arcgis_source_removes_legacy_snapshots_when_current_exists(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.external_sources.EVACUATIONS_SOURCE
    install_arcgis_query_stubs(monkeypatch, sample_arcgis_dataframe())
    first = peri_scribe.external_sources.fetch_external_source(source, tmp_path)[0]
    assert first.name == "evacuations.gpkg"
    legacy_directory = tmp_path / "sources" / "evacuations" / "000___"
    legacy_directory.mkdir(parents=True)
    legacy_path = (
        legacy_directory / f"000000,lastEdit={SAMPLE_LAST_EDIT_TIMESTAMP}.gpkg"
    )
    peri_scribe.output.write_geopackage(
        legacy_path,
        [
            peri_scribe.models.LayerData(
                name="evacuations",
                dataframe=sample_arcgis_dataframe(),
            ),
        ],
    )
    second = peri_scribe.external_sources.fetch_external_source(source, tmp_path)
    assert second == (first,)
    assert not legacy_directory.exists()
    snapshots = list((tmp_path / "sources").rglob("*.gpkg"))
    assert snapshots == [first]


def test_stream_combined_source_requires_centroids_without_attributes(
    tmp_path: pathlib.Path,
) -> None:
    source = dataclasses.replace(
        peri_scribe.external_sources.BUILDINGS_SOURCE,
        states=("California",),
        keep_attributes=True,
    )
    with pytest.raises(ValueError, match="must reduce to centroid points"):
        peri_scribe.external_sources.fetch_external_source(source, tmp_path)


def test_stream_download_and_convert_raises_when_download_fails(
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

    def get(url: str, **_kwargs: object) -> FakeResponse:
        if url == peri_scribe.external_sources.BUILDINGS_SOURCE.url:
            return FakeResponse(page.encode("utf-8"))
        message = "boom"
        raise peri_scribe.external_sources.requests.exceptions.RequestException(
            message,
        )

    monkeypatch.setattr(
        peri_scribe.external_sources.requests,
        "get",
        get,
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="Failed to download",
    ):
        peri_scribe.external_sources.fetch_external_source(source, tmp_path)


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
    sources = peri_scribe.snapshots.sources_directory_path(tmp_path)
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
        stream=False,
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


def single_archive_source() -> peri_scribe.external_sources.ExternalSource:
    """Return the buildings source as a single archive instead of per state.

    The generic single-archive download path is exercised with this source so that
    the skip-when-present behavior can be tested without the per-state machinery.

    Returns:
        A single-archive download source named after the buildings source.
    """
    return dataclasses.replace(
        peri_scribe.external_sources.BUILDINGS_SOURCE,
        states=(),
        combine=False,
        state_urls=None,
        url="https://example.com/buildings.geojson.zip",
    )


def testdownload_source_skips_when_single_archive_output_present(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = single_archive_source()
    archive = archive_zip_bytes(
        filename="buildings.geojson",
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
