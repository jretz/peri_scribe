"""Exact bounded source reads preserve metadata, provenance and mutable ownership."""

import contextlib
import dataclasses
import functools
import pathlib
import sqlite3
import unittest.mock

import pytest

import peri_scribe.fires.bounded_sources
import peri_scribe.fires.complexes
import peri_scribe.fires.sources
import peri_scribe.geo.catalog
import peri_scribe.geo.compaction
import peri_scribe.geo.database
import peri_scribe.geo.fingerprints
import peri_scribe.models
import peri_scribe.sources.snapshots
import tests.helpers.factories.peri_scribe.geo.catalog


def test_open_catalog_keeps_metadata_without_payloads(tmp_path: pathlib.Path) -> None:
    path = tests.helpers.factories.peri_scribe.geo.catalog.create(tmp_path)
    with peri_scribe.geo.catalog.open_catalog(tmp_path) as catalog:
        assert len(catalog.entries) == len(
            tests.helpers.factories.peri_scribe.geo.catalog.rows(),
        )
        assert all(row.record.geometry is None for row in catalog.read.rows)
        assert all(row.attributes == {} for row in catalog.read.rows)
        assert catalog.read.paths == (path,) * 3
    with pytest.raises(sqlite3.ProgrammingError):
        catalog.connections[0].execute("SELECT 1")


def test_catalog_hydrate_preserves_exact_evidence_and_selected_order(
    tmp_path: pathlib.Path,
) -> None:
    tests.helpers.factories.peri_scribe.geo.catalog.create(tmp_path)
    expected = tests.helpers.factories.peri_scribe.geo.catalog.rows()
    with peri_scribe.geo.catalog.open_catalog(tmp_path) as catalog:
        read = catalog.hydrate((2, 0, 0))
        assert read.rows == (expected[2], expected[0], expected[0])
        assert all(
            peri_scribe.geo.fingerprints.row_evidence_fingerprint(row)
            == catalog.entries[index].row["evidence_fingerprint"]
            for index, row in zip((2, 0, 0), read.rows, strict=True)
        )
        nested = read.rows[0].attributes["nested"]
        assert isinstance(nested, list)
        nested.append("changed")
        assert catalog.hydrate((2,)).rows[0] == expected[2]


def test_catalog_records_preserves_geometry_without_attributes(
    tmp_path: pathlib.Path,
) -> None:
    tests.helpers.factories.peri_scribe.geo.catalog.create(tmp_path)
    with peri_scribe.geo.catalog.open_catalog(tmp_path) as catalog:
        actual = catalog.records((2, 0))
    expected = tests.helpers.factories.peri_scribe.geo.catalog.rows()
    assert actual == [expected[2].record, expected[0].record]


def test_catalog_weight_deduplicates_shared_references(tmp_path: pathlib.Path) -> None:
    tests.helpers.factories.peri_scribe.geo.catalog.create(tmp_path)
    with peri_scribe.geo.catalog.open_catalog(tmp_path) as catalog:
        assert catalog.weight((0, 0)) == catalog.weight((0,))
        assert catalog.weight((0, 1)) > catalog.weight((0,))


def test_catalog_observations_matches_complete_source_policy(
    tmp_path: pathlib.Path,
) -> None:
    path = tests.helpers.factories.peri_scribe.geo.catalog.create(tmp_path)
    rows = tests.helpers.factories.peri_scribe.geo.catalog.rows()
    expected = peri_scribe.fires.complexes.observations(rows, (path,) * 3, (), ())
    with peri_scribe.geo.catalog.open_catalog(tmp_path) as catalog:
        assert catalog.observations() == expected


def test_open_catalog_rejects_authoritative_source_changes(
    tmp_path: pathlib.Path,
) -> None:
    path = tests.helpers.factories.peri_scribe.geo.catalog.create(tmp_path)
    with (
        pytest.raises(OSError, match="Sources changed"),
        peri_scribe.geo.catalog.open_catalog(tmp_path),
    ):
        path.write_bytes(b"changed authoritative source")


def test_open_catalog_preserves_anonymous_anchor_adapter(
    tmp_path: pathlib.Path,
) -> None:
    rows = tests.helpers.factories.peri_scribe.geo.catalog.rows()
    tests.helpers.factories.peri_scribe.geo.catalog.create(
        tmp_path,
        (dataclasses.replace(rows[0], object_id=None),),
    )
    with (
        pytest.raises(peri_scribe.geo.catalog.UnavailableError),
        peri_scribe.geo.catalog.open_catalog(tmp_path),
    ):
        pytest.fail("Anonymous anchors require the complete adapter")


