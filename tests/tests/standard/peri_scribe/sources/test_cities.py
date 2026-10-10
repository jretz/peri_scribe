"""Exercise city source selection, authenticated reuse, and failed refresh recovery."""

from __future__ import annotations

import contextlib
import json
import pathlib
import sqlite3
import typing

import geopandas
import pydantic
import pytest
import requests
import shapely.geometry

import peri_scribe.exceptions
import peri_scribe.sources.catalog
import peri_scribe.sources.cities
import peri_scribe.sources.external_sources
import spatial_data.reference
import tests.helpers.doubles.errors
import tests.helpers.doubles.peri_scribe.sources.cities
import tests.helpers.factories.peri_scribe.sources.cities


if typing.TYPE_CHECKING:
    import structlog.testing


def test_city_database_path_uses_source_sqlite(tmp_path: pathlib.Path) -> None:
    assert peri_scribe.sources.cities.city_database_path(tmp_path) == (
        tmp_path / "sources" / "cities.sqlite"
    )


def test_contents_digest_ignores_order_and_keeps_every_operational_field() -> None:
    first = tests.helpers.factories.peri_scribe.sources.cities.city()
    second = tests.helpers.factories.peri_scribe.sources.cities.city(name="Other")
    digest = peri_scribe.sources.cities.contents_digest((first, second))
    assert digest == peri_scribe.sources.cities.contents_digest((second, first))
    for change in (
        {"name": "Renamed"},
        {"state": "NV"},
        {"longitude": -118.0},
        {"latitude": 36.0},
    ):
        assert digest != peri_scribe.sources.cities.contents_digest((
            first.model_copy(update=change),
            second,
        ))
    assert digest != peri_scribe.sources.cities.contents_digest((first, second, first))


@pytest.mark.parametrize("records", [(), ("  ", "CA"), ("City", "ZZ")])
def test_validate_cities_rejects_unusable_names_and_empty_data(
    records: tuple[()] | tuple[str, str],
) -> None:
    cities = (
        (
            tests.helpers.factories.peri_scribe.sources.cities.city(
                name=records[0],
                state=records[1],
            ),
        )
        if records
        else ()
    )
    with pytest.raises(ValueError, match="nonempty place names"):
        peri_scribe.sources.cities.validate_cities(cities)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("latitude", float("nan")),
        ("latitude", 91.0),
        ("longitude", float("inf")),
        ("longitude", -181.0),
    ],
)
def test_city_rejects_nonfinite_or_out_of_range_coordinates(
    field: str,
    value: float,
) -> None:
    values = tests.helpers.factories.peri_scribe.sources.cities.city().model_dump()
    values[field] = value
    with pytest.raises(pydantic.ValidationError):
        peri_scribe.sources.cities.City.model_validate(values)


def test_archive_cities_includes_states_dc_and_territories_using_geometry() -> None:
    version, cities = peri_scribe.sources.cities.archive_cities(
        tests.helpers.factories.peri_scribe.sources.cities.archive(),
    )
    assert version == "5.1.2"
    assert [city.state for city in cities] == ["CA", "DC", "AS", "GU", "MP", "PR", "VI"]
    assert [city.longitude for city in cities] == list(range(-119, -112))
    assert [city.latitude for city in cities] == pytest.approx([35.0] * len(cities))


