"""Tests for peri_scribe.kml.builder."""

from __future__ import annotations

import pathlib
import tempfile
import zipfile

import hypothesis

import peri_scribe.kml.builder
import tests.helpers.strategies.peri_scribe.kml.builder


@hypothesis.given(
    images=tests.helpers.strategies.peri_scribe.kml.builder.archive_images(),
    document=hypothesis.infer,
)
def test_write_archive_preserves_document_and_every_image(
    images: dict[str, bytes],
    document: str,
) -> None:
    expected = {
        peri_scribe.kml.builder.KMZ_DOCUMENT_FILENAME: document.encode("utf-8"),
        **images,
    }
    with tempfile.TemporaryDirectory() as directory:
        path = pathlib.Path(directory) / "fires.kmz"
        peri_scribe.kml.builder.write_archive(path, document, images)
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
            assert len(archive.namelist()) == len(expected)
            assert {name: archive.read(name) for name in archive.namelist()} == expected
