"""Tests for peri_scribe.sources.external_sources."""

from __future__ import annotations

import dataclasses
import io
import pathlib
import zipfile

import pytest
import requests

import peri_scribe.exceptions
import peri_scribe.sources.catalog
import peri_scribe.sources.downloading
import peri_scribe.sources.external_sources
import tests.helpers.doubles.errors
import tests.helpers.doubles.peri_scribe.sources.downloading
import tests.helpers.doubles.peri_scribe.sources.external_source
import tests.helpers.factories.peri_scribe.sources.external_source


def test_download_source_raises_when_geodata_cannot_be_read(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = (
        tests.helpers.factories.peri_scribe.sources.external_source
    ).per_state_template_source()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("California.geojson", "not valid geojson {{{ ")
    monkeypatch.setattr(
        requests,
        "get",
        lambda _url, **_kwargs: (
            tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse(
                buffer.getvalue(),
            )
        ),
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="Failed to read",
    ):
        peri_scribe.sources.external_sources.fetch_external_source(source, tmp_path)


def test_download_source_raises_when_download_fails(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = (
        tests.helpers.factories.peri_scribe.sources.external_source
    ).per_state_template_source()

    fail = tests.helpers.doubles.errors.raising_stub(
        requests.exceptions.RequestException("boom"),
    )

    monkeypatch.setattr(requests, "get", fail)
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="Failed to download",
    ):
        peri_scribe.sources.external_sources.fetch_external_source(source, tmp_path)


def test_download_source_raises_when_not_a_zip(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = (
        tests.helpers.factories.peri_scribe.sources.external_source
    ).per_state_template_source()
    monkeypatch.setattr(
        requests,
        "get",
        lambda _url, **_kwargs: (
            tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse(
                b"not a zip",
            )
        ),
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="is not a zip file",
    ):
        peri_scribe.sources.external_sources.fetch_external_source(source, tmp_path)


def test_download_source_raises_when_archive_has_no_geodata(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = (
        tests.helpers.factories.peri_scribe.sources.external_source
    ).per_state_template_source()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "hi")
    monkeypatch.setattr(
        requests,
        "get",
        lambda _url, **_kwargs: (
            tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse(
                buffer.getvalue(),
            )
        ),
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match=r"No \.geojson data found",
    ):
        peri_scribe.sources.external_sources.fetch_external_source(source, tmp_path)


def test_download_source_skips_when_output_present(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = (
        tests.helpers.factories.peri_scribe.sources.external_source
    ).per_state_template_source()
    archive = (
        tests.helpers.factories.peri_scribe.sources.external_source
    ).archive_zip_bytes(
        filename="California.geojson",
        dataframe=(
            tests.helpers.factories.peri_scribe.sources.external_source.building_dataframe()
        ),
        driver="GeoJSON",
    )
    calls: list[str] = []
    monkeypatch.setattr(
        requests,
        "get",
        lambda url, **_kwargs: (
            calls.append(url)
            or tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse(
                archive,
            )
        ),
    )

    first = peri_scribe.sources.external_sources.fetch_external_source(source, tmp_path)
    assert len(calls) == 1
    second = peri_scribe.sources.external_sources.fetch_external_source(
        source,
        tmp_path,
    )
    assert second == first
    assert len(calls) == 1


def test_download_source_skips_when_single_archive_output_present(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = (
        tests.helpers.factories.peri_scribe.sources.external_source
    ).single_archive_source()
    archive = (
        tests.helpers.factories.peri_scribe.sources.external_source
    ).archive_zip_bytes(
        filename="buildings.geojson",
        dataframe=(
            tests.helpers.factories.peri_scribe.sources.external_source.building_dataframe()
        ),
        driver="GeoJSON",
    )
    calls: list[str] = []
    monkeypatch.setattr(
        requests,
        "get",
        lambda url, **_kwargs: (
            calls.append(url)
            or tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse(
                archive,
            )
        ),
    )

    first = peri_scribe.sources.external_sources.fetch_external_source(source, tmp_path)
    assert len(calls) == 1
    second = peri_scribe.sources.external_sources.fetch_external_source(
        source,
        tmp_path,
    )
    assert second == first
    assert len(calls) == 1


def test_stream_combined_source_requires_centroids_without_attributes(
    tmp_path: pathlib.Path,
) -> None:
    source = dataclasses.replace(
        peri_scribe.sources.catalog.BUILDINGS_SOURCE,
        states=("California",),
        keep_attributes=True,
        combine=True,
        stream=True,
        compact_database=False,
    )
    with pytest.raises(ValueError, match="must reduce to centroid points"):
        peri_scribe.sources.external_sources.fetch_external_source(source, tmp_path)


def test_stream_download_and_convert_raises_when_download_fails(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = dataclasses.replace(
        peri_scribe.sources.catalog.BUILDINGS_SOURCE,
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
        for state in peri_scribe.sources.catalog.BUILDINGS_STATES
    }
    page = (
        tests.helpers.factories.peri_scribe.sources.external_source.buildings_page_html(
            links,
        )
    )

    get = (
        tests.helpers.doubles.peri_scribe.sources.downloading
    ).make_failing_archive_responder(
        page=page,
    )

    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="Failed to download",
    ):
        peri_scribe.sources.external_sources.fetch_external_source(source, tmp_path)


def test_stream_download_and_convert_preserves_application_error_contract(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse(
        b"not a zip archive",
    )
    monkeypatch.setattr(requests, "get", lambda _url, **_kwargs: response)
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="The streamed archive is not a zip file",
    ):
        peri_scribe.sources.downloading.stream_download_and_convert(
            "https://example.com/polygons.zip",
            tmp_path / "centroids.gpkg",
            "points",
            append=False,
        )