def test_prepare_groups_matches_complete_grouping(tmp_path: pathlib.Path) -> None:
    path = tests.helpers.factories.peri_scribe.geo.catalog.create(tmp_path)
    expected = peri_scribe.fires.sources.group_fire_sources(
        peri_scribe.fires.sources.ReadFireSources(
            rows=tests.helpers.factories.peri_scribe.geo.catalog.rows(),
            paths=(path,) * 3,
            memberships=(),
        ),
    )
    with peri_scribe.geo.catalog.open_catalog(tmp_path) as catalog:
        actual = peri_scribe.fires.bounded_sources.prepare_groups(catalog)
    assert actual.groups == expected.groups
    assert actual.fires == expected.fires


@pytest.mark.parametrize(
    "changes",
    [
        {"object_id": None},
        {"attributes_digest": None},
        {"geometry_digest": None},
        {"evidence_fingerprint": "incorrect"},
        {"attributes_size": -1},
        {"attributes_size": None},
        {"attributes_size": "invalid"},
        {"geometry_size": -1},
    ],
)
def test_metadata_row_rejects_unusable_anchors_hashes_and_admission_sizes(
    tmp_path: pathlib.Path,
    changes: dict[str, object],
) -> None:
    path = tests.helpers.factories.peri_scribe.geo.catalog.create(tmp_path)
    row = tests.helpers.factories.peri_scribe.geo.catalog.metadata(path, changes)
    with pytest.raises(peri_scribe.geo.catalog.UnavailableError):
        peri_scribe.geo.catalog.metadata_row(row)


def test_catalog_retains_membership_fallbacks_and_null_geometry(
    tmp_path: pathlib.Path,
) -> None:
    original = tests.helpers.factories.peri_scribe.geo.catalog.rows()[0]
    record = dataclasses.replace(
        original,
        record=dataclasses.replace(original.record, geometry=None),
        attributes={},
    )
    membership = peri_scribe.models.ComplexMembership(
        fire_identifier="standalone",
        complex_identifier="parent",
        complex_name="Parent",
    )
    path = tests.helpers.factories.peri_scribe.geo.catalog.create(
        tmp_path,
        (record,),
        (membership,),
    )
    with peri_scribe.geo.catalog.open_catalog(tmp_path) as catalog:
        assert catalog.hydrate((0,)).rows == (record,)
        assert catalog.records((0,)) == [record.record]
        assert catalog.weight((0,)) == len(b"{}")
        assert catalog.observations() == peri_scribe.fires.complexes.observations(
            (record,),
            (path,),
            (membership,),
            (path,),
        )


def test_catalog_accepts_authenticated_empty_snapshot(tmp_path: pathlib.Path) -> None:
    tests.helpers.factories.peri_scribe.geo.catalog.create(tmp_path, ())
    with peri_scribe.geo.catalog.open_catalog(tmp_path) as catalog:
        assert not catalog.entries
        assert not catalog.hydrate(()).rows
        assert catalog.records(()) == []
        assert catalog.observations() == []
        assert catalog.weight(()) == 0


def test_open_catalog_rejects_absent_source_inventory(tmp_path: pathlib.Path) -> None:
    with (
        pytest.raises(peri_scribe.geo.catalog.UnavailableError, match="No source"),
        peri_scribe.geo.catalog.open_catalog(tmp_path),
    ):
        pytest.fail("Empty inventories require the complete adapter")


def test_open_catalog_rejects_a_changed_source_inventory(
    tmp_path: pathlib.Path,
) -> None:
    path = tests.helpers.factories.peri_scribe.geo.catalog.create(tmp_path)
    with (
        pytest.raises(OSError, match="Sources changed"),
        peri_scribe.geo.catalog.open_catalog(tmp_path),
    ):
        path.unlink()


