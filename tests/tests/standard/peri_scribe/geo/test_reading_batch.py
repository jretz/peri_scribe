"""Feed-wide reads preserve authenticated evidence and caller fallback contracts."""

import contextlib
import dataclasses
import pathlib
import sqlite3
import unittest.mock

import pytest
import shapely

import peri_scribe.geo.database
import peri_scribe.geo.fingerprints
import peri_scribe.geo.package
import peri_scribe.geo.reading
import peri_scribe.sources.snapshots
import spatial_data.geometry_pool
import tests.helpers.factories.peri_scribe.geo.database


@pytest.mark.parametrize("damage", ["geometry", "attributes", "fingerprint"])
def test_fetch_snapshot_rows_rejects_invalid_normalized_evidence(damage: str) -> None:
    with contextlib.closing(sqlite3.connect(":memory:")) as connection:
        peri_scribe.geo.database.reset_database(connection)
        tests.helpers.factories.peri_scribe.geo.database.store(connection, 1)
        if damage == "fingerprint":
            connection.execute("UPDATE rows SET name = 'wrong metadata'")
        else:
            table = (
                "geometry_payloads" if damage == "geometry" else "attribute_payloads"
            )
            connection.execute(f"DELETE FROM {table}")
        with pytest.raises(ValueError, match=r"dictionary|fingerprint"):
            peri_scribe.geo.reading.fetch_snapshot_rows(
                connection,
                1,
                checksum="1",
                geometry_pool=spatial_data.geometry_pool.GeometryPool(),
            )


