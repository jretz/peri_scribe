"""Derived dictionaries publish atomically with exact logical payload identities."""

import compression.zstd
import contextlib
import hashlib
import pathlib
import sqlite3
import unittest.mock

import pytest

import peri_scribe.geo.database
import peri_scribe.geo.dictionaries
import peri_scribe.geo.payload_storage
import spatial_data.payload_codec


def test_payload_decode_requires_matching_logical_size_and_encoding() -> None:
    assert peri_scribe.geo.payload_storage.decode(b"abc", 0, 3) == b"abc"
    assert peri_scribe.geo.payload_storage.decode("火", 0, 3, text=True) == "火"
    with pytest.raises(ValueError, match="size"):
        peri_scribe.geo.payload_storage.decode(b"abc", 0, 4)
    with pytest.raises(ValueError, match="encoding"):
        peri_scribe.geo.payload_storage.decode(b"abc", 9, 3)


def test_payload_encode_retains_logical_bytes_when_optional_codec_cannot_store_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        spatial_data.payload_codec,
        "encode",
        unittest.mock.Mock(side_effect=ValueError("optional codec limit")),
    )
    assert peri_scribe.geo.payload_storage.encode("火") == ("火", 0, 3)


@pytest.mark.parametrize("commit", [False, True])
@pytest.mark.parametrize("dictionary_damage", [b"changed", "changed", 7, 1.5])
def test_dictionary_and_references_publish_or_rollback_as_one_generation(
    tmp_path: pathlib.Path,
    dictionary_damage: bytes | str | float,
    *,
    commit: bool,
) -> None:
    path = tmp_path / "cache.sqlite"
    values = {
        index: f'{{"sample":{index},"value":"' + "abcdefgh" * 600 + '"}'
        for index in range(40)
    }
    with (
        contextlib.closing(sqlite3.connect(path)) as writer,
        contextlib.closing(sqlite3.connect(path)) as reader,
    ):
        reader.row_factory = sqlite3.Row
        peri_scribe.geo.database.reset_database(writer)
        kind = peri_scribe.geo.database.PayloadKind.ATTRIBUTES
        identifiers = {
            peri_scribe.geo.database.intern_payload(writer, kind, value): value
            for value in values.values()
        }
        writer.commit()
        before = writer.execute(
            "SELECT * FROM attribute_payloads ORDER BY id",
        ).fetchall()
        peri_scribe.geo.payload_storage.prepare_dictionary(writer)
        assert writer.execute("SELECT count(*) FROM codec_dictionaries").fetchone() == (
            1,
        )
        assert not reader.execute("SELECT * FROM codec_dictionaries").fetchall()
        if commit:
            writer.commit()
        else:
            writer.rollback()
            assert (
                writer.execute(
                    "SELECT * FROM attribute_payloads ORDER BY id",
                ).fetchall()
                == before
            )
        assert (
            dict(
                peri_scribe.geo.dictionaries.payload_values(
                    reader,
                    kind,
                    set(identifiers),
                ),
            )
            == identifiers
        )
        assert reader.execute("SELECT count(*) FROM codec_dictionaries").fetchone()[
            0
        ] == int(commit)
        if commit:
            for identifier, value in identifiers.items():
                assert (
                    peri_scribe.geo.database.intern_payload(writer, kind, value)
                    == identifier
                )
            peri_scribe.geo.payload_storage.prepare_dictionary(writer)
            writer.commit()
            assert (
                reader.execute("SELECT count(*) FROM codec_dictionaries").fetchone()[0]
                == 1
            )
            reader.execute(
                "UPDATE codec_dictionaries SET value = ?",
                (dictionary_damage,),
            )
            with pytest.raises(ValueError, match="dictionary"):
                list(
                    peri_scribe.geo.dictionaries.payload_values(
                        reader,
                        kind,
                        set(identifiers),
                    ),
                )


def test_training_sparse_samples_and_total_bytes_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with contextlib.closing(sqlite3.connect(":memory:")) as connection:
        peri_scribe.geo.database.reset_database(connection)
        connection.executemany(
            "INSERT INTO attribute_payloads (id,digest,value,original_size) "
            "VALUES (?,?,?,?)",
            [(index, b"digest", "sample" * 5, 30) for index in range(20)],
        )
        monkeypatch.setattr(peri_scribe.geo.payload_storage, "TRAINING_SAMPLES", 3)
        monkeypatch.setattr(
            peri_scribe.geo.payload_storage,
            "MAXIMUM_TRAINING_BYTES",
            45,
        )
        assert peri_scribe.geo.payload_storage.training_samples(connection) == [
            b"sample" * 5,
            (b"sample" * 5)[:15],
        ]


def test_dictionary_training_failure_keeps_independently_decodable_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with contextlib.closing(sqlite3.connect(":memory:")) as connection:
        peri_scribe.geo.database.reset_database(connection)
        monkeypatch.setattr(
            peri_scribe.geo.payload_storage,
            "training_samples",
            unittest.mock.Mock(return_value=[b"sample" * 1000] * 8),
        )
        monkeypatch.setattr(
            compression.zstd,
            "train_dict",
            unittest.mock.Mock(side_effect=compression.zstd.ZstdError("small corpus")),
        )
        peri_scribe.geo.payload_storage.prepare_dictionary(connection)
        assert not peri_scribe.geo.payload_storage.dictionaries(connection)


def test_digest_is_checked_after_decompressing_complete_logical_payload() -> None:
    with contextlib.closing(sqlite3.connect(":memory:")) as connection:
        connection.row_factory = sqlite3.Row
        peri_scribe.geo.database.reset_database(connection)
        kind = peri_scribe.geo.database.PayloadKind.ATTRIBUTES
        key = peri_scribe.geo.database.intern_payload(connection, kind, "x" * 1000)
        connection.execute(
            "UPDATE attribute_payloads SET digest = ?",
            (hashlib.sha256(b"wrong").digest(),),
        )
        with pytest.raises(ValueError, match="stored digest"):
            list(peri_scribe.geo.dictionaries.payload_values(connection, kind, {key}))


def test_interrupted_dictionary_rewrite_rolls_back_its_partial_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with contextlib.closing(sqlite3.connect(":memory:")) as connection:
        peri_scribe.geo.database.reset_database(connection)
        for value in ("first", "second"):
            peri_scribe.geo.database.intern_payload(
                connection,
                peri_scribe.geo.database.PayloadKind.ATTRIBUTES,
                value,
            )
        connection.commit()
        before = connection.execute(
            "SELECT * FROM attribute_payloads ORDER BY id",
        ).fetchall()
        monkeypatch.setattr(
            peri_scribe.geo.payload_storage,
            "training_samples",
            unittest.mock.Mock(return_value=[b"sample" * 1000] * 8),
        )
        monkeypatch.setattr(
            compression.zstd,
            "train_dict",
            unittest.mock.Mock(
                return_value=unittest.mock.Mock(dict_content=b"dictionary"),
            ),
        )
        monkeypatch.setattr(
            peri_scribe.geo.payload_storage,
            "encode",
            unittest.mock.Mock(
                side_effect=[("first", 0, 5), RuntimeError("interrupted")],
            ),
        )
        with pytest.raises(RuntimeError, match="interrupted"), connection:
            peri_scribe.geo.payload_storage.prepare_dictionary(connection)
        assert not peri_scribe.geo.payload_storage.dictionaries(connection)
        assert (
            connection.execute(
                "SELECT * FROM attribute_payloads ORDER BY id",
            ).fetchall()
            == before
        )
