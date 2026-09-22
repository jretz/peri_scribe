"""Keep archive compatibility and interrupted publication behavior stable."""

import pathlib
import zipfile

import pytest

import kml_io.kmz
import tests.helpers.doubles.kml_io.kmz


def test_write_archive_writes_compressed_document(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "output.kmz"
    kml_io.kmz.write_archive(
        path,
        lambda stream: stream.write("<kml/>"),
        None,
    )
    with zipfile.ZipFile(path) as archive:
        assert archive.read("doc.kml") == b"<kml/>"
        assert archive.getinfo("doc.kml").compress_type == zipfile.ZIP_DEFLATED


def test_write_archive_writes_images(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "output.kmz"
    images = {"area.png": b"\x89PNG\r\n\x1a\n", "area.svg": b"<svg/>"}
    kml_io.kmz.write_archive(
        path,
        lambda stream: stream.write("<kml/>"),
        images,
    )
    with zipfile.ZipFile(path) as archive:
        assert {name: archive.read(name) for name in images} == images
        assert archive.getinfo("area.png").compress_type == zipfile.ZIP_STORED
        assert archive.getinfo("area.svg").compress_type == zipfile.ZIP_DEFLATED


def test_write_kmz_atomic_replacement_and_failed_write_preserve_complete_file(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "maps/output.kmz"
    kml_io.kmz.write_kmz(
        output,
        lambda stream: stream.write("<kml>old</kml>"),
    )
    previous = output.read_bytes()

    fail_after_partial_write = (
        tests.helpers.doubles.kml_io.kmz.make_interrupted_archive_writer(
            output=output,
            previous=previous,
        )
    )

    with monkeypatch.context() as patch:
        patch.setattr(
            kml_io.kmz,
            "write_archive",
            fail_after_partial_write,
        )
        with pytest.raises(OSError, match="disk failure"):
            kml_io.kmz.write_kmz(
                output,
                lambda stream: stream.write("<kml>new</kml>"),
            )
    assert output.read_bytes() == previous
    assert list(output.parent.iterdir()) == [output]
    kml_io.kmz.write_kmz(
        output,
        lambda stream: stream.write("<kml>new</kml>"),
    )
    with zipfile.ZipFile(output) as archive:
        assert archive.read("doc.kml") == b"<kml>new</kml>"


def test_write_kmz_uses_zip_2_0_for_reader_compatibility(
    tmp_path: pathlib.Path,
) -> None:
    output = tmp_path / "fires.kmz"
    kml_io.kmz.write_kmz(
        output,
        lambda stream: stream.write("<kml/>"),
        {"plot.png": b"plot image"},
    )
    with zipfile.ZipFile(output) as archive:
        zip_2_0 = 20
        assert all(member.extract_version <= zip_2_0 for member in archive.infolist())


def test_write_kmz_preserves_public_archive_after_serialization_failure(
    tmp_path: pathlib.Path,
) -> None:
    output = tmp_path / "fires.kmz"
    kml_io.kmz.write_kmz(output, lambda stream: stream.write("<kml/>"))
    previous = output.read_bytes()
    with pytest.raises(ValueError, match="serialization failed"):
        kml_io.kmz.write_kmz(
            output,
            tests.helpers.doubles.kml_io.kmz.interrupted_document,
        )
    assert output.read_bytes() == previous
    assert list(tmp_path.iterdir()) == [output]
