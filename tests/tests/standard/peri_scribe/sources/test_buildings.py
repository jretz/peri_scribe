"""Tests for peri_scribe.sources.buildings.

The tests use synthetic in-memory archives and temporary databases; they never touch the
network or the real buildings dataset."""

from __future__ import annotations

import dataclasses
import pathlib
import sqlite3

import numpy as np
import pytest
import requests
import shapely.geometry

import peri_scribe.exceptions
import peri_scribe.sources.catalog
import peri_scribe.sources.external_sources
import spatial_data.point_store
import tests.helpers.doubles.errors
import tests.helpers.doubles.peri_scribe.sources.buildings
import tests.helpers.doubles.peri_scribe.sources.external_source
import tests.helpers.factories.peri_scribe.sources.buildings
import tests.helpers.factories.spatial_data.point_store


def test_fetch_buildings_database_streams_states_into_database(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = dataclasses.replace(
        peri_scribe.sources.catalog.BUILDINGS_SOURCE,
        states=("California", "Texas"),
    )
    page = tests.helpers.factories.peri_scribe.sources.buildings.buildings_fetch_page()
    links = {
        state: f"https://example.com/{state.replace(' ', '')}.geojson.zip"
        for state in peri_scribe.sources.catalog.BUILDINGS_STATES
    }
    california = (
        tests.helpers.factories.peri_scribe.sources.buildings.feature_collection_bytes([
            tests.helpers.factories.peri_scribe.sources.buildings.square_ring(0.0, 0.0),
        ])
    )
    texas = (
        tests.helpers.factories.peri_scribe.sources.buildings.feature_collection_bytes([
            tests.helpers.factories.peri_scribe.sources.buildings.square_ring(
                100.5,
                40.25,
            ),
        ])
    )
    archives = {
        "California.geojson.zip": (
            tests.helpers.factories.peri_scribe.sources.buildings
        ).zip_bytes(
            {"California.geojson": california},
        ),
        "Texas.geojson.zip": (
            tests.helpers.factories.peri_scribe.sources.buildings
        ).zip_bytes({
            "Texas.geojson": texas,
            "readme.txt": b"hi",
        }),
    }
    urls: list[str] = []

    get = (
        tests.helpers.doubles.peri_scribe.sources.buildings
    ).make_state_archive_responder(
        urls=urls,
        page=page,
        archives=archives,
    )

    monkeypatch.setattr(requests, "get", get)

    result = peri_scribe.sources.external_sources.fetch_external_source(
        source,
        tmp_path,
    )
    output = tmp_path / "sources" / "buildings.sqlite"
    assert result == (output,)
    assert urls[0] == peri_scribe.sources.catalog.BUILDINGS_SOURCE.url
    assert sorted(urls[1:]) == sorted([links["California"], links["Texas"]])
    assert spatial_data.point_store.is_valid_database(output)
    sources = tmp_path / "sources"
    assert sorted(path.name for path in sources.iterdir()) == ["buildings.sqlite"]
    connection = sqlite3.connect(output)
    try:
        tile_rows = connection.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]
        total = connection.execute(
            "SELECT COALESCE(SUM(building_count), 0) FROM tiles",
        ).fetchone()[0]
    finally:
        connection.close()
    assert tile_rows == len(source.states)
    assert total == len(source.states)
    counts = spatial_data.point_store.point_counts_within(
        [
            shapely.geometry.box(99.0, 39.0, 102.0, 42.0),
            shapely.geometry.box(-1.0, -1.0, 1.0, 1.0),
        ],
        output,
    )
    assert counts == [1, 1]


