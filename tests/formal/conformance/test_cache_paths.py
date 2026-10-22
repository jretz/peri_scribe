import compression.zstd
import contextlib
import json
import pathlib
import sqlite3

import peri_scribe.geo.database
import peri_scribe.geo.payload_storage
import spatial_data.payload_codec
import tests.formal.helpers.cache_paths
import tests.helpers.factories.peri_scribe.geo.database


def test_observe_preserves_committed_dictionary_payload_bytes(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "cache.sqlite"
    with contextlib.closing(sqlite3.connect(path)) as writer:
        peri_scribe.geo.database.reset_database(writer)
        tests.helpers.factories.peri_scribe.geo.database.store(writer, 1)
        writer.commit()
        before = tests.formal.helpers.cache_paths.observe(path)
        dictionary = compression.zstd.train_dict(
            [
                f'{{"sample":{index},"repeated":"abcdef"}}'.encode()
                for index in range(100)
            ],
            512,
        ).dict_content
        logical = json.dumps({"sample": 1, "repeated": "abcdef" * 1000})
        encoded, marker, size = peri_scribe.geo.payload_storage.encode(
            logical,
            dictionary=dictionary,
        )
        assert isinstance(encoded, bytes)
        assert encoded[0] & spatial_data.payload_codec.DICTIONARY_FLAG
        writer.execute(
            "INSERT INTO codec_dictionaries (id, value) VALUES (42, ?)",
            (dictionary,),
        )
        writer.execute(
            "UPDATE attribute_payloads SET value = ?, encoding = ?, "
            "original_size = ?, dictionary_id = 42",
            (encoded, marker, size),
        )
        assert tests.formal.helpers.cache_paths.observe(path) == before
        writer.commit()
        expected = tuple(
            (
                table,
                tuple((*row[:-1], logical) for row in rows)
                if table == "rows"
                else rows,
            )
            for table, rows in before
        )
        assert tests.formal.helpers.cache_paths.observe(path) == expected