def test_read_geopackage_cached_borrows_caller_geometry_pool(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = (
        tmp_path
        / "feed"
        / peri_scribe.sources.snapshots.SourceFile(
            serial_number=1,
            last_edit_timestamp=1,
        ).relative_path
    )
    path.parent.mkdir(parents=True)
    path.write_bytes(b"source")
    expected = tests.helpers.factories.peri_scribe.geo.database.contents(1)
    monkeypatch.setattr(
        peri_scribe.geo.package,
        "read_geopackage",
        unittest.mock.Mock(return_value=expected),
    )
    pool = spatial_data.geometry_pool.GeometryPool()
    first = peri_scribe.geo.reading.read_geopackage_cached(path, geometry_pool=pool)
    second = peri_scribe.geo.reading.read_geopackage_cached(path, geometry_pool=pool)
    assert first.rows[0].record.geometry is second.rows[0].record.geometry
    assert (
        peri_scribe.geo.reading.read_geopackages_cached(
            [path],
            geometry_pool=pool,
        )[path]
        == expected
    )


def test_read_geopackages_cached_keeps_same_serial_in_different_feeds_separate(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = [
        tmp_path
        / name
        / peri_scribe.sources.snapshots.SourceFile(
            serial_number=1,
            last_edit_timestamp=1,
        ).relative_path
        for name in ("first-feed", "second-feed")
    ]
    for path in paths:
        path.parent.mkdir(parents=True)
        path.write_bytes(b"current")
    expected = tests.helpers.factories.peri_scribe.geo.database.contents(1)
    parse = unittest.mock.Mock(return_value=expected)
    monkeypatch.setattr(peri_scribe.geo.package, "read_geopackage", parse)
    assert peri_scribe.geo.reading.read_geopackages_cached(paths) == dict.fromkeys(
        paths,
        expected,
    )
    assert parse.call_count == len(paths)
    parse.reset_mock()
    assert peri_scribe.geo.reading.read_geopackages_cached(paths) == dict.fromkeys(
        paths,
        expected,
    )
    assert not parse.called


@pytest.mark.parametrize("named", [True, False])
def test_read_geopackages_cached_preserves_explicit_fallback(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    named: bool,
) -> None:
    path = tmp_path / ("000001,lastEdit=1.gpkg" if named else "unrecognized.gpkg")
    path.write_bytes(b"source")
    expected = tests.helpers.factories.peri_scribe.geo.database.contents(2)
    fallback = unittest.mock.Mock(return_value=expected)
    if named:
        monkeypatch.setattr(
            peri_scribe.geo.reading,
            "read_feed_batch",
            unittest.mock.Mock(side_effect=sqlite3.OperationalError("Unavailable")),
        )
    actual = peri_scribe.geo.reading.read_geopackages_cached(
        [path],
        read_fallback=fallback,
    )
    assert actual == {path: expected}
    fallback.assert_called_once_with(path)


def test_read_geopackages_cached_falls_back_for_unauthenticated_snapshot(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "feed"
    path = (
        source
        / peri_scribe.sources.snapshots.SourceFile(
            serial_number=1,
            last_edit_timestamp=1,
        ).relative_path
    )
    path.parent.mkdir(parents=True)
    path.write_bytes(b"before")
    original = tests.helpers.factories.peri_scribe.geo.database.contents(1)
    monkeypatch.setattr(
        peri_scribe.geo.package,
        "read_geopackage",
        unittest.mock.Mock(return_value=original),
    )
    peri_scribe.geo.reading.read_geopackages_cached([path])
    path.write_bytes(b"after")
    expected = tests.helpers.factories.peri_scribe.geo.database.contents(2)
    fallback = unittest.mock.Mock(return_value=expected)
    assert peri_scribe.geo.reading.read_geopackages_cached(
        [path],
        read_fallback=fallback,
    ) == {path: expected}
    fallback.assert_called_once_with(path)


def test_fetch_snapshot_batch_shares_geometry_and_isolates_mutable_attributes() -> None:
    original = tests.helpers.factories.peri_scribe.geo.database.contents(1)
    duplicate = dataclasses.replace(original, rows=(original.rows[0],) * 2)
    with contextlib.closing(sqlite3.connect(":memory:")) as connection:
        peri_scribe.geo.database.reset_database(connection)
        serials = (1, 2)
        for serial in serials:
            peri_scribe.geo.database.write_snapshot(
                connection,
                peri_scribe.sources.snapshots.SourceFile(
                    serial_number=serial,
                    last_edit_timestamp=1,
                ),
                1,
                1,
                duplicate,
                checksum="current",
            )
        connection.commit()
        assert connection.execute("SELECT count(*) FROM rows").fetchone()[0] == len(
            duplicate.rows,
        ) * len(serials)
        for table in ("geometry_payloads", "attribute_payloads"):
            assert (
                connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 1
            )
        pool = spatial_data.geometry_pool.GeometryPool()
        with unittest.mock.patch.object(
            pool,
            "from_wkb",
            wraps=pool.from_wkb,
        ) as decode:
            actual = peri_scribe.geo.reading.fetch_snapshot_batch(
                connection,
                {
                    pathlib.Path("first"): (1, "current"),
                    pathlib.Path("second"): (2, "current"),
                    pathlib.Path("stale"): (1, "changed"),
                },
                geometry_pool=pool,
            )
        assert decode.call_count == 1
        assert actual == {
            pathlib.Path("first"): duplicate,
            pathlib.Path("second"): duplicate,
        }
        first = actual[pathlib.Path("first")].rows[0]
        second = actual[pathlib.Path("second")].rows[1]
        assert first.record.geometry is second.record.geometry
        assert first.attributes is not second.attributes
        assert first.attributes["nested"] is not second.attributes["nested"]
        assert peri_scribe.geo.fingerprints.row_evidence_fingerprint(first) == (
            peri_scribe.geo.fingerprints.complete_row_fingerprint(first)
        )
        first.attributes["nested"] = [True, None]
        assert first.attributes != second.attributes
        assert peri_scribe.geo.fingerprints.row_evidence_fingerprint(first) != (
            first.evidence_fingerprint
        )


@pytest.mark.parametrize("table", ["geometry_payloads", "attribute_payloads"])
def test_fetch_snapshot_batch_rejects_missing_dictionary_references(table: str) -> None:
    with contextlib.closing(sqlite3.connect(":memory:")) as connection:
        peri_scribe.geo.database.reset_database(connection)
        tests.helpers.factories.peri_scribe.geo.database.store(connection, 1)
        connection.execute(f"DELETE FROM {table}")
        with pytest.raises(ValueError, match="missing dictionary"):
            peri_scribe.geo.reading.fetch_snapshot_batch(
                connection,
                {pathlib.Path("snapshot"): (1, "1")},
                geometry_pool=spatial_data.geometry_pool.GeometryPool(),
            )


def test_fetch_snapshot_batch_preserves_srid_and_coordinate_dimensions() -> None:
    original = tests.helpers.factories.peri_scribe.geo.database.contents(1)
    geometry = shapely.set_srid(shapely.Point(1, 2, 3), 4326)
    row = dataclasses.replace(
        original.rows[0],
        record=dataclasses.replace(original.rows[0].record, geometry=geometry),
    )
    snapshot = dataclasses.replace(original, rows=(row,))
    with contextlib.closing(sqlite3.connect(":memory:")) as connection:
        peri_scribe.geo.database.reset_database(connection)
        peri_scribe.geo.database.write_snapshot(
            connection,
            peri_scribe.sources.snapshots.SourceFile(
                serial_number=1,
                last_edit_timestamp=1,
            ),
            1,
            1,
            snapshot,
            checksum="current",
        )
        actual = peri_scribe.geo.reading.fetch_snapshot_batch(
            connection,
            {pathlib.Path("snapshot"): (1, "current")},
            geometry_pool=spatial_data.geometry_pool.GeometryPool(),
        )[pathlib.Path("snapshot")].rows[0]
        assert shapely.to_wkb(actual.record.geometry, include_srid=True) == (
            shapely.to_wkb(geometry, include_srid=True)
        )