@pytest.mark.parametrize(
    "geometry",
    [None, shapely.geometry.Point(), shapely.geometry.LineString([(1, 2), (3, 4)])],
)
def test_archive_cities_rejects_missing_empty_and_nonpoint_geometry(
    geometry: shapely.geometry.base.BaseGeometry | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tests.helpers.factories.peri_scribe.sources.cities.archive()
    dataframe = tests.helpers.factories.peri_scribe.sources.cities.dataframe()
    dataframe.loc[0, "geometry"] = geometry
    monkeypatch.setattr(geopandas, "read_file", lambda *_args: dataframe)
    with pytest.raises(ValueError, match="nonempty point"):
        peri_scribe.sources.cities.archive_cities(archive)


def test_load_database_round_trips_exact_fields_and_metadata(
    tmp_path: pathlib.Path,
) -> None:
    database = tests.helpers.factories.peri_scribe.sources.cities.database()
    path = tmp_path / "cities.sqlite"
    peri_scribe.sources.cities.write_database(path, database)
    assert (
        peri_scribe.sources.cities.load_database(path, database.metadata.source_url)
        == database
    )
    with contextlib.closing(sqlite3.connect(path)) as connection, connection:
        assert [row[1] for row in connection.execute("PRAGMA table_info(cities)")] == [
            "name",
            "state",
            "longitude",
            "latitude",
        ]


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM metadata",
        "INSERT INTO metadata SELECT * FROM metadata",
        "UPDATE cities SET longitude = -118",
        "UPDATE cities SET state = 'ZZ'",
        "DELETE FROM cities",
        "UPDATE metadata SET document = '{}'",
    ],
)
def test_read_database_rejects_corrupt_contents_or_metadata(
    tmp_path: pathlib.Path,
    statement: str,
) -> None:
    database = tests.helpers.factories.peri_scribe.sources.cities.database()
    path = tmp_path / "cities.sqlite"
    peri_scribe.sources.cities.write_database(path, database)
    with contextlib.closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(statement)
    assert (
        peri_scribe.sources.cities.read_database(path, database.metadata.source_url)
        is None
    )


@pytest.mark.parametrize(
    "change",
    [
        {"source_url": "https://example.com/other.zip"},
        {"schema_version": 99},
        {"source_version": "unknown"},
        {"archive_sha256": "bad"},
    ],
)
def test_read_database_rejects_incompatible_generation(
    tmp_path: pathlib.Path,
    change: dict[str, object],
) -> None:
    database = tests.helpers.factories.peri_scribe.sources.cities.database()
    path = tmp_path / "cities.sqlite"
    peri_scribe.sources.cities.write_database(path, database)
    metadata = database.metadata.model_dump() | change
    with contextlib.closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("UPDATE metadata SET document = ?", (json.dumps(metadata),))
    assert (
        peri_scribe.sources.cities.read_database(path, database.metadata.source_url)
        is None
    )


