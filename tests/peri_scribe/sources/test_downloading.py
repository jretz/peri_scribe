"""Tests for peri_scribe.sources.external_sources."""

from __future__ import annotations

import dataclasses
import io
import pathlib
import typing
import zipfile

import pytest

import peri_scribe.exceptions
import peri_scribe.sources.archives
import peri_scribe.sources.downloading
import peri_scribe.sources.external_sources
import tests.peri_scribe.sources.external_source_helpers


def test_download_source_raises_when_geodata_cannot_be_read(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = (
        tests.peri_scribe.sources.external_source_helpers.per_state_template_source()
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("California.geojson", "not valid geojson {{{ ")
    monkeypatch.setattr(
        peri_scribe.sources.archives.requests,
        "get",
        lambda _url, **_kwargs: (
            tests.peri_scribe.sources.external_source_helpers.FakeResponse(
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
        tests.peri_scribe.sources.external_source_helpers.per_state_template_source()
    )

    def fail(_url: str, **_kwargs: object) -> typing.Never:
        message = "boom"
        raise peri_scribe.sources.archives.requests.exceptions.RequestException(
            message,
        )

    monkeypatch.setattr(
        peri_scribe.sources.archives.requests,
        "get",
        fail,
    )
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
        tests.peri_scribe.sources.external_source_helpers.per_state_template_source()
    )
    monkeypatch.setattr(
        peri_scribe.sources.archives.requests,
        "get",
        lambda _url, **_kwargs: (
            tests.peri_scribe.sources.external_source_helpers.FakeResponse(b"not a zip")
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
        tests.peri_scribe.sources.external_source_helpers.per_state_template_source()
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "hi")
    monkeypatch.setattr(
        peri_scribe.sources.archives.requests,
        "get",
        lambda _url, **_kwargs: (
            tests.peri_scribe.sources.external_source_helpers.FakeResponse(
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
        tests.peri_scribe.sources.external_source_helpers.per_state_template_source()
    )
    archive = tests.peri_scribe.sources.external_source_helpers.archive_zip_bytes(
        filename="California.geojson",
        dataframe=tests.peri_scribe.sources.external_source_helpers.building_dataframe(),
        driver="GeoJSON",
    )
    calls: list[str] = []
    monkeypatch.setattr(
        peri_scribe.sources.archives.requests,
        "get",
        lambda url, **_kwargs: (
            calls.append(url)
            or tests.peri_scribe.sources.external_source_helpers.FakeResponse(archive)
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
    source = tests.peri_scribe.sources.external_source_helpers.single_archive_source()
    archive = tests.peri_scribe.sources.external_source_helpers.archive_zip_bytes(
        filename="buildings.geojson",
        dataframe=tests.peri_scribe.sources.external_source_helpers.building_dataframe(),
        driver="GeoJSON",
    )
    calls: list[str] = []
    monkeypatch.setattr(
        peri_scribe.sources.archives.requests,
        "get",
        lambda url, **_kwargs: (
            calls.append(url)
            or tests.peri_scribe.sources.external_source_helpers.FakeResponse(archive)
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
        peri_scribe.sources.external_sources.BUILDINGS_SOURCE,
        states=("California",),
        keep_attributes=True,
    )
    with pytest.raises(ValueError, match="must reduce to centroid points"):
        peri_scribe.sources.external_sources.fetch_external_source(source, tmp_path)


def test_stream_download_and_convert_raises_when_download_fails(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = dataclasses.replace(
        peri_scribe.sources.external_sources.BUILDINGS_SOURCE,
        states=("California",),
    )
    links = {
        state: (
            "https://minedbuildings.z5.web.core.windows.net/legacy/"
            f"usbuildings-v2/{state.replace(' ', '')}.geojson.zip"
        )
        for state in peri_scribe.sources.external_sources.BUILDINGS_STATES
    }
    page = tests.peri_scribe.sources.external_source_helpers.buildings_page_html(links)

    def get(
        url: str,
        **_kwargs: object,
    ) -> tests.peri_scribe.sources.external_source_helpers.FakeResponse:
        if url == peri_scribe.sources.external_sources.BUILDINGS_SOURCE.url:
            return tests.peri_scribe.sources.external_source_helpers.FakeResponse(
                page.encode("utf-8"),
            )
        message = "boom"
        raise peri_scribe.sources.downloading.requests.exceptions.RequestException(
            message,
        )

    monkeypatch.setattr(
        peri_scribe.sources.downloading.requests,
        "get",
        get,
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="Failed to download",
    ):
        peri_scribe.sources.external_sources.fetch_external_source(source, tmp_path)
