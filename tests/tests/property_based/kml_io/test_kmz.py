"""Tests for kml_io.kmz."""

from __future__ import annotations

import pathlib
import tempfile
import zipfile

import hypothesis

import kml_io.kmz
import tests.helpers.strategies.kml_io.kmz


@hypothesis.given(
    images=tests.helpers.strategies.kml_io.kmz.archive_images(),
    document=hypothesis.infer,
)
def test_write_archive_preserves_document_and_every_image(
    images: dict[str, bytes],
    document: str,
) -> None:
    expected = {
        kml_io.kmz.KMZ_DOCUMENT_FILENAME: document.encode("utf-8"),
        **images,
    }
    with tempfile.TemporaryDirectory() as directory:
        path = pathlib.Path(directory) / "fires.kmz"
        kml_io.kmz.write_archive(
            path,
            lambda stream: stream.write(document),
            images,
        )
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
            assert len(archive.namelist()) == len(expected)
            assert {name: archive.read(name) for name in archive.namelist()} == expected