def test_fetch_buildings_database_skips_valid_existing_database(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "sources" / "buildings.sqlite"
    output.parent.mkdir(parents=True)
    tests.helpers.factories.spatial_data.point_store.write_database(
        np.asarray([[0.2, 0.2]], dtype=float),
        output,
    )
    original = output.read_bytes()
    monkeypatch.setattr(
        requests,
        "get",
        lambda *_args, **_kwargs: pytest.fail("no downloads expected"),
    )

    result = peri_scribe.sources.external_sources.fetch_external_source(
        peri_scribe.sources.catalog.BUILDINGS_SOURCE,
        tmp_path,
    )

    assert result == (output,)
    assert output.read_bytes() == original


def test_fetch_buildings_database_preserves_existing_file_when_download_fails(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "sources" / "buildings.sqlite"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"existing contents")
    monkeypatch.setattr(
        requests,
        "get",
        lambda _url, **_kwargs: (
            tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse(
                b"<html><body><p>hi</p></body></html>",
            )
        ),
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="No download links found",
    ):
        peri_scribe.sources.external_sources.fetch_external_source(
            dataclasses.replace(
                peri_scribe.sources.catalog.BUILDINGS_SOURCE,
                states=("California",),
            ),
            tmp_path,
        )
    assert output.read_bytes() == b"existing contents"


def test_fetch_buildings_database_preserves_existing_file_when_archive_fails(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "sources" / "buildings.sqlite"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"existing contents")

    fail = tests.helpers.doubles.errors.raising_stub(
        requests.exceptions.RequestException("boom"),
    )

    monkeypatch.setattr(requests, "get", fail)
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="Failed to download",
    ):
        peri_scribe.sources.external_sources.fetch_external_source(
            dataclasses.replace(
                peri_scribe.sources.catalog.BUILDINGS_SOURCE,
                states=("California",),
                state_urls=None,
                url="https://example.com/legacy/{state}.geojson.zip",
            ),
            tmp_path,
        )
    assert output.read_bytes() == b"existing contents"


def test_fetch_buildings_database_raises_when_archive_is_not_a_zip(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = dataclasses.replace(
        peri_scribe.sources.catalog.BUILDINGS_SOURCE,
        states=("California",),
        state_urls=None,
        url="https://example.com/legacy/{state}.geojson.zip",
    )
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
    assert not (tmp_path / "sources" / "buildings.sqlite").exists()


def test_fetch_buildings_database_raises_when_geojson_is_unreadable(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = dataclasses.replace(
        peri_scribe.sources.catalog.BUILDINGS_SOURCE,
        states=("California",),
        state_urls=None,
        url="https://example.com/legacy/{state}.geojson.zip",
    )
    archive = tests.helpers.factories.peri_scribe.sources.buildings.zip_bytes({
        "California.geojson": b"not valid geojson {{{ ",
    })
    monkeypatch.setattr(
        requests,
        "get",
        lambda _url, **_kwargs: (
            tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse(
                archive,
            )
        ),
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="Failed to read the streamed GeoJSON",
    ):
        peri_scribe.sources.external_sources.fetch_external_source(source, tmp_path)
    assert not (tmp_path / "sources" / "buildings.sqlite").exists()


def test_fetch_buildings_database_raises_when_generated_database_is_invalid(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = dataclasses.replace(
        peri_scribe.sources.catalog.BUILDINGS_SOURCE,
        states=("California",),
        state_urls=None,
        url="https://example.com/legacy/{state}.geojson.zip",
    )
    california = (
        tests.helpers.factories.peri_scribe.sources.buildings.feature_collection_bytes([
            tests.helpers.factories.peri_scribe.sources.buildings.square_ring(0.0, 0.0),
        ])
    )
    archive = tests.helpers.factories.peri_scribe.sources.buildings.zip_bytes({
        "California.geojson": california,
    })
    monkeypatch.setattr(
        requests,
        "get",
        lambda _url, **_kwargs: (
            tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse(
                archive,
            )
        ),
    )
    monkeypatch.setattr(
        spatial_data.point_store,
        "is_valid_database",
        lambda _path: False,
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="generated buildings database is invalid",
    ):
        peri_scribe.sources.external_sources.fetch_external_source(source, tmp_path)
    assert not (tmp_path / "sources" / "buildings.sqlite").exists()


def test_fetch_buildings_database_raises_when_archive_has_no_geojson(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = dataclasses.replace(
        peri_scribe.sources.catalog.BUILDINGS_SOURCE,
        states=("California",),
        state_urls=None,
        url="https://example.com/legacy/{state}.geojson.zip",
    )
    archive = tests.helpers.factories.peri_scribe.sources.buildings.zip_bytes({
        "readme.txt": b"hi",
    })
    monkeypatch.setattr(
        requests,
        "get",
        lambda _url, **_kwargs: (
            tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse(
                archive,
            )
        ),
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="No GeoJSON data found",
    ):
        peri_scribe.sources.external_sources.fetch_external_source(source, tmp_path)
    assert not (tmp_path / "sources" / "buildings.sqlite").exists()
