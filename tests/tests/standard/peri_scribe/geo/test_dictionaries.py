"""Exact normalized payloads preserve all ordered source occurrences."""

import contextlib
import hashlib
import json
import pathlib
import sqlite3

import pytest

import peri_scribe.geo.database
import peri_scribe.geo.dictionaries
import peri_scribe.geo.reading
import spatial_data.geometry_pool
import tests.helpers.factories.peri_scribe.geo.database


@pytest.mark.parametrize("payload", [b"damaged", "invalid geometry type"])
def test_payload_values_rejects_changed_dictionary_encoding(
    payload: bytes | str,
) -> None:
    with contextlib.closing(sqlite3.connect(":memory:")) as connection:
        connection.row_factory = sqlite3.Row
        peri_scribe.geo.database.reset_database(connection)
        key = peri_scribe.geo.database.intern_payload(
            connection,
            peri_scribe.geo.database.PayloadKind.GEOMETRY,
            b"original",
        )
        connection.execute("UPDATE geometry_payloads SET value = ?", (payload,))
        with pytest.raises(ValueError, match=r"stored digest|header"):
            list(
                peri_scribe.geo.dictionaries.payload_values(
                    connection,
                    peri_scribe.geo.database.PayloadKind.GEOMETRY,
                    {key},
                ),
            )


def test_payload_values_reads_more_than_one_parameter_batch() -> None:
    expected = {index: str(index) for index in range(1, 702)}
    with contextlib.closing(sqlite3.connect(":memory:")) as connection:
        connection.row_factory = sqlite3.Row
        peri_scribe.geo.database.reset_database(connection)
        connection.executemany(
            "INSERT INTO attribute_payloads (id, digest, value, original_size) "
            "VALUES (?, ?, ?, ?)",
            [
                (
                    key,
                    hashlib.sha256(value.encode()).digest(),
                    value,
                    len(value.encode()),
                )
                for key, value in expected.items()
            ],
        )
        assert (
            dict(
                peri_scribe.geo.dictionaries.payload_values(
                    connection,
                    peri_scribe.geo.database.PayloadKind.ATTRIBUTES,
                    set(expected),
                ),
            )
            == expected
        )


def test_decoded_payloads_rejects_nonobject_attribute_documents() -> None:
    with contextlib.closing(sqlite3.connect(":memory:")) as connection:
        connection.row_factory = sqlite3.Row
        peri_scribe.geo.database.reset_database(connection)
        tests.helpers.factories.peri_scribe.geo.database.store(connection, 1)
        payload = json.dumps(["invalid attribute bag"])
        connection.execute(
            "UPDATE attribute_payloads SET value = ?, digest = ?, "
            "encoding = 0, original_size = ?",
            (payload, hashlib.sha256(payload.encode()).digest(), len(payload.encode())),
        )
        with pytest.raises(ValueError, match="complete JSON object"):
            peri_scribe.geo.reading.fetch_snapshot_batch(
                connection,
                {pathlib.Path("snapshot"): (1, "1")},
                geometry_pool=spatial_data.geometry_pool.GeometryPool(),
            )