def test_read_database_rejects_non_database_bytes(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "cities.sqlite"
    path.write_bytes(b"broken")
    assert peri_scribe.sources.cities.read_database(path, "https://example.com") is None


def test_read_cities_missing_cache_returns_typed_empty_frame(
    tmp_path: pathlib.Path,
) -> None:
    frame = peri_scribe.sources.cities.read_cities(tmp_path)
    assert frame.empty
    assert list(frame.columns) == ["NAME", "STATE_ABBR", "geometry"]
    assert frame.crs.to_epsg() == spatial_data.reference.WGS84_SPATIAL_REFERENCE_ID
    assert peri_scribe.sources.cities.database_digest(tmp_path) is None


def test_read_cities_and_database_digest_use_validated_generation(
    tmp_path: pathlib.Path,
) -> None:
    database = tests.helpers.factories.peri_scribe.sources.cities.database()
    peri_scribe.sources.cities.publish_database(
        peri_scribe.sources.cities.city_database_path(tmp_path),
        database,
    )
    frame = peri_scribe.sources.cities.read_cities(tmp_path)
    assert frame["NAME"].tolist() == ["Bakersfield"]
    assert frame["STATE_ABBR"].tolist() == ["CA"]
    assert frame.geometry.tolist() == [shapely.geometry.Point(-119, 35)]
    assert (
        peri_scribe.sources.cities.database_digest(tmp_path)
        == database.metadata.contents_sha256
    )


@pytest.mark.parametrize(
    ("etag", "last_modified", "expected"),
    [
        ('"first"', "yesterday", {"If-None-Match": '"first"'}),
        (None, "yesterday", {"If-Modified-Since": "yesterday"}),
        (None, None, {}),
    ],
)
def test_conditional_headers_prefers_etag_then_modification_time(
    etag: str | None,
    last_modified: str | None,
    expected: dict[str, str],
) -> None:
    database = tests.helpers.factories.peri_scribe.sources.cities.database(
        etag=etag,
        last_modified=last_modified,
    )
    assert peri_scribe.sources.cities.conditional_headers(database) == expected


def test_fetch_cities_database_checks_every_fetch_and_reuses_304(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.sources.catalog.CITIES_SOURCE
    responder = tests.helpers.doubles.peri_scribe.sources.cities.install(
        monkeypatch,
        tests.helpers.doubles.peri_scribe.sources.cities.response(
            tests.helpers.factories.peri_scribe.sources.cities.archive(),
            headers={"ETag": '"one"', "Last-Modified": "yesterday"},
        ),
        tests.helpers.doubles.peri_scribe.sources.cities.response(status=304),
    )
    (path,) = peri_scribe.sources.external_sources.fetch_external_source(
        source,
        tmp_path,
    )
    before = path.read_bytes(), path.stat().st_mtime_ns
    assert peri_scribe.sources.cities.fetch_cities_database(source, tmp_path) == (path,)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert [headers for _, headers, _ in responder.calls] == [
        {},
        {"If-None-Match": '"one"'},
    ]


def test_fetch_cities_database_replaces_all_rows_on_new_download(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.sources.catalog.CITIES_SOURCE
    path = peri_scribe.sources.cities.city_database_path(tmp_path)
    peri_scribe.sources.cities.publish_database(
        path,
        tests.helpers.factories.peri_scribe.sources.cities.database(),
    )
    dataframe = (
        tests.helpers.factories.peri_scribe.sources.cities.dataframe().iloc[:1].copy()
    )
    dataframe.loc[0, "name"] = "Replacement"
    tests.helpers.doubles.peri_scribe.sources.cities.install(
        monkeypatch,
        tests.helpers.doubles.peri_scribe.sources.cities.response(
            tests.helpers.factories.peri_scribe.sources.cities.archive(
                dataframe,
                version="5.2.0",
            ),
        ),
    )
    peri_scribe.sources.cities.fetch_cities_database(source, tmp_path)
    database = peri_scribe.sources.cities.load_database(path, source.url)
    assert [city.name for city in database.cities] == ["Replacement"]
    assert database.metadata.source_version == "5.2.0"
    assert database.metadata.etag is None


def test_fetch_cities_database_rebuilds_unusable_cache_unconditionally(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.sources.catalog.CITIES_SOURCE
    path = peri_scribe.sources.cities.city_database_path(tmp_path)
    path.parent.mkdir()
    path.write_bytes(b"not a database")
    responder = tests.helpers.doubles.peri_scribe.sources.cities.install(
        monkeypatch,
        tests.helpers.doubles.peri_scribe.sources.cities.response(
            tests.helpers.factories.peri_scribe.sources.cities.archive(),
        ),
    )
    peri_scribe.sources.cities.fetch_cities_database(source, tmp_path)
    assert responder.calls[0][1] == {}
    assert peri_scribe.sources.cities.database_digest(tmp_path) is not None


def test_fetch_cities_database_metadata_changes_preserve_publication_digest(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.sources.catalog.CITIES_SOURCE
    tests.helpers.doubles.peri_scribe.sources.cities.install(
        monkeypatch,
        tests.helpers.doubles.peri_scribe.sources.cities.response(
            tests.helpers.factories.peri_scribe.sources.cities.archive(),
            headers={"Last-Modified": "yesterday"},
        ),
        tests.helpers.doubles.peri_scribe.sources.cities.response(
            tests.helpers.factories.peri_scribe.sources.cities.archive(version="5.2.0"),
            headers={"ETag": '"updated"'},
        ),
    )
    (path,) = peri_scribe.sources.cities.fetch_cities_database(source, tmp_path)
    before = peri_scribe.sources.cities.load_database(path, source.url)
    peri_scribe.sources.cities.fetch_cities_database(source, tmp_path)
    after = peri_scribe.sources.cities.load_database(path, source.url)
    assert before.metadata.contents_sha256 == after.metadata.contents_sha256
    assert before.metadata.archive_sha256 != after.metadata.archive_sha256
    assert after.metadata.etag == '"updated"'
    assert after.metadata.source_version == "5.2.0"


@pytest.mark.parametrize(
    "failure",
    [requests.ConnectionError("offline"), b"bad zip", 503],
)
def test_fetch_cities_database_preserves_valid_cache_on_failure(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    log_output: structlog.testing.LogCapture,
    failure: Exception | bytes | int,
) -> None:
    source = peri_scribe.sources.catalog.CITIES_SOURCE
    path = peri_scribe.sources.cities.city_database_path(tmp_path)
    peri_scribe.sources.cities.publish_database(
        path,
        tests.helpers.factories.peri_scribe.sources.cities.database(),
    )
    original = path.read_bytes()
    outcome = (
        failure
        if isinstance(failure, Exception)
        else tests.helpers.doubles.peri_scribe.sources.cities.response(
            failure if isinstance(failure, bytes) else b"",
            status=failure if isinstance(failure, int) else 200,
        )
    )
    tests.helpers.doubles.peri_scribe.sources.cities.install(monkeypatch, outcome)
    assert peri_scribe.sources.cities.fetch_cities_database(source, tmp_path) == (path,)
    assert path.read_bytes() == original
    warning = next(
        entry
        for entry in log_output.entries
        if "keeping current data" in entry["event"]
    )
    assert "Traceback (most recent call last)" in warning["exception"]


@pytest.mark.parametrize("status", [304, 204, 500])
def test_fetch_cities_database_fails_without_usable_cached_data(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    log_output: structlog.testing.LogCapture,
    status: int,
) -> None:
    tests.helpers.doubles.peri_scribe.sources.cities.install(
        monkeypatch,
        tests.helpers.doubles.peri_scribe.sources.cities.response(status=status),
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="without usable cached",
    ):
        peri_scribe.sources.cities.fetch_cities_database(
            peri_scribe.sources.catalog.CITIES_SOURCE,
            tmp_path,
        )
    assert not peri_scribe.sources.cities.city_database_path(tmp_path).exists()
    assert any(
        "exception" in entry and entry["log_level"] == "error"
        for entry in log_output.entries
    )


def test_publish_database_rejects_mismatched_staged_generation(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = tests.helpers.factories.peri_scribe.sources.cities.database()
    changed = tests.helpers.factories.peri_scribe.sources.cities.database(
        cities=(
            tests.helpers.factories.peri_scribe.sources.cities.city(name="Changed"),
        ),
    )
    path = tmp_path / "cities.sqlite"
    peri_scribe.sources.cities.write_database(path, original)
    before = path.read_bytes()
    monkeypatch.setattr(
        peri_scribe.sources.cities,
        "load_database",
        lambda *_args: original,
    )
    with pytest.raises(ValueError, match="does not match"):
        peri_scribe.sources.cities.publish_database(path, changed)
    assert path.read_bytes() == before


def test_publish_database_preserves_cache_when_atomic_replace_fails(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tests.helpers.factories.peri_scribe.sources.cities.database()
    path = tmp_path / "cities.sqlite"
    peri_scribe.sources.cities.write_database(path, database)
    before = path.read_bytes()
    monkeypatch.setattr(
        pathlib.Path,
        "replace",
        tests.helpers.doubles.errors.raising_stub(OSError("cannot replace")),
    )
    with pytest.raises(OSError, match="cannot replace"):
        peri_scribe.sources.cities.publish_database(path, database)
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]