def test_open_catalog_rejects_receipt_mismatch_without_exposing_rows(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tests.helpers.factories.peri_scribe.geo.catalog.create(tmp_path)
    database = peri_scribe.sources.snapshots.record_cache_database_path(
        path.parent.parent,
    )
    with contextlib.closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE snapshots SET checksum = 'changed'")
        connection.commit()
    monkeypatch.setattr(
        peri_scribe.geo.database,
        "ensure_database_current",
        unittest.mock.Mock(),
    )
    with (
        pytest.raises(peri_scribe.geo.catalog.UnavailableError, match="unavailable"),
        peri_scribe.geo.catalog.open_catalog(tmp_path),
    ):
        pytest.fail("Wrong receipts cannot authenticate rows")


@pytest.mark.parametrize("operation", ["hydrate", "records", "observations"])
@pytest.mark.parametrize("storage", ["payload", "dictionary"])
def test_catalog_rejects_payload_corruption_before_serving_complete_work(
    tmp_path: pathlib.Path,
    operation: str,
    storage: str,
) -> None:
    path = tests.helpers.factories.peri_scribe.geo.catalog.create(tmp_path)
    database = peri_scribe.sources.snapshots.record_cache_database_path(
        path.parent.parent,
    )
    table = "attribute_payloads" if operation == "observations" else "geometry_payloads"
    with contextlib.closing(sqlite3.connect(database)) as connection:
        if storage == "dictionary":
            connection.execute(
                "INSERT INTO codec_dictionaries (id, value) VALUES (1, ?)",
                ("damaged",),
            )
        else:
            connection.execute(f"UPDATE {table} SET value = ?", (b"damaged",))
        connection.commit()
    with peri_scribe.geo.catalog.open_catalog(tmp_path) as catalog:
        selected = {
            "observations": catalog.observations,
            "hydrate": functools.partial(catalog.hydrate, (0,)),
            "records": functools.partial(catalog.records, (0,)),
        }[operation]
        with pytest.raises(peri_scribe.geo.catalog.UnavailableError):
            selected()


def test_catalog_rejects_nonobject_ownership_attributes(tmp_path: pathlib.Path) -> None:
    path = tests.helpers.factories.peri_scribe.geo.catalog.create(tmp_path)
    database = peri_scribe.sources.snapshots.record_cache_database_path(
        path.parent.parent,
    )
    with (
        peri_scribe.geo.catalog.open_catalog(tmp_path) as catalog,
        contextlib.closing(sqlite3.connect(":memory:")) as malformed,
    ):
        malformed.row_factory = sqlite3.Row
        peri_scribe.geo.database.reset_database(malformed)
        key = peri_scribe.geo.database.intern_payload(
            malformed,
            peri_scribe.geo.database.PayloadKind.ATTRIBUTES,
            "[]",
        )
        changed = dataclasses.replace(catalog, connections=(malformed,))
        with pytest.raises(
            peri_scribe.geo.catalog.UnavailableError,
            match="object",
        ):
            changed.row_declarations(0, {key: [0]})
    assert database.exists()


def test_catalog_closes_every_connection_when_consumer_fails(
    tmp_path: pathlib.Path,
) -> None:
    tests.helpers.factories.peri_scribe.geo.catalog.create(tmp_path)
    message = "consumer failure"
    consumer = unittest.mock.Mock(side_effect=RuntimeError(message))
    with (
        pytest.raises(RuntimeError, match=message),
        peri_scribe.geo.catalog.open_catalog(tmp_path) as catalog,
    ):
        consumer(catalog)
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        consumer.call_args.args[0].connections[0].execute("SELECT 1")


def test_catalog_separates_payload_identity_between_feed_connections(
    tmp_path: pathlib.Path,
) -> None:
    expected = tests.helpers.factories.peri_scribe.geo.catalog.rows()
    first = tests.helpers.factories.peri_scribe.geo.catalog.create(tmp_path / "first")
    second = tests.helpers.factories.peri_scribe.geo.catalog.create(tmp_path / "second")
    with peri_scribe.geo.catalog.open_catalog(tmp_path) as catalog:
        assert catalog.read.paths == (first,) * len(expected) + (second,) * len(
            expected,
        )
        assert catalog.hydrate((3, 0)).rows == (expected[0], expected[0])
        assert catalog.weight((3, 0)) == catalog.weight((0,)) + catalog.weight((3,))


def test_catalog_copies_mutable_attributes_for_distinct_occurrences(
    tmp_path: pathlib.Path,
) -> None:
    original = tests.helpers.factories.peri_scribe.geo.catalog.rows()[0]
    rows = (original, dataclasses.replace(original, object_id=9))
    tests.helpers.factories.peri_scribe.geo.catalog.create(tmp_path, rows)
    with peri_scribe.geo.catalog.open_catalog(tmp_path) as catalog:
        hydrated = catalog.hydrate((0, 1))
        first = hydrated.rows[0].attributes["nested"]
        second = hydrated.rows[1].attributes["nested"]
        assert isinstance(first, list)
        first.append("independent mutation")
        assert first != second
        assert catalog.hydrate((1,)).rows == (rows[1],)


def test_catalog_read_lease_retains_payloads_through_atomic_cache_replacement(
    tmp_path: pathlib.Path,
) -> None:
    path = tests.helpers.factories.peri_scribe.geo.catalog.create(tmp_path)
    database = peri_scribe.sources.snapshots.record_cache_database_path(
        path.parent.parent,
    )
    original_inode = database.stat().st_ino
    expected = tests.helpers.factories.peri_scribe.geo.catalog.rows()
    with peri_scribe.geo.catalog.open_catalog(tmp_path) as catalog:
        with peri_scribe.geo.compaction.writer_lock(database):
            assert peri_scribe.geo.compaction.compact(
                database,
                peri_scribe.geo.database.RECORD_CACHE_SCHEMA,
                force=True,
            )
        assert database.stat().st_ino != original_inode
        assert catalog.hydrate((0, 1, 2)).rows == expected
        assert catalog.records((0, 1, 2)) == [row.record for row in expected]
        assert catalog.observations() == peri_scribe.fires.complexes.observations(
            expected,
            (path,) * len(expected),
            (),
            (),
        )
